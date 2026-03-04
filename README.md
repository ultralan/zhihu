# 知乎热榜自动爬取 & 飞书推送

定时从 CDN 获取知乎热榜数据，推送到飞书群机器人。

## 快速启动

```bash
# 克隆代码后，一行命令启动
docker-compose up -d --build
```

## 访问

| 地址 | 说明 |
|------|------|
| `http://localhost:1000` | 监控面板 |
| `http://localhost:1000/trigger` | 手动触发抓取 |
| `http://localhost:1000/health` | 健康检查 |
| `http://localhost:1000/history` | 历史记录 JSON |

## 定时规则

每天 **11:00 / 18:00 / 23:00**（北京时间）自动抓取并推送飞书。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FEISHU_WEBHOOK` | (已内置) | 飞书机器人 Webhook 地址 |
| `TZ` | `Asia/Shanghai` | 时区 |
| `PORT` | `1000` | Web 服务端口 |

## 停止服务

```bash
docker-compose down
```
