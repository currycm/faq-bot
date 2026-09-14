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

import os
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

from src.agent import FaqBot, answer_cache_stats
from src import config, logger

__pid = os.getpid()

bot: FaqBot | None = None
ready: bool = False


def _load_bot() -> FaqBot:
    """构建并预热 FaqBot（**在模块导入时调用**，见文件末尾）。

    ⚠️ 为什么不在 lifespan 里建：gunicorn `--preload` 会让 master 进程先
    import 本模块、再 fork worker —— 子进程通过写时复制（COW）共享这份模型
    内存。若把构建放进 lifespan（每个 worker 各跑一次），每个 worker 仍会
    各建一份，preload 就白加了。单进程（uvicorn 直起）时行为等价。
    """
    global bot, ready
    print(f"[bot] 进程 {__pid} 加载 FaqBot…")
    t0 = time.perf_counter()
    b = FaqBot()
    b.ask("图书馆几点开门")        # 预热：触发 BGE 懒加载 + 首次索引访问
    s = b.stats()
    bot = b
    ready = True
    print(f"[bot] ready: intents={s['intents']} vectorizer={s['vectorizer']} "
          f"init={(time.perf_counter() - t0) * 1000:.0f}ms")
    return b


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
    # 是否命中答案缓存（便于观察缓存效果；缓存查找在安全层之后，不会绕过限流）
    cache_hit: bool = False


class SuggestResponse(BaseModel):
    questions: list[str]


class HealthResponse(BaseModel):
    status: str
    ready: bool
    intents: int = 0
    questions: int = 0
    vectorizer: str = ""
    cache: dict | None = None


# ------------------------------------------------------------------ lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 / 关闭钩子：每个 worker 进程启动时跑一次。

    模型构建与预热已移到**模块导入时**（见下方 `_load_bot` 与文件末尾的调用），
    这里只留日志与关闭钩子 —— lifespan 保持轻量，gunicorn `--preload` 的
    COW 共享才能真正生效。
    """
    print(f"[lifespan] worker {__pid} 启动（模型已随 preload 共享）")
    yield
    # 关闭钩子（目前无需清理，BGE 模型随进程退出）
    print(f"[lifespan] worker {__pid} 关闭")


# ------------------------------------------------------------------ app

app = FastAPI(
    title="faq-bot",
    version="8.0",
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
        cache=answer_cache_stats(),
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
        cache_hit=bool(result.get("cache_hit", False)),
    )


# ------------------------------------------------------------------ 入口
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=False)


# ---------------------------------------------------------------- 启动时加载
# !! 必须在**模块级**执行（导入即加载），不要挪进 lifespan：
#    gunicorn --preload 在 master 里 import 完本模块后才 fork worker，
#    子进程靠 COW 共享同一份模型内存；挪进 lifespan 就退化成"每 worker 一份"。
#    放在文件末尾，让 app / 路由先定义好，加载失败的堆栈更干净。
bot = _load_bot()
