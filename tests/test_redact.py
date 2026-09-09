"""端到端验证 redact 真的能从日志文件兜住 KEY"""
import json
import re
import sys
from pathlib import Path

# 让脚本能 import src
ROOT = Path(__file__).resolve().parent.parent  # faq-bot/
sys.path.insert(0, str(ROOT))

from src.logger import write_jsonl, redact  # noqa: E402
from src import config  # noqa: E402

# 模拟 1：query string 里带 key 的 URL 异常
test1 = {
    "event": "weather_api_error",
    "url": "https://devapi.qweather.com/v7/weather/now",
    "error": ("<urlopen error [Errno 401] Unauthorized: "
              "https://devapi.qweather.com/v7/weather/now"
              "?location=101190101&key=31fd4d948139475f843f235103febb4c&foo=bar>"),
}
print("Test 1: query string with key")
print("  ", json.dumps(redact(test1), ensure_ascii=False))

# 模拟 2：异常体里含 sk-xxx
test2 = {
    "event": "llm_api_error",
    "model": "deepseek-chat",
    "error": ('HTTPError: 401, Response: {"error":{"message":"Incorrect API key provided: '
              'sk-1309340f02564d0eb243f9c9456c383c"}}'),
}
print("\nTest 2: error msg contains sk- key")
print("  ", json.dumps(redact(test2), ensure_ascii=False))

# 模拟 3：完整请求 dump 含 Authorization 头
test3 = {
    "event": "llm_api_error",
    "model": "deepseek-chat",
    "error": ("urllib.error.URLError: <request url=https://api.deepseek.com/chat/completions "
              "headers={Authorization: Bearer sk-1309340f02564d0eb243f9c9456c383c}>"),
}
print("\nTest 3: full request dump")
print("  ", json.dumps(redact(test3), ensure_ascii=False))

# 模拟 4：长 hex token
test4 = {
    "event": "weather_api_error",
    "error": "Failed: token=abcdef0123456789abcdef0123456789 expired",
}
print("\nTest 4: long hex token in error")
print("  ", json.dumps(redact(test4), ensure_ascii=False))

# 模拟 5：query 字段里偶然含 sk- 不能误伤
test5 = {
    "query": "请问我怎么用 sk- 开头的代码",
    "tag": "general",
}
print("\nTest 5: query field with sk- text (must not be damaged)")
print("  ", json.dumps(redact(test5), ensure_ascii=False))
assert "请问我怎么用 sk-" in redact(test5)["query"], "误伤了普通 query!"

# 实际走 write_jsonl 写到日志
log_path = config.LOG_PATH
write_jsonl(log_path, test1)
write_jsonl(log_path, test2)
write_jsonl(log_path, test3)
write_jsonl(log_path, test4)

# 读所有内容验证 KEY 没漏
with open(log_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# 取刚写入的 4 行
recent = lines[-4:]
print("\n--- 最近 4 行日志（实际写到文件的内容） ---")
for line in recent:
    print(" ", line.rstrip())

# 检查全文是否还有完整的 KEY 模式
content = "".join(recent)
assert "31fd4d948139475f843f235103febb4c" not in content, "和风天气 KEY 泄露！"
assert "sk-1309340f02564d0eb243f9c9456c383c" not in content, "DeepSeek KEY 泄露！"
assert "abcdef0123456789abcdef0123456789" not in content, "hex token 泄露！"
print("\n[OK] 4 个测试场景全部安全，真实 KEY 一律未泄露到日志文件。")
