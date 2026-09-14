# -*- coding: utf-8 -*-
"""吞吐量基准：验证 README 里的「请求/秒」是可以复现的，而不是一次性的口头数字。

用法：
    python scripts/benchmark_throughput.py                 # 默认：16 并发跑 30 秒
    python scripts/benchmark_throughput.py -c 32 -n 800
    python scripts/benchmark_throughput.py --mode cold     # 全部冷查询（无缓存收益）

关键，别踩：
    **每个请求必须给独立的 IP / 用户 ID**。否则所有请求落进同一个限流桶，
    绝大多数会直接返回限流话术（压根不跑检索），测出来的 QPS 高得毫无意义 ——
    那测的是「拒绝一个请求有多快」，不是系统吞吐。这一点已经坑过一次，
    详见 README「三个必须说清楚的点」。
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import FaqBot, answer_cache_stats, clear_answer_cache  # noqa: E402


def build_pool(n: int, mode: str) -> list[str]:
    cases = json.load(open(ROOT / "tests" / "test_set.json", encoding="utf-8"))["cases"]
    qs = [c["query"] for c in cases if c.get("expected_tag")]
    if mode == "cacheable":
        # 反复问同一小撮高频问题 —— 模拟真实场景里"热问法"占大头的情况
        return [qs[i % 8] for i in range(n)]
    return [qs[i % len(qs)] for i in range(n)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--concurrency", type=int, default=16)
    ap.add_argument("-n", "--requests", type=int, default=600)
    ap.add_argument("--mode", choices=["cacheable", "cold"], default="cacheable")
    args = ap.parse_args()

    bot = FaqBot()
    bot.ask("预热")
    clear_answer_cache()

    pool = build_pool(args.requests, args.mode)
    lock = threading.Lock()
    done = {"n": 0}
    t0 = time.perf_counter()

    def one(i: int) -> None:
        # 独立身份：不然会被限流桶挡掉，测到的是"拒绝速度"而非吞吐
        bot.ask(pool[i], user_id=f"tp-{i}",
                client_ip=f"10.{100 + i // 65536}.{(i // 256) % 256}.{i % 256 + 1}")
        with lock:
            done["n"] += 1

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        list(ex.map(one, range(args.requests)))

    elapsed = time.perf_counter() - t0
    qps = done["n"] / elapsed if elapsed else 0.0
    st = answer_cache_stats()

    print(f"模式 {args.mode} · 并发 {args.concurrency} · {done['n']} 个请求")
    print(f"  耗时      {elapsed:7.2f} s")
    print(f"  吞吐      {qps:7.1f} 请求/秒")
    print(f"  缓存命中率 {st.get('hit_rate', 0):.1%}")


if __name__ == "__main__":
    main()
