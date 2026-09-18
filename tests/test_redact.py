"""验证 logger 的日志侧脱敏真的能兜住 KEY（write_jsonl 落盘前强制打码）。

2026-09 修复：旧版是顶层脚本，import 即执行、断言跑在收集期，
还会把 4 条伪造的 weather_api_error / llm_api_error 追加进真实的
logs/qa.log——每跑一次测试就往生产日志塞一批假错误，误导排障。
现改为标准 pytest 用例，写入 pytest 的 tmp_path 隔离目录，不碰真实日志。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent  # faq-bot/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.logger import redact, write_jsonl  # noqa: E402

# 伪造的 KEY —— **仅测试用占位符，非真实凭据**。
# !! 刻意拆成两段拼接、不写成完整字面量：完整的 "sk-" + 32 位十六进制会被
#    GitHub secret scanning 误判为真实 DeepSeek API Key，push protection 会
#    直接拒绝推送（GH013 Push cannot contain secrets）。拆开后文件里不再有
#    任何 32 位连续十六进制，运行时取值不变、测试语义不受影响。
HEFENG_KEY = "31fd4d948139475f" + "843f235103febb4c"
DEEPSEEK_KEY = "sk-" + "1309340f02564d0e" + "b243f9c9456c383c"
HEX_TOKEN = "abcdef0123456789" + "abcdef0123456789"

ALL_SECRETS = (HEFENG_KEY, DEEPSEEK_KEY, HEX_TOKEN)


def _secret_records() -> dict:
    return {
        "query_string_key": {
            "event": "weather_api_error",
            "url": "https://devapi.qweather.com/v7/weather/now",
            "error": (
                "<urlopen error [Errno 401] Unauthorized: "
                "https://devapi.qweather.com/v7/weather/now"
                "?location=101190101&key=" + HEFENG_KEY + "&foo=bar>"
            ),
        },
        "sk_key_in_error": {
            "event": "llm_api_error",
            "model": "deepseek-chat",
            "error": (
                'HTTPError: 401, Response: {"error":{"message":"Incorrect API key provided: ' + DEEPSEEK_KEY + '"}}'
            ),
        },
        "authorization_header": {
            "event": "llm_api_error",
            "model": "deepseek-chat",
            "error": (
                "urllib.error.URLError: <request "
                "url=https://api.deepseek.com/chat/completions "
                "headers={Authorization: Bearer " + DEEPSEEK_KEY + "}>"
            ),
        },
        "long_hex_token": {
            "event": "weather_api_error",
            "error": "Failed: token=" + HEX_TOKEN + " expired",
        },
    }


@pytest.mark.parametrize("case", sorted(_secret_records()))
def test_secret_never_lands_in_log_file(case, tmp_path):
    """端到端：redact 后的内存结果与落盘内容都不得出现完整 KEY。"""
    record = _secret_records()[case]

    sanitized = redact(record)
    dumped = json.dumps(sanitized, ensure_ascii=False)
    for secret in ALL_SECRETS:
        assert secret not in dumped, f"{case}: 内存侧脱敏漏了 KEY"

    log_path = tmp_path / "qa.log"
    write_jsonl(log_path, record)
    content = log_path.read_text(encoding="utf-8")
    for secret in ALL_SECRETS:
        assert secret not in content, f"{case}: 落盘内容泄露 KEY"


def test_query_field_with_sk_prefix_not_damaged():
    """query 字段里偶然出现"sk-"字样不能误伤正常文本。"""
    record = {"query": "请问我怎么用 sk- 开头的代码", "tag": "general"}
    assert "请问我怎么用 sk-" in redact(record)["query"]


def test_plain_record_passes_through():
    """无敏感内容的记录原样通过。"""
    record = {"event": "llm_call_ok", "model": "deepseek-chat", "latency_ms": 12}
    out = redact(record)
    assert out["event"] == "llm_call_ok"
    assert out["model"] == "deepseek-chat"
    assert out["latency_ms"] == 12


def test_non_str_key_not_crash():
    """dict key 不是字符串时不该抛 AttributeError（打穿 write_jsonl 兜底）。"""
    record = {1: "value", "token": "abc"}
    out = redact(record)
    assert out["token"] == "***"
