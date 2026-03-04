import json
import logging
import os
from datetime import datetime

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, render_template_string

# ──────────────────────────── 配置 ────────────────────────────
FEISHU_WEBHOOK = os.getenv(
    "FEISHU_WEBHOOK",
    "https://open.feishu.cn/open-apis/bot/v2/hook/c5678c43-f33f-47f1-ad5e-f4009bd7b50c",
)
CDN_JSON_URL = "https://cdn.jsdelivr.net/gh/hu-qi/trending-in-one/raw/zhihu-search/{date}.json"
CDN_MD_URL = "https://cdn.jsdelivr.net/gh/hu-qi/trending-in-one/archives/zhihu-search/{date}.md"
TZ = pytz.timezone(os.getenv("TZ", "Asia/Shanghai"))
PORT = int(os.getenv("PORT", 1000))

# ──────────────────────────── 日志 ────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ──────────────────────────── Flask ────────────────────────────
app = Flask(__name__)

# 保存最近的抓取记录（内存中保留最近 50 条）
fetch_history: list[dict] = []
MAX_HISTORY = 50


# ──────────────────────────── 核心逻辑 ────────────────────────────
def fetch_zhihu_hot(date_str: str | None = None) -> dict | None:
    """从 CDN 获取指定日期的知乎热榜 JSON 数据。"""
    if date_str is None:
        date_str = datetime.now(TZ).strftime("%Y-%m-%d")

    url = CDN_JSON_URL.format(date=date_str)
    log.info("正在获取知乎热榜: %s", url)

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        log.info("获取成功，共 %d 条热搜", len(data) if isinstance(data, list) else 0)
        return {"date": date_str, "items": data}
    except requests.RequestException as e:
        log.error("获取热榜失败: %s", e)
        return None


def build_feishu_message(result: dict) -> dict:
    """将热榜数据构建为飞书富文本消息。"""
    items = result["items"]
    date_str = result["date"]

    if not isinstance(items, list) or len(items) == 0:
        return {
            "msg_type": "text",
            "content": {"text": f"📋 知乎热榜 ({date_str})\n\n暂无数据"},
        }

    # 取前 30 条
    top_items = items[:30]
    lines = []
    for i, item in enumerate(top_items, 1):
        title = item.get("title") or item.get("query") or item.get("display_query") or str(item)
        url = item.get("url") or item.get("link") or ""
        heat = item.get("heat") or item.get("hot") or ""

        line = f"{i}. {title}"
        if heat:
            line += f"  🔥{heat}"
        if url:
            line += f"\n   {url}"
        lines.append(line)

    md_url = CDN_MD_URL.format(date=date_str)
    text = (
        f"📋 知乎热榜 ({date_str})\n\n"
        + "\n\n".join(lines)
        + f"\n\n📎 完整存档: {md_url}"
    )

    # 飞书文本消息（限制 4096 字符）
    if len(text) > 4000:
        text = text[:4000] + "\n\n... (已截断)"

    return {"msg_type": "text", "content": {"text": text}}


def send_to_feishu(message: dict) -> bool:
    """发送消息到飞书 Webhook。"""
    log.info("正在推送飞书消息...")
    try:
        resp = requests.post(
            FEISHU_WEBHOOK,
            json=message,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") == 0 or body.get("StatusCode") == 0:
            log.info("飞书推送成功")
            return True
        log.warning("飞书返回异常: %s", body)
        return False
    except requests.RequestException as e:
        log.error("飞书推送失败: %s", e)
        return False


def job_fetch_and_push():
    """定时任务：抓取热榜 + 飞书推送。"""
    now = datetime.now(TZ)
    date_str = now.strftime("%Y-%m-%d")
    log.info("===== 定时任务触发 [%s %s] =====", date_str, now.strftime("%H:%M:%S"))

    result = fetch_zhihu_hot(date_str)
    if result is None:
        record = {"time": now.isoformat(), "date": date_str, "status": "fetch_failed"}
        fetch_history.append(record)
        if len(fetch_history) > MAX_HISTORY:
            fetch_history.pop(0)
        return

    msg = build_feishu_message(result)
    ok = send_to_feishu(msg)

    record = {
        "time": now.isoformat(),
        "date": date_str,
        "status": "success" if ok else "push_failed",
        "count": len(result["items"]) if isinstance(result["items"], list) else 0,
    }
    fetch_history.append(record)
    if len(fetch_history) > MAX_HISTORY:
        fetch_history.pop(0)


# ──────────────────────────── 定时调度 ────────────────────────────
scheduler = BackgroundScheduler(timezone=TZ)
# 每天 11:00, 18:00, 23:00 执行
scheduler.add_job(job_fetch_and_push, "cron", hour="11,18,23", minute=0, id="zhihu_hot")
scheduler.start()
log.info("定时任务已启动: 每天 11:00, 18:00, 23:00 抓取知乎热榜并推送飞书")


# ──────────────────────────── Web 路由 ────────────────────────────
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>知乎热榜监控</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, "Microsoft YaHei", sans-serif;
               background: #f5f6f7; color: #333; padding: 20px; }
        .container { max-width: 800px; margin: 0 auto; }
        h1 { text-align: center; margin-bottom: 10px; font-size: 24px; }
        .subtitle { text-align: center; color: #999; margin-bottom: 30px; font-size: 14px; }
        .card { background: #fff; border-radius: 8px; padding: 20px; margin-bottom: 16px;
                box-shadow: 0 1px 3px rgba(0,0,0,.08); }
        .card h2 { font-size: 16px; margin-bottom: 12px; color: #0066ff; }
        .status-row { display: flex; justify-content: space-between; padding: 8px 0;
                      border-bottom: 1px solid #f0f0f0; font-size: 14px; }
        .status-row:last-child { border-bottom: none; }
        .badge { padding: 2px 8px; border-radius: 4px; font-size: 12px; }
        .badge-ok { background: #e6f7e6; color: #389e0d; }
        .badge-fail { background: #fff1f0; color: #cf1322; }
        table { width: 100%; border-collapse: collapse; font-size: 14px; }
        th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid #f0f0f0; }
        th { color: #999; font-weight: normal; }
        .empty { text-align: center; color: #ccc; padding: 30px; }
        .btn { display: inline-block; padding: 8px 20px; background: #0066ff; color: #fff;
               border: none; border-radius: 6px; cursor: pointer; font-size: 14px;
               text-decoration: none; }
        .btn:hover { background: #0050cc; }
        .actions { text-align: center; margin-bottom: 20px; }
    </style>
</head>
<body>
<div class="container">
    <h1>📊 知乎热榜监控</h1>
    <p class="subtitle">定时抓取: 每天 11:00 / 18:00 / 23:00 → 飞书推送</p>

    <div class="actions">
        <a class="btn" href="/trigger" onclick="fetch('/trigger').then(()=>location.reload());return false;">
            手动触发抓取
        </a>
    </div>

    <div class="card">
        <h2>服务状态</h2>
        <div class="status-row"><span>运行状态</span><span class="badge badge-ok">运行中</span></div>
        <div class="status-row"><span>当前时间</span><span>{{ now }}</span></div>
        <div class="status-row"><span>累计执行</span><span>{{ history|length }} 次</span></div>
    </div>

    <div class="card">
        <h2>执行记录</h2>
        {% if history %}
        <table>
            <thead><tr><th>时间</th><th>日期</th><th>条数</th><th>状态</th></tr></thead>
            <tbody>
            {% for h in history|reverse %}
            <tr>
                <td>{{ h.time[:19] }}</td>
                <td>{{ h.date }}</td>
                <td>{{ h.count|default('-') }}</td>
                <td><span class="badge {{ 'badge-ok' if h.status == 'success' else 'badge-fail' }}">
                    {{ h.status }}</span></td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
        {% else %}
        <p class="empty">暂无执行记录，等待定时任务触发或手动触发</p>
        {% endif %}
    </div>
</div>
</body>
</html>
"""


@app.route("/")
def index():
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    return render_template_string(HTML_TEMPLATE, now=now, history=fetch_history)


@app.route("/trigger")
def trigger():
    """手动触发一次抓取。"""
    job_fetch_and_push()
    return jsonify({"msg": "已触发", "history": fetch_history[-1] if fetch_history else None})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now(TZ).isoformat()})


@app.route("/history")
def history_api():
    return jsonify(fetch_history)


# ──────────────────────────── 启动 ────────────────────────────
if __name__ == "__main__":
    log.info("Web 服务启动于端口 %d", PORT)
    app.run(host="0.0.0.0", port=PORT)
