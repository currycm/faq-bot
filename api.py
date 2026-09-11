"""FastAPI 生产入口

提供 HTTP 接口给前端/小程序/任何客户端使用。
业务逻辑全在 src.agent.FaqBot，本文件只做：
  - 请求/响应 schema 校验（Pydantic）
  - lifespan 启动时预加载 BGE 模型 + 预热一次 ask
  - trace_id 生成与透传
  - 错误处理（503/422/500）

启动：
    uvicorn api:app --host 0.0.0.0 --port 8000 --workers 2
或生产：
    gunicorn api:app -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
"""
from __future__ import annotations

import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

# 让脚本能从任意目录启动（uvicorn api:app 时 cwd 是项目根）
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.agent import FaqBot
from src import config, logger

bot: FaqBot | None = None
ready: bool = False


# ------------------------------------------------------------------ schema
class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200, description="用户问题")
    user_id: str | None = Field(None, max_length=64, description="用户ID（可选）")
    top_k: int | None = Field(None, ge=1, le=10, description="召回候选数")


class AskResponse(BaseModel):
    answer: str
    matched: bool
    tag: str | None = None
    score: float
    fallback: dict | None = None
    candidates: list[dict] = []
    latency_ms: float
    trace_id: str
    vectorizer: str
    # W2 安全层：把脱敏命中 / 注入规则透传给前端（调试 & 前端展示用）
    security: dict | None = None


class SuggestResponse(BaseModel):
    questions: list[str]


class HealthResponse(BaseModel):
    status: str
    ready: bool
    intents: int = 0
    questions: int = 0
    vectorizer: str = ""


# ------------------------------------------------------------------ lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 / 关闭钩子：每个 worker 进程启动时跑一次。"""
    global bot, ready
    print(f"[lifespan] worker {__pid} 启动，加载 FaqBot…")
    t0 = time.perf_counter()
    bot = FaqBot()
    # 预热：跑一次真实查询，触发 BGE 懒加载 + 首次索引访问
    bot.ask("图书馆几点开门")
    ready = True
    elapsed = (time.perf_counter() - t0) * 1000
    s = bot.stats()
    print(f"[lifespan] ready: intents={s['intents']} "
          f"vectorizer={s['vectorizer']} init={elapsed:.0f}ms")
    yield
    # 关闭钩子（目前无需清理，BGE 模型随进程退出）
    print(f"[lifespan] worker {__pid} 关闭")


# ------------------------------------------------------------------ app
__pid = 0  # 占位，lifespan 里赋值
try:
    import os as _os
    __pid = _os.getpid()
except Exception:
    pass

app = FastAPI(
    title="faq-bot",
    version="7.0",
    description="校园 FAQ 问答机器人生产 API",
    lifespan=lifespan,
)

# CORS：开发时允许本地 Streamlit / 前端 HTML 调用。
# 2026-09 修复：删除 "*"（任意站点都能浏览器直调无鉴权接口、烧 LLM
# 预算）。允许源统一由 config.CORS_ORIGINS（env FAQ_CORS_ORIGINS）控制。
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET","POST"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------ exception handler
@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    """兜底异常处理器：所有未捕获异常都返回 500 + trace_id，绝不裸抛。"""
    trace_id = request.headers.get("X-Trace-Id", str(uuid.uuid4()))
    logger.write_jsonl(config.LOG_PATH, {
        "event": "api_500",
        "trace_id": trace_id,
        "path": str(request.url),
        "error": f"{type(exc).__name__}: {exc}",
    })
    return JSONResponse(
        status_code=500,
        content={"detail": "服务暂时不可用，请稍后重试", "trace_id": trace_id},
    )


# ------------------------------------------------------------------ routes
@app.get("/health", response_model=HealthResponse)
def health():
    if not ready or bot is None:
        return HealthResponse(status="starting", ready=False)
    s = bot.stats()
    return HealthResponse(
        status="ok",
        ready=True,
        intents=s["intents"],
        questions=s["questions"],
        vectorizer=s["vectorizer"],
    )


@app.get("/suggest", response_model=SuggestResponse)
def suggest():
    """首次打开聊天界面时展示的 7 个示例问题。"""
    if not ready or bot is None:
        raise HTTPException(503, "bot not ready")
    return SuggestResponse(questions=bot.suggest_questions())


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, request: Request):
    """核心问答接口。

    Headers:
      X-Trace-Id   可选，透传到日志和响应，方便排查
      X-Forwarded-For / X-Real-IP  代理转发的客户端 IP
    """
    if not ready or bot is None:
        raise HTTPException(503, "bot not ready")

    trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())
    # 2026-09 修复：X-Forwarded-For 第一段可被客户端任意伪造，
    # 直接信任 = IP 限流与审计 IP 全部失效。现在只有在明确配置了
    # TRUST_PROXY_HEADERS（API 只暴露在可信 nginx 后面）时才读代理
    # 头；直连部署一律用真实 socket IP。配套 nginx 已改为
    # `X-Forwarded-For $remote_addr`（覆盖而非追加客户端伪造值）。
    if config.TRUST_PROXY_HEADERS:
        client_ip = (
            request.headers.get("X-Real-IP")
            or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or (request.client.host if request.client else None)
        )
    else:
        client_ip = request.client.host if request.client else None

    t0 = time.perf_counter()
    try:
        result = bot.ask(
            query=req.query,
            top_k=req.top_k,
            user_id=req.user_id,
            trace_id=trace_id,
            client_ip=client_ip,
        )
    except Exception as exc:
        logger.write_jsonl(config.LOG_PATH, {
            "event": "ask_exception",
            "trace_id": trace_id,
            "user_id": req.user_id,
            "query": req.query[:200],
            "error": f"{type(exc).__name__}: {exc}",
        })
        raise HTTPException(500, "问答失败，请稍后重试") from exc

    # 把总耗时（含 HTTP 开销）覆盖到 latency_ms
    result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    return AskResponse(
        answer=result["answer"],
        matched=result["matched"],
        tag=result.get("tag"),
        score=result["score"],
        fallback=result.get("fallback"),
        candidates=result.get("candidates", []),
        latency_ms=result["latency_ms"],
        trace_id=trace_id,
        vectorizer=result.get("vectorizer", ""),
        security=result.get("security"),
    )


# ------------------------------------------------------------------ 入口
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=False)
