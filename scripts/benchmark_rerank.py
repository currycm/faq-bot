# -*- coding: utf-8 -*-
"""精排（Cross-Encoder）实测：rerank 前后排序对比 + RERANK_THRESHOLD 标定。

用法：
    python scripts/benchmark_rerank.py                    # 默认 K=3,5,10
    python scripts/benchmark_rerank.py --topk 3,20
    python scripts/benchmark_rerank.py --show 8           # 打印 8 条排序变化示例
    python scripts/benchmark_rerank.py --probe            # 额外跑一组易混淆探针

--------------------------------------------------------------------------
为什么需要这个脚本
--------------------------------------------------------------------------
1. `RERANK_THRESHOLD = 0.5` 是**占位值**，必须标定。
2. `evaluate.py --threshold / --scan` 调的是**余弦**阈值，**对精排完全无效**
   —— 两种分数不同量纲（见 src/ranker.py 模块注释）。所以标定只能在精排分上做，
   本脚本就是干这个的。
3. `TOP_K = 3`：精排只能在召回交给它的候选里重排，
   **召回的天花板就是精排的天花板**。所以按多个 K 分别跑，
   看"多给候选"能不能把精排的价值释放出来。

--------------------------------------------------------------------------
刻意绕开的一环（别改）
--------------------------------------------------------------------------
直接调 `retriever.search` + `ranker.rerank`，**不走 ask() / 安全层**。
历史教训：不带独立身份批量调 `ask()` 会全落进同一个 IP 限流桶（容量 30），
第 31 条起被拒并被记成"未命中"，召回率会假跌到 24%、延迟还会假性变快。
这里测的是**排序层本身**，绕开限流是正确做法 —— 也因此不需要逐样本身份，
更不需要清答案缓存（根本没走缓存）。
真正的端到端限流/缓存影响由 `scripts/benchmark_throughput.py` 负责。

--------------------------------------------------------------------------
延迟怎么测才可信
--------------------------------------------------------------------------
走**生产同一条代码路径**（逐条 `ranker.rerank`），而不是我自己批量 predict，
这样测到的延迟就是线上真实要付的。模型推理本身有波动（同类项目实测 9.0~9.8ms
上下晃），所以取中位数与 P95，而不是单次值。
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import evaluate as ev  # noqa: E402
from src import config  # noqa: E402
from src.agent import FaqBot  # noqa: E402
from src.ranker import CrossEncoderRanker  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def pct(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    idx = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[idx]


def run_k(ranker: CrossEncoderRanker, bot: FaqBot, cases: list[dict], K: int, collect_examples: bool = True) -> dict:
    """跑一遍测试集：K 个候选 → 精排 → 记录命中性、排序变化、延迟。"""
    ret_times: list[float] = []
    rrk_times: list[float] = []
    cos_hit1 = rrk_hit1 = cos_hit3 = rrk_hit3 = vote_hit1 = 0
    n_ans = 0
    changed = 0
    rescuable = 0  # 余弦 top1 错、但前 K 里有正解 → 精排"有机会救"
    rescued = 0  # 上面那批里精排确实把正解推到 top1
    examples: list[dict] = []
    rows: list[dict] = []  # 供阈值扫描用

    for case in cases:
        q, expected = case["query"], case.get("expected_tag")

        t0 = time.perf_counter()
        hits = bot.retriever.search(q, top_k=K)
        t1 = time.perf_counter()
        if not hits:
            continue

        # 精排前先快照余弦序（ranker 会原地写 rerank_score 并返回新列表）
        before = [(h.tag, h.question, h.score) for h in hits]

        t2 = time.perf_counter()
        ordered = ranker.rerank(q, hits)
        t3 = time.perf_counter()

        ret_times.append((t1 - t0) * 1000)
        rrk_times.append((t3 - t2) * 1000)

        after = [(h.tag, h.question, h.rerank_score) for h in ordered]
        top1 = ordered[0]

        # 变体：**意图计数投票**。
        # 动机：实测发现精排常被"句式相同、话题不同"的单条候选带偏
        # （例：「GPA 在哪里能看到」输给「在哪看学校平面图」，两者都是"X 在哪里看"）。
        # 单条被带偏就满盘皆输；而 top-K 里**正解意图通常占多数候选**，
        # 所以按 tag 计数、票多者胜（平票时比该意图的最高精排分）。
        #
        # 注：曾经想写"按 tag 取最高精排分再比"——那是**恒等于全局最高分**的无意义变体
        # （max over tags of max-in-tag == global max），已弃用。
        cnt: dict[str, int] = {}
        best: dict[str, float] = {}
        for h in ordered:
            cnt[h.tag] = cnt.get(h.tag, 0) + 1
            best[h.tag] = max(best.get(h.tag, 0.0), h.rerank_score)
        vote_tag = max(cnt, key=lambda t: (cnt[t], best[t])) if cnt else None

        rows.append(
            {
                "query": q,
                "expected": expected,
                "cos_top1": before[0][0],
                "cos_score": before[0][2],
                "rrk_top1": top1.tag,
                "rrk_score": top1.rerank_score,
                "vote_tag": vote_tag,
                "vote_score": best.get(vote_tag, 0.0) if vote_tag else 0.0,
                "rrk_answers": top1.rerank_score >= config.RERANK_THRESHOLD,
            }
        )

        if expected is None:
            continue  # 应拒答样本只用于阈值扫描
        n_ans += 1
        tags_cos = [t for t, _, _ in before]
        tags_rrk = [t for t, _, _ in after]
        if tags_cos[0] == expected:
            cos_hit1 += 1
        if expected in tags_cos[:3]:
            cos_hit3 += 1
        if tags_rrk[0] == expected:
            rrk_hit1 += 1
        if vote_tag == expected:
            vote_hit1 += 1
        if expected in tags_rrk[:3]:
            rrk_hit3 += 1
        if tags_rrk != tags_cos:
            changed += 1
        if tags_cos[0] != expected and expected in tags_cos:
            rescuable += 1
            if tags_rrk[0] == expected:
                rescued += 1
        if collect_examples and tags_rrk != tags_cos:
            examples.append(
                {
                    "query": q,
                    "expected": expected,
                    "before": before,
                    "after": after,
                    "fixed": tags_cos[0] != expected and tags_rrk[0] == expected,
                    "broke": tags_cos[0] == expected and tags_rrk[0] != expected,
                }
            )

    return {
        "K": K,
        "n": n_ans,
        "rows": rows,
        "examples": examples,
        "cos_hit1": cos_hit1,
        "cos_hit3": cos_hit3,
        "rrk_hit1": rrk_hit1,
        "rrk_hit3": rrk_hit3,
        "vote_hit1": vote_hit1,
        "changed": changed,
        "rescuable": rescuable,
        "rescued": rescued,
        "ret_med": statistics.median(ret_times),
        "ret_p95": pct(ret_times, 0.95),
        "rrk_med": statistics.median(rrk_times),
        "rrk_p95": pct(rrk_times, 0.95),
    }


def print_metrics(results: list[dict]) -> None:
    print("\n" + "=" * 96)
    print("  一、rerank 前后排序质量（测试集可答样本）")
    print("=" * 96)
    print(
        f"{'K':>3} {'样本':>5} | {'余弦@1':>8} {'精排@1':>8} {'计数投票@1':>10} | "
        f"{'余弦@3':>8} {'精排@3':>8} | {'排序变化':>8} {'可救集':>7} {'救回':>5}"
    )
    print("-" * 96)
    for r in results:
        n = r["n"]
        print(
            f"{r['K']:>3} {n:>5} | {r['cos_hit1'] / n:>7.1%} {r['rrk_hit1'] / n:>8.1%} "
            f"{r['vote_hit1'] / n:>10.1%} | "
            f"{r['cos_hit3'] / n:>7.1%} {r['rrk_hit3'] / n:>8.1%} | "
            f"{r['changed']:>8} {r['rescuable']:>7} {r['rescued']:>5}"
        )
    print("-" * 96)
    print("「可救集」= 余弦 top1 答错、但前 K 个候选里存在正解 → 精排*原则上*有机会救回")
    print("「救回」  = 可救集里精排确实把正解推到了 top1")
    print("「计数投票@1」= top-K 内按意图计数，票多者胜（平票比该意图最高精排分）")


def print_latency(results: list[dict]) -> None:
    print("\n" + "=" * 96)
    print("  二、延迟（毫秒 / 单次 ask 的排序层开销，CPU）")
    print("=" * 96)
    print(
        f"{'K':>3} | {'检索 中位':>10} {'检索 P95':>10} | {'精排 中位':>10} {'精排 P95':>10} | "
        f"{'合计 中位':>10} {'相对检索':>10}"
    )
    print("-" * 96)
    for r in results:
        tot = r["ret_med"] + r["rrk_med"]
        print(
            f"{r['K']:>3} | {r['ret_med']:>10.1f} {r['ret_p95']:>10.1f} | "
            f"{r['rrk_med']:>10.1f} {r['rrk_p95']:>10.1f} | {tot:>10.1f} "
            f"{tot / r['ret_med']:>9.1f}x"
        )


def scan_threshold(rows: list[dict], K: int) -> None:
    """在**精排分**上扫阈值。evaluate.py 的 --scan 调的是余弦阈值，对精排无效。"""
    print("\n" + "=" * 96)
    print(f"  三、RERANK_THRESHOLD 标定（K={K}；config 现值 {config.RERANK_THRESHOLD} 只是占位）")
    print("=" * 96)
    print(f"{'阈值':>6} {'命中正确':>9} {'未识别':>8} {'答错':>7} {'误触发':>8} {'整体准确率':>10}")
    print("-" * 96)
    ans = [r for r in rows if r["expected"]]
    rej = [r for r in rows if not r["expected"]]
    for t in [round(0.05 * i, 2) for i in range(1, 20)]:
        ok = miss = wrong = ft = 0
        for r in ans:
            if r["rrk_score"] < t:
                miss += 1
            elif r["rrk_top1"] == r["expected"]:
                ok += 1
            else:
                wrong += 1
        for r in rej:
            if r["rrk_score"] >= t:
                ft += 1
        acc = (ok + (len(rej) - ft)) / max(1, len(rows))
        mark = "  ←" if abs(t - config.RERANK_THRESHOLD) < 1e-9 else ""
        print(
            f"{t:>6.2f} {ok / len(ans):>9.1%} {miss / len(ans):>8.1%} {wrong / len(ans):>7.1%} "
            f"{ft}/{len(rej):>6} {acc:>10.1%}{mark}"
        )
    print("-" * 96)
    print("「误触发」= 应拒答样本里精排分仍 ≥ 阈值（会被当成可答而硬答）")


def print_examples(examples: list[dict], limit: int) -> None:
    if not examples:
        print("\n（没有排序发生变化的样本）")
        return
    print("\n" + "=" * 96)
    print(f"  四、排序变化实例（共 {len(examples)} 条，展示前 {min(limit, len(examples))} 条）")
    print("=" * 96)
    fixed = [e for e in examples if e["fixed"]]
    broke = [e for e in examples if e["broke"]]
    print(f"其中：精排修好 {len(fixed)} 条，精排弄坏 {len(broke)} 条，其余只是同 tag 内问法顺序变化\n")
    # 先放"修好"和"弄坏"的（最有信息量），再补其余；按 query 去重，避免重复打印
    picked: list[dict] = []
    seen_q: set[str] = set()
    for e in fixed + broke + examples:
        if e["query"] in seen_q:
            continue
        seen_q.add(e["query"])
        picked.append(e)
        if len(picked) >= limit:
            break
    for e in picked:
        flag = "✅修好" if e["fixed"] else ("❌弄坏" if e["broke"] else "· 换序")
        print(f"[{flag}] {e['query']}   期望：{e['expected']}")
        print("   精排前：" + " > ".join(f"{t}({s:.3f})" for t, q, s in e["before"]))
        print("   精排后：" + " > ".join(f"{t}({s:.3f})" for t, q, s in e["after"]))
        print(f"   精排把 “{e['after'][0][1]}” 排到了最前")
        print()


def run_probe(ranker: CrossEncoderRanker, bot: FaqBot, K: int) -> None:
    """易混淆探针：近邻意图之间，看精排能不能拉开区分度。"""
    probes = [
        ("图书馆几点开门", "library_hours"),
        ("图书馆能借几本书", "library_borrow"),
        ("图书馆有没有存包柜", "library_service"),
        ("学生证丢了怎么办", "jwc_student_id_reissue"),
        ("校园卡丢了怎么办", "lost_card"),
        ("怎么开学历证明", "jwc_certificate_issue"),
        ("成绩单在哪里打印", "transcript"),
        ("暑假能留校住吗", "dorm_summer_stay"),
        ("宿舍电费怎么交", "dorm_electricity"),
        ("宿舍晚上几点熄灯", "dorm_curfew"),
        ("什么时候放寒假", "academic_calendar"),
        ("学费一年多少钱", "tuition_fee"),
    ]
    print("\n" + "=" * 96)
    print(f"  五、易混淆探针（K={K}，人挑的近邻意图）")
    print("=" * 96)
    for q, expected in probes:
        hits = bot.retriever.search(q, top_k=K)
        before = [(h.tag, h.score) for h in hits]
        ordered = ranker.rerank(q, hits)
        after = [(h.tag, h.rerank_score) for h in ordered]
        cos_ok = "✅" if before[0][0] == expected else "❌"
        rrk_ok = "✅" if after[0][0] == expected else "❌"
        print(f"{q}   期望 {expected}")
        print(f"   余弦 {cos_ok} " + " > ".join(f"{t}({s:.3f})" for t, s in before))
        print(f"   精排 {rrk_ok} " + " > ".join(f"{t}({s:.3f})" for t, s in after))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topk", default="3,5,10", help="逗号分隔的 K 列表")
    ap.add_argument("--show", type=int, default=6, help="打印几条排序变化实例")
    ap.add_argument("--probe", action="store_true", help="额外跑易混淆探针")
    args = ap.parse_args()

    print("[加载] 语料 + BGE + Cross-Encoder…")
    t0 = time.perf_counter()
    bot = FaqBot()  # ENABLE_RERANK 默认 False → 直通，用于取余弦候选
    s = bot.stats()
    ranker = CrossEncoderRanker()
    import torch

    print(
        f"[就绪] 索引 {s['intents']} 意图 / {s['questions']} 问法 ｜ 向量化 {s['vectorizer']} ｜ "
        f"精排模型 {ranker.model_name} ｜ torch 线程 {torch.get_num_threads()} ｜ "
        f"耗时 {time.perf_counter() - t0:.1f}s"
    )

    cases = ev.load_test_set()
    print(
        f"[测试集] {len(cases)} 条（可答 {sum(1 for c in cases if c.get('expected_tag'))} / "
        f"应拒答 {sum(1 for c in cases if not c.get('expected_tag'))}）"
    )

    ks = [int(x) for x in args.topk.split(",")]
    results = []
    for K in ks:
        t = time.perf_counter()
        r = run_k(ranker, bot, cases, K)
        results.append(r)
        print(f"[K={K}] 完成，耗时 {time.perf_counter() - t:.1f}s")

    print_metrics(results)
    print_latency(results)
    scan_threshold(results[-1]["rows"], results[-1]["K"])
    if args.show:
        print_examples(results[0]["examples"], args.show)
    if args.probe:
        run_probe(ranker, bot, ks[0])


if __name__ == "__main__":
    main()
