# -*- coding: utf-8 -*-
"""检索方案实测对比：TF-IDF / BGE / BGE+精排

输出一张可直接贴进 README 的 Markdown 表，包含：
    构建耗时、召回率@1、Top-3 命中率、未识别率、误答率、误触发率、
    查询延迟 P50 / P99（端到端 ask，含安全层开销）。

用法：
    python scripts/benchmark_retrieval.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import FaqBot
import evaluate as ev


CONFIGS = [
    ("TF-IDF", dict(vectorizer_type="tfidf", enable_rerank=False)),
    ("BGE-small", dict(vectorizer_type="bge", enable_rerank=False)),
    ("BGE + 精排", dict(vectorizer_type="bge", enable_rerank=True)),
]


def percentile(latencies_ms: list[float], p: float) -> float:
    if not latencies_ms:
        return 0.0
    s = sorted(latencies_ms)
    k = max(0, min(len(s) - 1, int(round((p / 100) * (len(s) - 1)))))
    return s[k]


def main() -> None:
    cases = ev.load_test_set()
    print(f"测试集：{len(cases)} 条（可答 {sum(1 for c in cases if c.get('expected_tag'))} "
          f"/ 应拒答 {sum(1 for c in cases if not c.get('expected_tag'))}）\n")

    print(f"{'方案':<12}{'构建ms':>9}{'召回@1':>9}{'Top3':>9}"
          f"{'未识别':>9}{'误答':>9}{'误触发':>9}{'P50ms':>9}{'P99ms':>9}")
    print("-" * 88)

    for name, kw in CONFIGS:
        try:
            bot = FaqBot(**kw)
        except Exception as exc:  # 精排模型下载失败等
            print(f"{name:<12} 跳过：{type(exc).__name__}: {exc}")
            continue

        build_ms = bot.stats()["build_ms"]

        # 预热一次，避免首查询懒加载污染 P99
        bot.ask("测试预热")
        latencies: list[float] = []
        for c in cases:
            t0 = time.perf_counter()
            bot.ask(c["query"])
            latencies.append((time.perf_counter() - t0) * 1000.0)

        metrics, _ = ev.evaluate(bot, cases)
        print(f"{name:<12}{build_ms:>9.1f}{metrics['recall@1']:>8.1%}{metrics['top3']:>8.1%}"
              f"{metrics['unmatched_rate']:>8.1%}{metrics['wrong_rate']:>8.1%}"
              f"{metrics['false_trigger_rate']:>8.1%}"
              f"{percentile(latencies, 50):>9.2f}{percentile(latencies, 99):>9.2f}")


if __name__ == "__main__":
    main()
