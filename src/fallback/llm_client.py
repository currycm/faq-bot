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
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from .. import config, logger


@dataclass
class LLMResult:
    answer: str
    raw: dict


def _get_api_key() -> str:
    return config.DEEPSEEK_API_KEY or os.environ.get("DEEPSEEK_API_KEY", "")


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
        logger.write_jsonl(config.LOG_PATH, {
            "event": "llm_api_error",
            "model": config.DEEPSEEK_MODEL,
            "error": str(exc),
        })
        return None

    latency_ms = round((__import__("time").perf_counter() - t0) * 1000, 1)
    try:
        content = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        logger.write_jsonl(config.LOG_PATH, {
            "event": "llm_response_invalid",
            "raw": str(data)[:300],
        })
        return None

    logger.write_jsonl(config.LOG_PATH, {
        "event": "llm_call_ok",
        "model": config.DEEPSEEK_MODEL,
        "latency_ms": latency_ms,
        "usage": data.get("usage"),
    })

    return LLMResult(answer=content, raw=data)


def format_answer(question: str) -> str:
    """对外统一接口：失败时返回固定兜底话术，绝不裸抛异常。"""
    try:
        result = call_llm(question)
    except Exception as exc:
        logger.write_jsonl(config.LOG_PATH,
                           {"event": "llm_exception", "error": str(exc)})
        return config.FALLBACK_TEXT

    if result is None:
        return ("现在没法联系到 AI 助手，可能是网络问题或 API key 没配置。\n"
                "换个问法，或者把问题反馈给管理员。")

    # 给 LLM 兜底的回答加个标签，让用户知道这不是从知识库来的
    return f"{result.answer}\n\n（此回答由 DeepSeek 生成，仅供参考）"