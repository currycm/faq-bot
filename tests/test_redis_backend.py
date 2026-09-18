# -*- coding: utf-8 -*-
"""Redis 分布式限流 / 预算后端测试（FakeRedis，不需要真实 Redis）

FakeRedis 只实现被用到的命令。令牌桶 Lua 在 fake 里用同逻辑的 Python
实现代替 —— 本文件验证的是包装层（键名 / 参数 / 降级行为 / 预算窗口）；
Lua 脚本本身的语义应在真实 Redis 上联调确认（见 redis_backend.py 模块注释）。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.security import budget as budget_mod  # noqa: E402
from src.security import rate_limit as rl_mod  # noqa: E402
from src.security import redis_backend  # noqa: E402
from src.security.redis_backend import RedisBudgetGuard, RedisRateLimiter  # noqa: E402


class FakePipeline:
    def __init__(self, parent):
        self.parent = parent
        self.ops = []

    def zremrangebyscore(self, key, lo, hi):
        self.ops.append(("zrem", key, lo, hi))
        return self

    def zcard(self, key):
        self.ops.append(("zcard", key))
        return self

    def zrange(self, key, start, end):
        self.ops.append(("zrange", key))
        return self

    def zadd(self, key, mapping):
        self.ops.append(("zadd", key, mapping))
        return self

    def pexpire(self, key, ms):
        self.ops.append(("pexpire", key, ms))
        return self

    def execute(self):
        if self.parent.fail:
            raise ConnectionError("redis down")
        out = [self.parent._apply(*op) for op in self.ops]
        self.ops = []
        return out


class FakeRedis:
    """最小 Redis 替身：hash（令牌桶）/ zset（预算窗口）。"""

    def __init__(self, fail: bool = False):
        self.hashes = {}
        self.zsets = {}
        self.fail = fail
        self.now = 1_000_000.0

    # ---- 令牌桶脚本 ----
    def register_script(self, script):
        def run(keys=None, args=None):
            return self.eval(script, len(keys or []), *(keys or []), *(args or []))
        return run

    def eval(self, script, numkeys, *rest):
        if self.fail:
            raise ConnectionError("redis down")
        assert "HMGET" in script and "PEXPIRE" in script   # 确认是令牌桶脚本
        key = rest[0]
        capacity, refill, cost = (float(a) for a in rest[1:4])
        tokens, ts = self.hashes.get(key, (capacity, self.now))
        tokens = min(capacity, tokens + (self.now - ts) * refill)
        allowed = 1 if tokens >= cost else 0
        if allowed:
            tokens -= cost
        self.hashes[key] = (tokens, self.now)
        return [allowed, str(tokens)]

    # ---- 预算窗口 ----
    def pipeline(self):
        return FakePipeline(self)

    def _apply(self, *op):
        kind = op[0]
        if kind == "zrem":
            _, key, lo, hi = op
            z = self.zsets.setdefault(key, [])
            self.zsets[key] = [(s, m) for s, m in z if not (lo <= s <= hi)]
            return 0
        if kind == "zcard":
            return len(self.zsets.get(op[1], []))
        if kind == "zrange":
            return [m for _s, m in self.zsets.get(op[1], [])]
        if kind == "zadd":
            _, key, mapping = op
            z = self.zsets.setdefault(key, [])
            for member, score in mapping.items():
                z.append((score, member))
            return 1
        if kind == "pexpire":
            return 1
        raise AssertionError(f"unexpected op: {op}")


# ============================================================ 令牌桶
def test_token_bucket_capacity_and_deny():
    rl = RedisRateLimiter("redis://x", capacity=2, refill_rate=0.001,
                          name="ip", client=FakeRedis())
    assert rl.allow("1.2.3.4")
    assert rl.allow("1.2.3.4")
    assert not rl.allow("1.2.3.4")
    assert rl.allow("5.6.7.8")           # 不同 key 独立


def test_token_bucket_refill():
    fake = FakeRedis()
    rl = RedisRateLimiter("redis://x", capacity=1, refill_rate=10.0,
                          name="ip", client=fake)
    assert rl.allow("k")
    assert not rl.allow("k")
    fake.now += 0.2                      # 补 2 个令牌（上限 1）
    assert rl.allow("k")


def test_token_bucket_falls_back_when_redis_down():
    """Redis 挂了 → 退回进程内桶继续限流，而不是直接放行。"""
    rl = RedisRateLimiter("redis://x", capacity=2, refill_rate=0.001,
                          name="ip", client=FakeRedis(fail=True))
    assert rl.allow("k")
    assert rl.allow("k")
    assert not rl.allow("k")


# ============================================================ 预算熔断
def test_budget_trips_on_calls():
    bg = RedisBudgetGuard("redis://x", window_sec=60, max_calls=2,
                          max_cost_cny=100.0, client=FakeRedis())
    bg.record()
    bg.record()
    ok, reason = bg.check()
    assert not ok and "调用次数熔断" in reason


def test_budget_trips_on_cost():
    bg = RedisBudgetGuard("redis://x", window_sec=60, max_calls=1000,
                          max_cost_cny=0.05, avg_cost_per_call=0.02,
                          client=FakeRedis())
    bg.record()
    bg.record()
    ok, reason = bg.check()
    assert not ok and "成本熔断" in reason
    assert bg.stats()["is_open"] is True    # 成本触顶也要反映到 is_open


def test_budget_window_slides():
    bg = RedisBudgetGuard("redis://x", window_sec=0.2, max_calls=2,
                          max_cost_cny=100.0, client=FakeRedis())
    bg.record()
    bg.record()
    assert not bg.check()[0]
    time.sleep(0.3)
    assert bg.check()[0]


def test_budget_falls_back_when_redis_down():
    """Redis 挂了 → 预算退回进程内熔断器（仍熔断，不是放空）。"""
    bg = RedisBudgetGuard("redis://x", window_sec=60, max_calls=2,
                          max_cost_cny=100.0, client=FakeRedis(fail=True))
    bg.record()
    assert bg.check()[0]
    bg.record()
    ok, reason = bg.check()
    assert not ok and "调用次数熔断" in reason


# ============================================================ 配置接线
def test_config_redis_url_switches_backend(monkeypatch):
    """设了 FAQ_REDIS_URL → get_ip_limiter / get_budget 返回 Redis 版本。"""

    class _Stub:
        def __init__(self, *a, **k):
            pass

        def reset(self, *a, **k):
            pass

        def stats(self):
            return {}

    monkeypatch.setattr(redis_backend, "RedisRateLimiter", _Stub)
    monkeypatch.setattr(redis_backend, "RedisBudgetGuard", _Stub)
    monkeypatch.setattr(config, "REDIS_URL", "redis://x")
    monkeypatch.setattr(rl_mod, "_ip_limiter", None)
    monkeypatch.setattr(budget_mod, "_budget", None)

    assert isinstance(rl_mod.get_ip_limiter(), _Stub)
    assert isinstance(budget_mod.get_budget(), _Stub)
    rl_mod.reset_all()
    budget_mod.reset_budget()
