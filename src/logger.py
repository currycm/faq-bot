# -*- coding: utf-8 -*-
"""L7 日志与反馈层

这是让机器人"越用越聪明"的一层，也是最容易被初学者忽略的一层。

引擎跑得好不好，不看当下准不准，看的是：
    每周导出未命中问题 → 人工归纳成新意图 → 补进语料 → 重新评估

这条运营闭环，比调任何超参数都更能提升实际体验。

日志格式：JSONL（每行一条 JSON），方便直接用 pandas 读：
    import pandas as pd
    df = pd.read_json("logs/qa.log", lines=True)

【v5 安全】所有写入 JSONL 的内容都强制过 redact() 脱敏，
避免 Authorization、api_key 等字段被日志采集系统捞走。
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ======================================================================== 敏感信息脱敏（v5）
# 设计原则：宁可误伤一些普通字符串，也不能让 key 漏出去。
#
# 三类规则：
#   1. 字段名白名单（这些 key 名整体置为 ***，最严格）
#   2. 字符串内"经典密钥"模式（regex 替换）
#   3. 长 token 兜底（>= 32 位连续字母数字也脱敏）

# 字段名直接 redact 整个值（大小写不敏感）
_SENSITIVE_KEYS = {
    "authorization", "api_key", "apikey", "api-key",
    "secret", "secret_key", "secret-key",
    "access_token", "refresh_token", "id_token",
    "password", "passwd", "pwd",
    "cookie", "set-cookie",
    "token",                          # 通用兜底（含 access/refresh 之外的私有 token）
    "deepseek_api_key", "hefeng_api_key",  # 业务专属
}

# 在字符串里匹配"经典密钥形态"的正则
# - sk-xxx（OpenAI / DeepSeek / 通义千问风格）
# - Bearer xxx（HTTP Authorization 头）
# - ?key=xxx 或 &key=xxx 这种 query string 参数（和风天气走 GET，key 在 URL 里）
# - token=xxx 形式（部分厂商用 token 参数）
# - 长 hex / base64 串（>= 32 位）
_KEY_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "sk-***"),
    (re.compile(r"(?i)Bearer\s+[A-Za-z0-9_\-\.]{16,}"), "Bearer ***"),
    (re.compile(r"(?i)([?&](?:key|api_key|apikey|access_token|token|password|pwd)=)[^&\s\"'<>]+"), r"\1***"),
    (re.compile(r"(?i)\b[A-Fa-f0-9]{32,}\b"), "hex***"),  # 32 位以上纯 hex
]

_REDACTED = "***"


def _redact_string(s: str) -> str:
    """扫一遍字符串，把里面的密钥形态全部替换掉。"""
    if not isinstance(s, str):
        return s
    for pattern, replacement in _KEY_PATTERNS:
        s = pattern.sub(replacement, s)
    return s


def _redact_value(value: Any, key_name: str | None = None) -> Any:
    """递归脱敏一个值。

    :param value: 任意 JSON 可序列化的值
    :param key_name: 当前值的字段名（如果是 dict 的某个 key）
    """
    # 规则 1：字段名在白名单 → 整个值清成 ***
    if key_name and key_name.lower() in _SENSITIVE_KEYS:
        return _REDACTED

    # dict：递归处理每一个键值对
    if isinstance(value, dict):
        return {k: _redact_value(v, k) for k, v in value.items()}

    # list / tuple：递归处理每一项
    if isinstance(value, (list, tuple)):
        return [_redact_value(item, None) for item in value]

    # 字符串：扫一遍 regex
    if isinstance(value, str):
        return _redact_string(value)

    # 其它（int / float / bool / None）原样返回
    return value


def redact(record: dict) -> dict:
    """对外暴露的脱敏入口。返回新 dict，不修改原对象。"""
    return _redact_value(record) or {}


# ======================================================================== 写日志
def write_jsonl(path: Path, record: dict) -> None:
    """追加一行 JSON 到文件。任何写失败都不该影响主流程，所以吞掉异常。

    【v5】写入前强制 redact，即便调用方不小心塞了 Authorization 头也不会泄露。
    """
    try:
        safe_record = redact(record)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(safe_record, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[logger] 写日志失败（不影响问答）：{exc}")


def log_query(result: dict) -> None:
    """记录一次问答。result 由 agent.ask() 返回。"""
    if not config.ENABLE_LOGGING:
        return

    record = {
        "timestamp": _now(),
        "query": result.get("query", ""),
        "matched": result.get("matched", False),
        "tag": result.get("tag"),
        "score": round(result.get("score", 0.0), 4),
        "latency_ms": result.get("latency_ms", 0),
        "vectorizer": result.get("vectorizer", ""),
    }
    write_jsonl(config.LOG_PATH, record)

    # 未命中问题单独存一份，方便每周导出分析
    if not record["matched"]:
        write_jsonl(config.UNMATCHED_PATH, {
            **record,
            "top_guess": result.get("top_guess"),   # 最接近的意图，可能是"差一点就命中"
        })

    if config.LOG_TO_CONSOLE:
        print(f"[log] {record}")


def log_feedback(result: dict, vote: str, comment: str = "") -> None:
    """记录用户对某条回答的反馈（v6 运营闭环）。

    前端点了"有用/没用"后调用。写入独立的 feedback.jsonl，
    与问答日志分开，方便单独统计好评率。

    :param result: agent.ask() 的返回结构
    :param vote:   "up" 表示有用，"down" 表示没用
    :param comment: 用户补充文字（可选）
    """
    if not getattr(config, "FEEDBACK_ENABLED", True):
        return

    fb = result.get("fallback") or {}
    write_jsonl(config.FEEDBACK_PATH, {
        "timestamp": _now(),
        "query": result.get("query", ""),
        "matched": result.get("matched", False),
        "tag": result.get("tag"),
        "score": round(result.get("score", 0.0), 4),
        # 兜底来源：区分"知识库答得不好"还是"LLM 答得不好"
        "fallback_type": fb.get("type"),
        "fallback_source": fb.get("source"),
        "answer": result.get("answer", ""),
        "vote": vote,
        "comment": comment,
    })


def summarize_feedback() -> dict:
    """统计反馈数据，给运营看。

    返回：
        {
          "total": 总反馈数,
          "up": 好评数, "down": 差评数,
          "up_rate": 好评率(0~1),
          "top_bad": [{"query","count","tag"}, ...]   差评最多的问题
        }
    """
    path = config.FEEDBACK_PATH
    if not path.exists():
        return {"total": 0, "up": 0, "down": 0, "up_rate": 0.0, "top_bad": []}

    up = down = 0
    bad: dict[str, dict] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if rec.get("vote") == "up":
                    up += 1
                elif rec.get("vote") == "down":
                    down += 1
                    q = (rec.get("query") or "").strip()
                    if q:
                        item = bad.setdefault(
                            q, {"query": q, "count": 0, "tag": rec.get("tag")}
                        )
                        item["count"] += 1
    except OSError:
        return {"total": 0, "up": 0, "down": 0, "up_rate": 0.0, "top_bad": []}

    total = up + down
    return {
        "total": total,
        "up": up,
        "down": down,
        "up_rate": round(up / total, 4) if total else 0.0,
        "top_bad": sorted(bad.values(), key=lambda x: -x["count"])[:10],
    }


def log_reload(corpus_path, n_intents: int, n_questions: int) -> None:
    """记录语料热更新事件。"""
    if not config.ENABLE_LOGGING:
        return
    write_jsonl(config.LOG_PATH, {
        "timestamp": _now(),
        "event": "corpus_reload",
        "corpus": str(corpus_path),
        "intents": n_intents,
        "questions": n_questions,
    })


def summarize_unmatched(limit: int = 20) -> list[dict]:
    """读取未命中日志，按出现次数排序，用于每周语料迭代。"""
    if not config.UNMATCHED_PATH.exists():
        return []

    counter: dict[str, dict] = {}
    with open(config.UNMATCHED_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            q = rec.get("query", "").strip()
            if not q:
                continue
            if q not in counter:
                counter[q] = {"query": q, "count": 0, "top_guess": rec.get("top_guess"),
                              "last_score": rec.get("score")}
            counter[q]["count"] += 1

    return sorted(counter.values(), key=lambda x: -x["count"])[:limit]


def _unused(*_args):
    """占位，避免 time 未使用的告警。"""
    return time.time()
