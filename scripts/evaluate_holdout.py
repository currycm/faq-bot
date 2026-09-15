# -*- coding: utf-8 -*-
"""留出集评测：每个意图只保留 K 条问法建索引，剩下的留出来测。

--------------------------------------------------------------------------
它回答的问题（也是它存在的理由）
--------------------------------------------------------------------------
项目 README 里有一个**从未被验证过的核心论断**：
「把每条问法补到 8 条覆盖不同说法，收益大于换更强的算法」。

本脚本用**缩减索引**去检验它：每意图只留 K 条问法建索引，然后看召回怎么变。
- 若 K=3 与 K=8 差不多 → **堆问法的边际收益很低**，那个论断站不住；
- 若下降明显 → 论断成立，"补问法"确实是性价比最高的一招。

--------------------------------------------------------------------------
两个探针，测的是两件事
--------------------------------------------------------------------------
- **探针 A：`tests/test_set.json`（207 条）** —— 它**不在语料里**（有断言保证），
  所以是真正"没见过的说法"。这是**主指标**。
- **探针 B：被留出的那批语料问法** —— 测"自己的问法能不能被兄弟问法召回"。
  实测它比探针 A **更难**（K=3 时 68.7% vs 76.5%）——我原本预判它更容易，错了。
  原因推测：语料问法里有大量短句/省略式（"多少钱""怎么申请"），
  单条自身区分度低；而测试集问法是刻意改写、话题词更明确。
  这个现象与 `docs/rerank_report.md` 的「句式压过话题」是同一件事的两面。

--------------------------------------------------------------------------
已知局限（写在报告里，别当成"开放集"）
--------------------------------------------------------------------------
语料与测试集**出自同一作者**，用词习惯一致 → 绝对数字偏乐观。
本脚本只声称**相对趋势**有信息量（K 变化引起的召回变化），不声称绝对值等于线上表现。
项目**没有真实用户数据**（`logs/unmatched.jsonl` 去重后仅 210 条，其中 132 条直接来自测试集，
其余是压测循环 → 不能当开放集，详见 `docs/pending_items.md`）。

用法：
    python scripts/evaluate_holdout.py                     # K=8,6,5,4,3 × 3 个随机划分
    python scripts/evaluate_holdout.py --ks 8,5,3 --seeds 5
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import evaluate as ev                                      # noqa: E402
from src import config, preprocess                         # noqa: E402
from src.agent import flatten, load_corpus                 # noqa: E402
from src.retriever import Retriever                        # noqa: E402
from src.vectorizer import build_vectorizer                # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def probe(retr: Retriever, cases: list[tuple[str, str | None]]) -> dict:
    """跑一批 (query, expected_tag)。逐条调 search，不经过安全层（同 benchmark_rerank 的理由）。"""
    n_ans = hit1 = hit3 = unmatched = 0
    false_trigger = 0
    n_rej = 0
    per_intent_miss: dict[str, int] = {}
    per_intent_tot: dict[str, int] = {}
    for i, (q, exp) in enumerate(cases):
        hits = retr.search(q, top_k=3)
        if not hits:
            top1_tag, top1_score, top3 = None, 0.0, []
        else:
            top1_tag, top1_score = hits[0].tag, hits[0].score
            top3 = [h.tag for h in hits]
        if exp is None:
            n_rej += 1
            if top1_score >= config.SIMILARITY_THRESHOLD:
                false_trigger += 1
            continue
        n_ans += 1
        per_intent_tot[exp] = per_intent_tot.get(exp, 0) + 1
        if top1_score < config.SIMILARITY_THRESHOLD:
            unmatched += 1
            per_intent_miss[exp] = per_intent_miss.get(exp, 0) + 1
            continue
        if top1_tag == exp:
            hit1 += 1
        else:
            per_intent_miss[exp] = per_intent_miss.get(exp, 0) + 1
        if exp in top3:
            hit3 += 1
    return {
        "n": n_ans, "hit1": hit1 / max(1, n_ans), "hit3": hit3 / max(1, n_ans),
        "unmatched": unmatched / max(1, n_ans),
        "false_trigger": false_trigger, "n_rej": n_rej,
        "per_intent_miss": per_intent_miss, "per_intent_tot": per_intent_tot,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ks", default="8,6,5,4,3", help="每意图保留的问法条数（逗号分隔）")
    ap.add_argument("--seeds", type=int, default=3, help="随机划分次数，取均值")
    args = ap.parse_args()

    t0 = time.perf_counter()
    intents = load_corpus()
    total_q = sum(len(it["questions"]) for it in intents)
    sizes = sorted(len(it["questions"]) for it in intents)
    print(f"[语料] {len(intents)} 意图 / {total_q} 问法 ｜每意图问法数 最少 {sizes[0]} / 中位 "
          f"{sizes[len(sizes)//2]} / 最多 {sizes[-1]}")

    vec = build_vectorizer()
    vec.fit([preprocess.cut(q) for it in intents for q in it["questions"]])
    print(f"[就绪] 向量化 {vec.name} ｜ 耗时 {time.perf_counter()-t0:.1f}s\n")

    test_cases = [(c["query"], c.get("expected_tag")) for c in ev.load_test_set()]
    ks = [int(x) for x in args.ks.split(",")]

    # ---------------- 基线：全量索引 ----------------
    retr_full = Retriever(vec, flatten(intents), text_fn=preprocess.cut)
    base = probe(retr_full, test_cases)
    print("=" * 92)
    print("  探针 A：测试集（207 条，**不在语料里** → 真正没见过的说法）")
    print("=" * 92)
    print(f"{'索引':>16} {'问法数':>7} | {'召回@1':>9} {'Top-3':>8} {'未识别':>8} | {'误触发':>8}")
    print("-" * 92)
    print(f"{'全量（基线）':>16} {total_q:>7} | {base['hit1']:>8.1%} {base['hit3']:>8.1%} "
          f"{base['unmatched']:>8.1%} | {base['false_trigger']}/{base['n_rej']}")

    # ---------------- 各 K ----------------
    rows = []
    last_miss_stats: dict[str, dict] = {}
    for K in ks:
        acc = []
        for seed in range(args.seeds):
            rng = random.Random(seed * 1000 + K)
            reduced = []
            for it in intents:
                qs = list(it["questions"])
                keep = qs if len(qs) <= K else rng.sample(qs, K)
                reduced.append({**it, "questions": keep})
            held_out = [
                (q, it["tag"])
                for it, orig in zip(reduced, intents)
                for q in orig["questions"] if q not in it["questions"]
            ]
            retr = Retriever(vec, flatten(reduced), text_fn=preprocess.cut)
            a = probe(retr, test_cases)
            if seed == 0:
                b = probe(retr, held_out)          # 探针 B 只跑第一个划分（省时间）
                last_miss_stats = {
                    "n_idx": sum(len(it["questions"]) for it in reduced),
                    "b": b,
                    "miss": a["per_intent_miss"],
                    "tot": a["per_intent_tot"],
                }
            acc.append(a)
        m = {k: statistics.fmean([a[k] for a in acc]) for k in ("hit1", "hit3", "unmatched")}
        lo = min(a["hit1"] for a in acc)
        hi = max(a["hit1"] for a in acc)
        rows.append({"K": K, **m, "lo": lo, "hi": hi})
        print(f"{'每意图留 %d 条' % K:>16} {last_miss_stats['n_idx']:>7} | "
              f"{m['hit1']:>8.1%} {m['hit3']:>8.1%} {m['unmatched']:>8.1%} | "
              f"{acc[0]['false_trigger']}/{acc[0]['n_rej']}   "
              f"(召回@1 极差 {lo:.1%}~{hi:.1%}, {args.seeds} 次划分)")
    print("-" * 92)
    d = rows[-1]["hit1"] - base["hit1"]
    print(f"最激进的一档（每意图留 {rows[-1]['K']} 条）相对全量基线：召回@1 "
          f"{base['hit1']:.1%} → {rows[-1]['hit1']:.1%}（{'−' if d < 0 else '+'}{abs(d):.1%}）")

    # ---------------- 探针 B ----------------
    if last_miss_stats:
        b = last_miss_stats["b"]
        print("\n" + "=" * 92)
        print(f"  探针 B：被留出的语料问法（K={rows[-1]['K']} 时，共 {b['n']} 条）")
        print("=" * 92)
        print(f"  召回@1 {b['hit1']:.1%} ｜ Top-3 {b['hit3']:.1%} ｜ 未识别 {b['unmatched']:.1%}")
        print("  注意：实测它比探针 A **更难**（脚本里原预判「更容易」是错的）——")
        print("  语料问法里短句/省略式多（'多少钱''怎么申请'），单条自身区分度低")

    # ---------------- 谁最依赖"问法数量" ----------------
    miss, tot = last_miss_stats.get("miss", {}), last_miss_stats.get("tot", {})
    hurts = sorted(((miss.get(t, 0) / tot[t], t) for t in tot if tot[t]), reverse=True)[:6]
    print("\n" + "=" * 92)
    print(f"  索引最稀疏时（每意图留 {rows[-1]['K']} 条）**掉得最多**的意图")
    print("=" * 92)
    for rate, tag in hurts:
        print(f"  错 {rate:>5.0%}  {tag}   （测试集里 {tot[tag]} 条）")
    print("\n  这些意图的问法覆盖比较薄 —— 若要补问法，优先补它们")


if __name__ == "__main__":
    main()
