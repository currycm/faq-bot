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
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

# 「目录已就绪」进程内缓存（详见 _ensure_parent 的说明）
_dirs_ensured: set[str] = set()
_dirs_lock = threading.Lock()

# 日志轮转参数（#19：避免长期运行撑爆磁盘 / 无限增长）
_LOG_MAX_BYTES = 100 * 1024 * 1024  # 单文件上限 100MB
_LOG_BACKUP_COUNT = 5  # 保留 5 份历史
_log_write_lock = threading.Lock()  # 保护「轮转 + 追加」的原子性（多 worker/线程并发）


def _now() -> str:
    """带时区的 ISO 时间戳，避免 HF Spaces(UTC) 与本地(Asia/Shanghai) 差 8 小时导致日志混乱。

    优先用 Asia/Shanghai（对国内运维友好）；缺少 IANA 时区数据（部分 Windows 未装 tzdata）
    时回退到 UTC（仍带 +00:00 后缀，绝不留裸本地时间）。
    """
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Asia/Shanghai")
    except Exception:
        tz = timezone.utc
    return datetime.now(tz).isoformat(timespec="seconds")


# ======================================================================== 敏感信息脱敏（v5）
# 设计原则：宁可误伤一些普通字符串，也不能让 key 漏出去。
#
# 三类规则：
#   1. 字段名白名单（这些 key 名整体置为 ***，最严格）
#   2. 字符串内"经典密钥"模式（regex 替换）
#   3. 长 token 兜底（>= 32 位连续字母数字也脱敏）

# 字段名直接 redact 整个值（大小写不敏感）
_SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "api-key",
    "secret",
    "secret_key",
    "secret-key",
    "access_token",
    "refresh_token",
    "id_token",
    "password",
    "passwd",
    "pwd",
    "cookie",
    "set-cookie",
    "token",  # 通用兜底（含 access/refresh 之外的私有 token）
    "deepseek_api_key",
    "hefeng_api_key",  # 业务专属
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
    """扫一遍字符串，把里面的密钥形态全部替换掉。

    2026-09 修复：追加 PII 脱敏（手机号/身份证/邮箱等）。
    此前只有密钥形态被脱敏，用户输入的手机号会原样写进 qa.log，
    与"我们不能存"的设计目标矛盾。redact 模块自带全兜底、绝不抛。
    """
    if not isinstance(s, str):
        return s
    for pattern, replacement in _KEY_PATTERNS:
        s = pattern.sub(replacement, s)
    try:
        from .security.redact import redact as _redact_pii

        s = _redact_pii(s).sanitized
    except Exception:
        pass
    return s


def _redact_value(value: Any, key_name: str | None = None) -> Any:
    """递归脱敏一个值。

    :param value: 任意 JSON 可序列化的值
    :param key_name: 当前值的字段名（如果是 dict 的某个 key）
    """
    # 规则 1：字段名在白名单 → 整个值清成 ***
    # str() 兜底：dict key 可能不是字符串（json.dumps 会把 int key 转成
    # 字符串落盘），直接调 .lower() 会抛 AttributeError——它不在
    # write_jsonl 捕获的异常列表里，会打穿"写日志失败不影响主流程"。
    if key_name and str(key_name).lower() in _SENSITIVE_KEYS:
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
def _ensure_parent(path: Path) -> None:
    """确保日志文件的父目录存在 —— **只在首次**真正执行 mkdir。

    动机（实测）：`path.parent.mkdir(parents=True, exist_ok=True)` 是一次真实
    系统调用，在本机中位数 **0.366 ms/次**。它原本在每一条日志写入前都跑一次，
    而进程启动后目录必然已经存在，这步纯属浪费：

        write_jsonl 整趟 0.893 ms = mkdir 0.366（41%）+ open/write/close 0.456
                                  + redact 0.020 + json.dumps 0.003

    对 LLM 无关的检索请求，这条 mkdir 约占端到端延迟的 3%；
    而**缓存命中**的请求总耗时只有 ~0.9ms，它一个人就占掉 40%。

    所以改成进程内缓存"已确认存在"的目录 —— 语义完全不变（目录不存在照样会建），
    只是不再重复打 syscall。
    """
    key = str(path.parent)
    if key in _dirs_ensured:  # 热路径：一次集合查找，无 syscall
        return
    with _dirs_lock:  # 并发下只让一个线程去 mkdir
        # 双检：拿到锁之后再确认一次，避免重复 mkdir（幂等但不必要）
        if key in _dirs_ensured:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        _dirs_ensured.add(key)


def clear_dir_cache() -> None:
    """清空"目录已就绪"缓存。

    正常无需调用。目录有可能在**进程运行期间**被删掉（运维清理 / 挂载点重挂 /
    容器重建卷），此时缓存是脏的 —— `write_jsonl` 里 OSError 重试分支会自动调它，
    测试也可以手动调来模拟这种情况。
    """
    with _dirs_lock:
        _dirs_ensured.clear()


def _maybe_rotate(path: Path, max_bytes: int = _LOG_MAX_BYTES, backup_count: int = _LOG_BACKUP_COUNT) -> None:
    """写前轮转：超过 max_bytes 时 qa.log → qa.log.1 → qa.log.2 …（最多 backup_count 份）。

    只做轻量 rename，不改动既有 redact / 重试逻辑；任何异常都吞掉，绝不影响主流程。
    """
    try:
        if not path.exists() or path.stat().st_size < max_bytes:
            return
        for i in range(backup_count - 1, 0, -1):
            prev = Path(f"{path}.{i}")
            nxt = Path(f"{path}.{i + 1}")
            if prev.exists():
                prev.replace(nxt)
        path.replace(Path(f"{path}.1"))
    except OSError:
        pass


def write_jsonl(path: Path, record: dict) -> None:
    """追加一行 JSON 到文件。任何写失败都不该影响主流程，所以吞掉异常。

    【v5】写入前强制 redact，即便调用方不小心塞了 Authorization 头也不会泄露。
    2026-09 修复：json.dumps 对不可序列化对象（numpy 标量 / Path / 集合）
    抛 TypeError，此前只捕获 OSError 会直接穿透——最坏情况是 500 处理器
    里调它，让异常处理器自身再抛。现在 TypeError/ValueError 一并兜住，
    序列化用 default=str 兜底。
    """
    try:
        safe_record = redact(record)
        line = json.dumps(safe_record, ensure_ascii=False, default=str) + "\n"
    except (TypeError, ValueError) as exc:
        print(f"[logger] 写日志失败（不影响问答）：{exc}", file=sys.stderr)
        return

    try:
        _ensure_parent(path)
        with _log_write_lock:
            _maybe_rotate(path)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
    except OSError as exc:
        # 目录可能在进程运行期间被删掉 → "已就绪"缓存变脏。
        # 清掉缓存、重建目录后重试一次；仍然失败才按原逻辑降级打印。
        #
        # !! 只对「目录/路径不存在」这类错误重试，不对所有 OSError 重试。
        #    磁盘满 / 权限不足时第一次 open 可能已经把部分数据刷出去了，
        #    盲目重试会产生**重复行**——宁可丢一条日志，也不要重复一条。
        if isinstance(exc, (FileNotFoundError, NotADirectoryError)):
            try:
                clear_dir_cache()
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)
                return
            except OSError:
                pass
        print(f"[logger] 写日志失败（不影响问答）：{exc}", file=sys.stderr)


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
        write_jsonl(
            config.UNMATCHED_PATH,
            {
                **record,
                "top_guess": result.get("top_guess"),  # 最接近的意图，可能是"差一点就命中"
            },
        )

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
    write_jsonl(
        config.FEEDBACK_PATH,
        {
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
        },
    )


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
                        item = bad.setdefault(q, {"query": q, "count": 0, "tag": rec.get("tag")})
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
    write_jsonl(
        config.LOG_PATH,
        {
            "timestamp": _now(),
            "event": "corpus_reload",
            "corpus": str(corpus_path),
            "intents": n_intents,
            "questions": n_questions,
        },
    )
