# LLM API Gateway · 大模型 API 网关

> 个人开源复刻 New API / One API 核心能力的 LLM 统一接入网关。

## 核心特性

- **多模型统一接入**：DeepSeek / 通义千问 / GPT 统一为 OpenAI 兼容接口，按模型前缀自动路由
- **Key 管理与限流**：客户端 Key 签发、令牌桶限流（RPM）、按 Key 用量审计
- **调用日志**：SQLite 记录每次调用（模型/令牌数/耗时/状态）
- **故障降级路由**：上游异常自动按优先级切换备用模型
- **Mock 模式**：无上游 Key 时返回模拟响应，便于联调与演示
- **Docker 私有化部署**：附 Dockerfile / docker-compose.yml

## 快速开始

```bash
pip install -r requirements.txt
uvicorn gateway:app --port 8400

curl -X POST localhost:8400/v1/chat/completions \
  -H 'X-Api-Key: demo-key-001' \
  -H 'Content-Type: application/json' \
  -d '{"model":"deepseek","messages":[{"role":"user","content":"hi"}]}'

curl localhost:8400/admin/usage -H 'X-Admin-Key: admin123'
```

## 架构

```
client → [鉴权 → 限流 → 路由(模型前缀) → 上游适配 → 失败降级] → 响应
                    ↘ 用量与日志(SQLite) ↙
```

## License

MIT
