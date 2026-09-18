# -*- coding: utf-8 -*-
"""兜底路由器测试

目的：
    1. 验证路由器分类正确（chat / realtime / campus / general）
    2. 验证降级路径：没有 API key 时也能给出合理答案（不抛异常）
    3. 验证安全栏：校园事务绝不进 LLM

注意：本测试不依赖真实 API key。
    - DEEPSEEK_ENABLED=True 但 API_KEY 为空 → 降级到 fixed_general_fallback
    - HEFENG_ENABLED=True 但 API_KEY 为空 → 降级到 fixed 兜底
    - 你可以临时把 KEY 写到环境变量，再单独跑真实联调
"""
from __future__ import annotations

import sys
from pathlib import Path

# 让脚本可以直接 python tests/test_fallback.py 运行
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Windows 控制台默认 GBK，强制 UTF-8（参考 src.agent.setup_stdio）
for _stream in (sys.stdout, sys.stderr):
    try:
        if (getattr(_stream, "encoding", "") or "").lower().replace("-", "") != "utf8":
            _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# ASCII fallback for GBK consoles
_OK = "[OK] "
_FAIL = "[FAIL] "

from src import config                                  # noqa: E402
from src.fallback import dispatch, QueryType            # noqa: E402


# ---------------------------------------------------------------- 路由分类
CLASSIFY_CASES = [
    # (query, 期望类型, 说明)
    ("你好",                       QueryType.CHAT,      "打招呼"),
    ("谢谢",                       QueryType.CHAT,      "感谢"),
    ("你是谁",                     QueryType.CHAT,      "问身份"),

    ("今天南京天气怎么样",         QueryType.REALTIME,  "天气 - 主关键词"),
    ("明天会下雨吗",               QueryType.REALTIME,  "天气 - 动词型"),
    ("今天几度",                   QueryType.REALTIME,  "天气 - 温度"),
    ("什么时候开学",               QueryType.REALTIME,  "校历 - 关键词在 REALTIME 中"),

    ("大四还能转专业吗",           QueryType.CAMPUS,    "校园事务 - 转专业"),
    ("校园卡丢了",                 QueryType.CAMPUS,    "校园事务 - 校园卡"),
    ("奖学金怎么申请",             QueryType.CAMPUS,    "校园事务 - 奖学金"),
    ("宿舍晚上几点熄灯",           QueryType.CAMPUS,    "校园事务 - 宿舍"),
    ("借书超期罚款",               QueryType.CAMPUS,    "校园事务 - 图书馆"),

    ("什么是机器学习",             QueryType.GENERAL,   "通识 - 概念"),
    ("怎么学好高数",               QueryType.GENERAL,   "通识 - 方法"),
    ("python 怎么读文件",          QueryType.GENERAL,   "通识 - 技术"),

    # ---- 回归用例（2026-09 修复）：英文关键词词边界 / 单字校园词 / 闲聊优先级 ----
    ("this is a question",        QueryType.GENERAL,   "hi 不得命中 this"),
    ("which 图书馆几点开门",       QueryType.CAMPUS,    "hi 不得命中 which"),
    ("history of china",          QueryType.GENERAL,   "hi 不得命中 history"),
    ("关系数据库是什么",           QueryType.GENERAL,   "单字'系'不得命中校务"),
    ("系统论是什么",               QueryType.GENERAL,   "单字'系'不得命中校务"),
    ("专业英语怎么学",             QueryType.GENERAL,   "'专业'不得误伤专业英语"),
    ("你好，请问怎么选课",         QueryType.CAMPUS,    "校务优先于闲聊"),
    ("谢谢，宿舍几点熄灯",         QueryType.CAMPUS,    "校务优先于闲聊"),
]


def test_classify():
    """路由器分类必须正确。

    【修复】此前用 return False 表示失败，pytest 下返回值被忽略，
    检测失效（永远绿）。现在改为 assert，失败会真实报错。
    """
    print("=" * 60)
    print("测试 1：路由器分类")
    print("=" * 60)

    failed = []
    for q, expected, note in CLASSIFY_CASES:
        d = dispatch(q)
        ok = d.query_type is expected
        flag = "✓" if ok else "✗"
        print(f"  {flag} [{d.query_type.value:12s}] {q!r:30s} ({note})")
        if not ok:
            failed.append((q, expected, d.query_type))

    assert not failed, (
        f"❌ {len(failed)} 个分类失败："
        + "; ".join(f"{q!r} 期望={exp.value} 实际={got.value}"
                    for q, exp, got in failed)
    )
    print(f"\n✅ 全部 {len(CLASSIFY_CASES)} 条分类通过\n")


# ---------------------------------------------------------------- 答案生成（含降级）
ANSWER_CASES = [
    # (query, 必须出现的子串, 必须不出现的子串, 说明)
    ("你好呀",
     ["南京工业职业技术大学"],
     [],
     "闲聊应给固定话术"),

    ("今天天气如何",
     [],
     ["幻觉", "随机"],                # 没 key 时会显示"暂时拿不到"
     "实时问题：天气降级路径"),

    ("大四还能转专业吗",
     ["相关部门", "知识库"],
     ["DeepSeek"],
     "校园事务绝不能进 LLM"),

    ("什么是机器学习",
     [],
     # 兜底话术只许说"我答不上"，不许解释原因 ——
     # "API key 没配""网络问题""预算用完""让管理员补语料"都是运维信息，
     # 说给用户听只会让人以为整个服务坏了。
     ["API key", "key 没配置", "网络问题", "预算额度", "管理员", "未配置"],
     "通识问题：LLM 降级也不透技术细节"),
]


def test_answers_safety():
    """答案生成：检查关键安全栏。"""
    print("=" * 60)
    print("测试 2：安全栏 & 降级路径")
    print("=" * 60)

    failed = []
    for q, must_have, must_not, note in ANSWER_CASES:
        d = dispatch(q)
        ans = d.answer
        ok = all(s in ans for s in must_have) and all(s not in ans for s in must_not)
        flag = "✓" if ok else "✗"
        snippet = ans.replace("\n", " ")[:50]
        print(f"  {flag} [{d.source:25s}] {q!r:25s} → {snippet}...")
        if not ok:
            failed.append((q, d, must_have, must_not))
            print(f"     答案: {ans!r}")
            print(f"     期望含: {must_have}  期望不含: {must_not}")

    if failed:
        print(f"\n❌ {len(failed)} 条答案检查失败")
        for q, d, must_have, must_not in failed:
            print(f"   {q!r}  期望含: {must_have}  期望不含: {must_not}")
        assert False, f"{len(failed)} 条答案检查失败"
    print(f"\n✅ 全部 {len(ANSWER_CASES)} 条安全栏检查通过\n")


# ---------------------------------------------------------------- 空输入
def test_empty():
    """空输入应该优雅返回。"""
    print("=" * 60)
    print("测试 3：边界输入")
    print("=" * 60)

    for q in ["", "   ", None]:
        d = dispatch(q) if q is not None else dispatch("")
        ok = "请输入" in d.answer or d.query_type is QueryType.UNKNOWN
        flag = "✓" if ok else "✗"
        print(f"  {flag} 输入={q!r:10s} → type={d.query_type.value}, "
              f"answer={d.answer!r}")
        assert ok, f"空输入处理异常：{q!r} → {d!r}"

    print("\n✅ 空输入处理正常\n")


# ---------------------------------------------------------------- 端到端
def test_end_to_end():
    """走完整 FaqBot.ask()，验证 fallback 字段被正确填入。"""
    print("=" * 60)
    print("测试 4：端到端（FaqBot.ask 未命中时）")
    print("=" * 60)

    from src.agent import FaqBot
    bot = FaqBot()

    # 1. 命中 FAQ
    r1 = bot.ask("图书馆几点开门")
    print(f"  [命中] tag={r1['tag']!r} score={r1['score']:.3f} "
          f"fallback={r1['fallback']}")
    assert r1["matched"], "FAQ 应命中"

    # 2. 天气 → 路由到 weather
    r2 = bot.ask("今天天气怎么样")
    print(f"  [天气] matched={r2['matched']} fallback={r2['fallback']}")
    assert not r2["matched"], "天气不在 FAQ，应未命中"
    assert r2["fallback"] is not None, "未命中应填入 fallback"
    assert r2["fallback"]["type"] == "realtime", f"天气应路由到 realtime: {r2['fallback']}"

    # 3. 校园事务 → 固定话术
    #    BGE 语义匹配很强，"食堂几点关门"会被识别成 dorm_curfew。
    #    这里测试两种合法结果：
    #      a) matched=True（FAQ 命中）→ fallback=None 是正确的
    #      b) matched=False → 必须走 fixed_campus，绝不能进 LLM
    r3 = bot.ask("校庆是哪天")
    print(f"  [校园] matched={r3['matched']} fallback={r3['fallback']}")
    assert "DeepSeek" not in r3["answer"], "校园事务绝不能进 LLM！"
    assert "DeepSeek 生成" not in r3["answer"]
    if not r3["matched"]:
        # 走路由器兜底，必须是 campus_only 类型
        assert r3["fallback"]["type"] == "campus_only", \
            f"校园事务应路由到 campus_only: {r3['fallback']}"
        assert r3["fallback"]["source"].startswith("fixed_campus"), \
            f"校园事务应走 fixed_campus: {r3['fallback']}"

    # 4. 通识 → LLM（无 key 时降级）
    r4 = bot.ask("如何提高英语口语")
    print(f"  [通识] matched={r4['matched']} fallback={r4['fallback']}")
    assert not r4["matched"]
    assert r4["fallback"] is not None
    assert r4["fallback"]["type"] == "general"

    # 5. 闲聊
    r5 = bot.ask("你好")
    print(f"  [闲聊] matched={r5['matched']} fallback={r5['fallback']}")
    assert not r5["matched"]
    assert r5["fallback"]["type"] == "chat"
    assert r5["fallback"]["source"] == "fixed_chat"

    print("\n✅ 端到端 5 条全部正常\n")


# ---------------------------------------------------------------- 主流程
if __name__ == "__main__":
    # 2026-09：FALLBACK_ROUTER_ENABLED 已删除 —— 路由器是唯一的兜底入口
    config.DEEPSEEK_ENABLED = True
    config.HEFENG_ENABLED = True

    results = []
    results.append(("classify",      test_classify()))
    results.append(("safety",        test_answers_safety()))
    results.append(("empty",         test_empty()))
    results.append(("end_to_end",    test_end_to_end()))

    print("=" * 60)
    print("汇总")
    print("=" * 60)
    for name, ok in results:
        print(f"  {'✅' if ok else '❌'} {name}")

    failed = [n for n, ok in results if not ok]
    if failed:
        print(f"\n❌ 失败: {failed}")
        sys.exit(1)
    print("\n🎉 全部通过")
