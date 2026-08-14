#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM API Gateway - 多模型统一接入网关（对标 New API/One API 核心能力）。"""
import json, os, sqlite3, time
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

DB = "gateway.db"
CLIENT_KEYS = {"demo-key-001": {"name": "demo", "rpm": 10}, "demo-key-002": {"name": "test", "rpm": 60}}
ADMIN_KEY = os.environ.get("ADMIN_KEY", "admin123")

PROVIDERS = {
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "key_env": "DEEPSEEK_API_KEY", "priority": 1},
    "qwen": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus", "key_env": "QWEN_API_KEY", "priority": 2},
    "gpt": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "key_env": "OPENAI_API_KEY", "priority": 3},
}
FALLBACK_ORDER = sorted(PROVIDERS, key=lambda k: PROVIDERS[k]["priority"])

app = FastAPI(title="LLM API Gateway")

def db():
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS calls "
                 "(id INTEGER PRIMARY KEY, client TEXT, model TEXT, provider TEXT, status TEXT, latency_ms INT, ts REAL)")
    return conn

class Bucket:  # 令牌桶限流
    def __init__(self, rpm): self.rpm, self.tokens, self.ts = rpm, float(rpm), time.time()
    def allow(self):
        now = time.time()
        self.tokens = min(self.rpm, self.tokens + (now - self.ts) * self.rpm / 60)
        self.ts = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False

buckets = {k: Bucket(v["rpm"]) for k, v in CLIENT_KEYS.items()}

class ChatRequest(BaseModel):
    model: str = "deepseek"
    messages: list
    stream: bool = False

def log_call(client, model, provider, status, latency_ms):
    with db() as conn:
        conn.execute("INSERT INTO calls(client, model, provider, status, latency_ms, ts) VALUES(?,?,?,?,?,?)",
                     (client, model, provider, status, latency_ms, time.time()))

def call_upstream(provider, body):
    import requests
    cfg = PROVIDERS[provider]
    key = os.environ.get(cfg["key_env"])
    if not key:  # Mock
        return {"choices": [{"message": {"role": "assistant",
            "content": f"[mock:{provider}] 模拟响应（配置 {cfg['key_env']} 后转发真实上游）"}}], "model": cfg["model"]}
    payload = dict(body); payload["model"] = cfg["model"]
    r = requests.post(f"{cfg['base_url']}/chat/completions", timeout=60,
                      headers={"Authorization": f"Bearer {key}"}, json=payload)
    r.raise_for_status()
    return r.json()

@app.post("/v1/chat/completions")
async def completions(req: ChatRequest, request: Request):
    key = request.headers.get("X-Api-Key", "")
    if key not in CLIENT_KEYS:
        raise HTTPException(401, "无效的 Api Key")
    if not buckets[key].allow():
        return JSONResponse(status_code=429, content={"error": "超出限流(RPM)"})
    primary = req.model.split("-")[0] if req.model.split("-")[0] in PROVIDERS else "deepseek"
    order = [primary] + [p for p in FALLBACK_ORDER if p != primary]
    last_err = None
    for provider in order:
        t0 = time.time()
        try:
            out = call_upstream(provider, req.model_dump())
            log_call(key, req.model, provider, "ok", int((time.time() - t0) * 1000))
            return out
        except Exception as e:  # 降级路由
            last_err = str(e)
            log_call(key, req.model, provider, f"fail:{e[:40]}", int((time.time() - t0) * 1000))
    raise HTTPException(502, f"全部上游不可用: {last_err}")

@app.get("/admin/usage")
def usage(request: Request):
    if request.headers.get("X-Admin-Key") != ADMIN_KEY:
        raise HTTPException(401, "admin key 错误")
    with db() as conn:
        rows = conn.execute("SELECT client, model, provider, status, COUNT(*) c, AVG(latency_ms) lat "
                            "FROM calls GROUP BY client, model, provider, status").fetchall()
    return [{"client": r[0], "model": r[1], "provider": r[2], "status": r[3], "count": r[4], "avg_latency_ms": round(r[5] or 0)} for r in rows]

@app.get("/health")
def health():
    return {"ok": True, "providers": {p: bool(os.environ.get(c["key_env"])) for p, c in PROVIDERS.items()}}
