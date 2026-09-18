# -*- coding: utf-8 -*-
"""DeepSeek API 客户端（兼容 OpenAI 协议）

为什么用兼容接口：DeepSeek 提供 OpenAI 兼容协议，用标准库 urllib 就能调，
零额外依赖。如果以后要换别的兼容厂商（豆包、Moonshot）也几乎不改代码。

环境：
    export DEEPSEEK_API_KEY=sk-xxx          # 推荐
或在 config.DEEPSEEK_API_KEY 里硬编码（不推荐提交到仓库）。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from .. import config, logger


@dataclass
class LLMResult:
    answer: str
    raw: dict


@dataclass
class LLMAnswer:
    """对外结构化结果（2026-09 新增）。

    Attributes:
        text:     给用户看的最终文本（成功时含"DeepSeek 生成"标签）
        ok:       是否真的拿到了 LLM 回复（替代靠子串嗅探判断）
        cost_cny: 本次调用的真实成本（按 usage × 单价折算，元）
    """

    text: str
    ok: bool
    cost_cny: float = 0.0


def _get_api_key() -> str:
    """密钥统一走 config（config 内部已用 _load_secret 读过环境变量）。

    2026-09 清理：此前这里又兜了一层 os.environ.get —— 违反 config.py 里写明的
    "所有 API Key 统一通过 _load_secret() 读取，不允许在任何模块里直接读环境变量"
    约定，也让"密钥到底从哪来"变得难追。
    """
    return config.DEEPSEEK_API_KEY


def call_llm(question: str, system: Optional[str] = None) -> Optional[LLMResult]:
    """调用 DeepSeek chat 接口。

    任何网络/解析错误返回 None —— 调用方负责降级。
    """
    if not config.DEEPSEEK_ENABLED:
        return None
    api_key = _get_api_key()
    if not api_key:
        return None

    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system or config.DEEPSEEK_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        "temperature": config.DEEPSEEK_TEMPERATURE,
        "max_tokens": config.DEEPSEEK_MAX_TOKENS,
    }

    req = urllib.request.Request(
        f"{config.DEEPSEEK_BASE_URL}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    t0 = __import__("time").perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=config.DEEPSEEK_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.write_jsonl(
            config.LOG_PATH,
            {
                "event": "llm_api_error",
                "model": config.DEEPSEEK_MODEL,
                "error": str(exc),
            },
        )
        return None

    latency_ms = round((__import__("time").perf_counter() - t0) * 1000, 1)
    # 2026-09 修复：content 为 null（被内容过滤器拦截 / reasoning 模型）时
    # 旧代码抛 AttributeError，既不在捕获列表内，invalid 事件也永远不记录。
    try:
        content = ((data.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        logger.write_jsonl(
            config.LOG_PATH,
            {
                "event": "llm_response_invalid",
                "raw": str(data)[:300],
            },
        )
        return None

    if not content:
        logger.write_jsonl(
            config.LOG_PATH,
            {
                "event": "llm_response_invalid",
                "raw": str(data)[:300],
            },
        )
        return None

    logger.write_jsonl(
        config.LOG_PATH,
        {
            "event": "llm_call_ok",
            "model": config.DEEPSEEK_MODEL,
            "latency_ms": latency_ms,
            "usage": data.get("usage"),
        },
    )

    return LLMResult(answer=content, raw=data)


def _usage_cost_cny(usage: Optional[dict]) -> float:
    """按 usage token 数 × 单价折算真实成本（元）。

    拿不到 usage（老接口/异常响应）时退回 avg 估算，保证熔断器
    仍能按 config.BUDGET_AVG_COST_CNY 近似累计。
    """
    if not usage:
        from ..security.budget import get_budget

        return get_budget().avg_cost_per_call
    try:
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
    except (TypeError, ValueError):
        from ..security.budget import get_budget

        return get_budget().avg_cost_per_call
    in_cost = prompt_tokens * config.DEEPSEEK_INPUT_PRICE_PER_MTOK / 1_000_000
    out_cost = completion_tokens * config.DEEPSEEK_OUTPUT_PRICE_PER_MTOK / 1_000_000
    return round(in_cost + out_cost, 8)


def answer_with_cost(question: str) -> LLMAnswer:
    """路由器专用接口：返回结构化结果（文本 + 是否成功 + 真实成本）。

    2026-09 修复：调用方此前靠"DeepSeek 生成"子串嗅探判断是否
    真的拿到 LLM 回复——标签文案一改，预算计数和 source 判定就全
    失真。现在用结构化的 ok 字段，并把 usage 折算的真实成本交给
    上层记入预算（成本熔断从"死指标"变成真正独立的一维）。
    """
    try:
        result = call_llm(question)
    except Exception as exc:
        logger.write_jsonl(config.LOG_PATH, {"event": "llm_exception", "error": str(exc)})
        return LLMAnswer(text=config.FALLBACK_TEXT, ok=False)

    if result is None:
        # 不告诉用户"为什么答不上"。"可能是网络问题或 API key 没配置"
        # 是给运维看的信息，学生看到只会困惑，还会怀疑服务是不是坏了。
        # 统一走 config 里的中性兜底话术。
        return LLMAnswer(text=config.FALLBACK_TEXT, ok=False)

    # 正文里不再附"（此回答由 DeepSeek 生成，仅供参考）"：
    # 品牌名属于技术细节，而前端已有一行来源说明「AI 生成 · 非官方答复」，
    # 两处讲的是同一件事，正文再贴一句既啰嗦又把大模型暴露得太直白。
    return LLMAnswer(
        text=result.answer,
        ok=True,
        cost_cny=_usage_cost_cny(result.raw.get("usage")),
    )


def format_answer(question: str) -> str:
    """对外统一接口（兼容旧调用方）：只返回文本。失败时返回固定兜底话术，绝不裸抛异常。"""
    return answer_with_cost(question).text
