# -*- coding: utf-8 -*-
"""效果评估脚本

指标：
    召回率@1    Top-1 预测意图 == 正确意图 的占比         目标 ≥ 80%
    Top-3 命中率 正确意图出现在 Top-3 候选中的占比        目标 ≥ 95%
    未识别率    相似度低于阈值的占比                      目标 ≤ 10%
    误答率      命中但意图错误的占比                      目标 ≤ 5%
    误触发率    本该拒答却硬答了的占比（测试集中 tag=null 的样本）

用法：
    python evaluate.py                # 按 config.SIMILARITY_THRESHOLD 评估
    python evaluate.py --scan         # 遍历阈值，找最优点
    python evaluate.py --show-error   # 打印答错的样本，逐个分析
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.agent import FaqBot, clear_answer_cache, setup_stdio  # noqa: E402
from src import config  # noqa: E402


def load_test_set(path: Path | None = None) -> list[dict]:
    path = Path(path) if path else config.TEST_SET_PATH
    if not path.exists():
        raise FileNotFoundError(f"测试集不存在：{path}")
    with open(path, encoding="utf-8") as f:
        cases = json.load(f).get("cases", [])
    if not cases:
        raise ValueError(f"测试集为空：{path}")
    return cases


def evaluate(bot: FaqBot, cases: list[dict], threshold: float | None = None):
    """跑一遍测试集，返回 (指标字典, 错误样本列表)。"""
    if threshold is not None:
        bot.threshold = threshold

    answerable = [c for c in cases if c.get("expected_tag")]
    rejectable = [c for c in cases if not c.get("expected_tag")]

    hit1 = hit3 = unmatched = wrong = 0
    false_trigger = correct_reject = 0
    errors = []

    for i, case in enumerate(cases):
        q, expected = case["query"], case.get("expected_tag")
        # !! 每条样本必须用**独立身份**调用。
        #    W2 安全层按 IP / user_id 分桶限流，空身份会落进共享兜底桶
        #    （rate_limit._FALLBACK_KEY）。全用同一个身份连跑 120+ 条，
        #    第 31 条起就会吃限流拒绝（IP 桶 capacity=30），返回值 matched=False，
        #    在报表上表现为"未识别率 75%"这种假红灯 ——
        #    实测 123 条里 93 条被拒，93/123 = 75.6%，和限流容量严丝合缝。
        #    评估脚本不是"一个用户狂问 127 次"，给它独立身份才对得上真实语义。
        r = bot.ask(q, user_id=f"eval-{i}", client_ip=f"10.0.{i // 250}.{i % 250 + 1}")
        top3_tags = [c["tag"] for c in r["candidates"]]

        if expected:  # 应回答
            if r["matched"] and r["tag"] == expected:
                hit1 += 1
                hit3 += 1
            elif not r["matched"]:
                unmatched += 1
                if expected in top3_tags:
                    hit3 += 1
                errors.append((q, expected, r["tag"], r["score"], r["matched_question"], "未命中"))
            else:
                wrong += 1
                if expected in top3_tags:
                    hit3 += 1
                errors.append((q, expected, r["tag"], r["score"], r["matched_question"], "答错意图"))
        else:  # 应拒答
            if r["matched"]:
                false_trigger += 1
                errors.append((q, "（应拒答）", r["tag"], r["score"], r["matched_question"], "误触发"))
            else:
                correct_reject += 1

    n = max(1, len(answerable))
    m = max(1, len(rejectable))
    metrics = {
        "threshold": bot.threshold,
        "total": len(cases),
        "answerable": len(answerable),
        "rejectable": len(rejectable),
        "recall@1": hit1 / n,
        "top3": hit3 / n,
        "unmatched_rate": unmatched / n,
        "wrong_rate": wrong / n,
        "false_trigger_rate": false_trigger / m,
        "accuracy": (hit1 + correct_reject) / max(1, len(cases)),
    }
    return metrics, errors


def print_metrics(m: dict) -> None:
    print("\n" + "=" * 56)
    print(f"  评估结果   阈值 = {m['threshold']:.2f}   向量化 = {m.get('vectorizer', 'tfidf')}")
    print("=" * 56)
    rows = [
        ("召回率@1", m["recall@1"], "≥ 80%", m["recall@1"] >= 0.80),
        ("Top-3 命中率", m["top3"], "≥ 95%", m["top3"] >= 0.95),
        ("未识别率", m["unmatched_rate"], "≤ 10%", m["unmatched_rate"] <= 0.10),
        ("误答率", m["wrong_rate"], "≤ 5%", m["wrong_rate"] <= 0.05),
        ("误触发率", m["false_trigger_rate"], "≤ 10%", m["false_trigger_rate"] <= 0.10),
        ("整体准确率", m["accuracy"], "—", None),
    ]
    print(f"{'指标':<14}{'实测':>10}{'目标':>10}   判定")
    print("-" * 56)
    for name, val, target, ok in rows:
        flag = "达标" if ok else ("—" if ok is None else "未达标")
        print(f"{name:<14}{val:>9.1%}{target:>10}   {flag}")
    print("-" * 56)
    print(f"样本：可答 {m['answerable']} 条 / 应拒答 {m['rejectable']} 条\n")


def scan_threshold(bot: FaqBot, cases: list[dict]) -> None:
    """遍历阈值，观察『准确率 vs 未识别率』的权衡曲线。"""
    print("\n阈值扫描（步长 0.05）")
    print("-" * 74)
    print(f"{'阈值':>6}{'召回率@1':>11}{'Top-3':>10}{'未识别率':>11}{'误答率':>10}{'误触发':>10}")
    print("-" * 74)

    best = None
    t = 0.05
    while t <= 0.9001:
        # !! 答案是全局缓存的，不清空的话第一轮之后全是缓存命中，
        #    18 个阈值会得到 18 行完全一样的数字（曲线退化成直线）。
        clear_answer_cache()
        m, _ = evaluate(bot, cases, threshold=round(t, 2))
        print(
            f"{m['threshold']:>6.2f}{m['recall@1']:>10.1%}{m['top3']:>10.1%}"
            f"{m['unmatched_rate']:>10.1%}{m['wrong_rate']:>10.1%}"
            f"{m['false_trigger_rate']:>10.1%}"
        )
        # 选点策略：误答率 ≤5% 且误触发率 ≤20% 的前提下，
        # 取召回率@1 最高的平台；同一平台上取更保守（更高）的阈值，
        # 避免选到 0.05 这种对真实噪声毫无抵抗力的值。
        if m["wrong_rate"] <= 0.05 and m["false_trigger_rate"] <= 0.20:
            if (
                best is None
                or m["recall@1"] > best["recall@1"]
                or (m["recall@1"] == best["recall@1"] and m["threshold"] > best["threshold"])
            ):
                best = m
        t += 0.05

    print("-" * 74)
    if best:
        print(
            f"推荐阈值：{best['threshold']:.2f}  "
            f"（召回率@1 = {best['recall@1']:.1%}，误答率 = {best['wrong_rate']:.1%}，"
            f"误触发率 = {best['false_trigger_rate']:.1%}）"
        )
        print(f"把 src/config.py 里的 SIMILARITY_THRESHOLD 改成 {best['threshold']:.2f} 即可生效。")
    else:
        print("没有阈值同时满足『误答率 ≤5% 且误触发率 ≤20%』。")
        print("这通常说明语料本身不够（换种问法就答不上），优先补语料而不是死磕阈值。")
    print()


def main() -> None:
    setup_stdio()

    parser = argparse.ArgumentParser(description="FAQ 机器人效果评估")
    parser.add_argument("--scan", action="store_true", help="扫描阈值找最优点")
    parser.add_argument("--show-error", action="store_true", help="打印答错的样本")
    parser.add_argument("--threshold", type=float, help="临时指定阈值，不改动配置文件")
    parser.add_argument(
        "--backend", choices=["tfidf", "bert", "bge"], help="临时指定向量化方案，覆盖 config.VECTORIZER_TYPE"
    )
    parser.add_argument(
        "--min-recall", type=float, default=None, help="回归门禁：召回率@1 低于该值即非零退出（CI 用，如 0.95）"
    )
    args = parser.parse_args()

    bot = FaqBot(vectorizer_type=args.backend)
    cases = load_test_set()

    s = bot.stats()
    print(
        f"索引：{s['intents']} 个意图 / {s['questions']} 条问法"
        f"   向量化：{s['vectorizer']}   构建耗时 {s['build_ms']:.1f} ms"
    )

    if config.ENABLE_RERANK:
        print(
            "\n!! ENABLE_RERANK=True：命中判定走 RERANK_THRESHOLD（精排分），"
            "--threshold / --scan 调的是余弦阈值，对结果没有影响。"
        )
        print("   标定精排阈值：临时改 config.RERANK_THRESHOLD 后重跑本脚本。\n")

    if args.scan:
        scan_threshold(bot, cases)
        return

    if args.threshold is not None:
        bot.threshold = args.threshold

    metrics, errors = evaluate(bot, cases, threshold=args.threshold)
    metrics["vectorizer"] = s["vectorizer"]
    print_metrics(metrics)

    if args.show_error and errors:
        print("答错的样本：")
        print("-" * 74)
        for q, expected, got, score, matched_q, kind in errors:
            print(f"[{kind}] {q}")
            print(f"    期望：{expected}   实际：{got}   分数：{score:.4f}")
            if matched_q:
                print(f"    误匹配到：{matched_q}")
        print("-" * 74)
        print("\n改进方向（按性价比排序）：")
        print("  1. 给对应意图补 3-5 条真实用户会用的问法 —— 提升最明显")
        print("  2. 把问句里的核心词加进 config.CUSTOM_WORDS，防止被 jieba 切碎")
        print("  3. 分数明明很高却答错 → 两个意图的问法太像，需要拉开差异")
        print("  4. 分数普遍偏低 → 词面匹配到瓶颈了，考虑升级 BERT 向量化\n")
    elif not errors:
        print("全部答对。这时要警惕：测试集可能太简单，或已被语料污染。\n")

    # ---------------------------------------------------------------- 回归门禁
    # CI 此前只跑单测：改检索 / 语料后召回率掉了，测试仍全绿（测试集固定，
    # 且不校验效果指标）。--min-recall 把「最小召回率基线」变成可断言的出口，
    # 由 .github/workflows/ci.yml 调用。
    if args.min_recall is not None:
        got = metrics["recall@1"]
        if got < args.min_recall:
            hit = round(got * metrics["answerable"])
            print(
                f"!! 效果回归：召回率@1 {got:.1%} < 基线 {args.min_recall:.1%}"
                f"（{hit}/{metrics['answerable']} 条可答样本命中）"
            )
            print("   用 --show-error 看是哪些意图掉了，再决定补问法还是回滚改动。")
            sys.exit(1)
        print(f"OK 效果门禁：召回率@1 {got:.1%} ≥ 基线 {args.min_recall:.1%}")


if __name__ == "__main__":
    main()
