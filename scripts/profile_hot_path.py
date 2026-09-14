# -*- coding: utf-8 -*-
"""热路径剖析：定位 ask() 里被慢逻辑拖累的部分。

用法：
    python scripts/profile_hot_path.py              # cProfile Top-20 + 端到端延迟
    python scripts/profile_hot_path.py --no-profile # 只测延迟（快）
    python scripts/profile_hot_path.py -n 300       # 指定样本数

只跑**语料命中**的样本（不触发 LLM / 天气），测的是最热的路径。
每个样本用独立身份，避免限流把结果污染（见 README「限流会拦自家脚本」）。
"""
from __future__ import annotations

import argparse
import cProfile
import io
import json
import pstats
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import FaqBot, clear_answer_cache  # noqa: E402


def load_queries(n: int) -> list[str]:
    """取一批确定能命中语料的问法（改写的测试问法，和语料原句不重复）。"""
    cases = json.load(open("tests/test_set.json", encoding="utf-8"))["cases"]
    qs = [c["query"] for c in cases if c.get("expected_tag")]
    # 循环补足到 n 条
    return [qs[i % len(qs)] for i in range(n)]


def timed_run(bot: FaqBot, queries: list[str]) -> dict:
    """返回延迟统计。每个样本独立身份 + 每次清空缓存，确保是冷的真实链路。"""
    lat = []
    for i, q in enumerate(queries):
        clear_answer_cache()          # 排除答案缓存干扰，测真实链路
        t0 = time.perf_counter()
        bot.ask(q, user_id=f"prof-{i}", client_ip=f"10.60.{i // 250}.{i % 250 + 1}")
        lat.append((time.perf_counter() - t0) * 1000)
    s = sorted(lat)
    return {
        "n": len(lat),
        "p50": s[len(s) // 2],
        "p90": s[int(len(s) * 0.9) - 1],
        "p99": s[int(len(s) * 0.99) - 1],
        "mean": statistics.mean(lat),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=200, help="样本数（默认 200）")
    ap.add_argument("--no-profile", action="store_true", help="跳过 cProfile，只测延迟")
    args = ap.parse_args()

    queries = load_queries(args.n)
    bot = FaqBot()
    bot.ask("测试预热")            # 预热懒加载，避免污染 P99

    print(f"== 热路径剖析：{len(queries)} 条命中样本（已预热，逐条清缓存）==")
    stat = timed_run(bot, queries)
    print(f"P50 {stat['p50']:.2f} ms   P90 {stat['p90']:.2f} ms   "
          f"P99 {stat['p99']:.2f} ms   均值 {stat['mean']:.2f} ms")

    if args.no_profile:
        return

    print("\n== cProfile 累计耗时 Top-20 ==")
    pr = cProfile.Profile()
    pr.enable()
    timed_run(bot, queries[: max(50, len(queries) // 4)])
    pr.disable()
    buf = io.StringIO()
    pstats.Stats(pr, stream=buf).sort_stats("cumulative").print_stats(20)
    print(buf.getvalue())


if __name__ == "__main__":
    main()
