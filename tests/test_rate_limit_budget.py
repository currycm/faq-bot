# -*- coding: utf-8 -*-
"""W2 限流 / 预算熔断单元测试"""
from __future__ import annotations

import time

import pytest

from src.security.rate_limit import RateLimiter, check_rate_limit, reset_all
from src.security.budget import (
    BudgetGuard, get_budget, check_budget, record_llm_call, reset_budget,
)


# ============================================================ rate_limit
class TestRateLimiter:
    def test_initial_allow(self):
        """新 key：桶满，能通过。"""
        rl = RateLimiter(capacity=3, refill_rate=0.1)
        assert rl.allow("ip:1.2.3.4")
        assert rl.allow("ip:1.2.3.4")
        assert rl.allow("ip:1.2.3.4")
        # 第 4 次该被拒
        assert not rl.allow("ip:1.2.3.4")

    def test_different_keys_independent(self):
        rl = RateLimiter(capacity=2, refill_rate=0.001)
        assert rl.allow("a")
        assert rl.allow("a")
        assert not rl.allow("a")
        # b 不受 a 影响
        assert rl.allow("b")
        assert rl.allow("b")

    def test_refill(self):
        """令牌会随时间补充。"""
        rl = RateLimiter(capacity=1, refill_rate=10.0)  # 10 个/秒
        assert rl.allow("x")
        assert not rl.allow("x")
        # 等 0.15s → 至少补 1 个令牌（10 * 0.15 = 1.5）
        time.sleep(0.15)
        assert rl.allow("x")

    def test_empty_key_passthrough(self):
        rl = RateLimiter(capacity=1, refill_rate=0.001)
        # 空 key / None → 放行（不影响正常流量）
        assert rl.allow("")
        assert rl.allow(None)
        assert rl.allow("")
        assert rl.allow("")

    def test_stats(self):
        rl = RateLimiter(capacity=5, refill_rate=1.0, name="test")
        rl.allow("a")
        rl.allow("b")
        s = rl.stats()
        assert s["name"] == "test"
        assert s["capacity"] == 5
        assert s["tracked_keys"] == 2

    def test_reset(self):
        rl = RateLimiter(capacity=1, refill_rate=0.001)
        rl.allow("k")
        assert not rl.allow("k")
        rl.reset("k")
        assert rl.allow("k")  # 重置后又能过

    def test_reset_all(self):
        rl = RateLimiter(capacity=1, refill_rate=0.001)
        rl.allow("a")
        rl.allow("b")
        rl.reset()
        s = rl.stats()
        assert s["tracked_keys"] == 0


class TestCheckRateLimit:
    def setup_method(self):
        reset_all()

    def test_ip_only(self):
        # IP 桶默认 30 个
        for _ in range(30):
            ok, reason = check_rate_limit("1.1.1.1", None)
            assert ok
        ok, reason = check_rate_limit("1.1.1.1", None)
        assert not ok
        assert "IP" in reason

    def test_user_only(self):
        for _ in range(60):
            ok, reason = check_rate_limit(None, "user_a")
            assert ok
        ok, reason = check_rate_limit(None, "user_a")
        assert not ok
        assert "用户" in reason

    def test_both_pass(self):
        ok, _ = check_rate_limit("2.2.2.2", "user_b")
        assert ok

    def test_neither_pass(self):
        ok, _ = check_rate_limit(None, None)
        assert ok  # 都未识别，放行


# ============================================================ budget
class TestBudgetGuard:
    def test_initial_allow(self):
        bg = BudgetGuard(window_sec=60, max_calls=3, max_cost_cny=1.0)
        for _ in range(3):
            ok, reason = bg.check()
            assert ok, reason
            bg.record()
        ok, reason = bg.check()
        assert not ok
        assert "调用次数熔断" in reason

    def test_cost_limit(self):
        # max_cost=0.05, avg_cost=0.02 → 累计 3 次后估算 0.06 超 0.05
        bg = BudgetGuard(window_sec=60, max_calls=1000, max_cost_cny=0.05,
                        avg_cost_per_call=0.02)
        for _ in range(2):
            ok, _ = bg.check()
            assert ok
            bg.record()
        ok, reason = bg.check()
        assert not ok
        assert "成本熔断" in reason

    def test_record_makes_check_stricter(self):
        """record 后下次 check 会被算入。"""
        bg = BudgetGuard(window_sec=60, max_calls=2, max_cost_cny=100.0)
        assert bg.check()[0]
        bg.record()
        assert bg.check()[0]
        bg.record()
        ok, _ = bg.check()
        assert not ok

    def test_sliding_window_expires(self):
        """滑动窗口：旧记录会滑出。"""
        bg = BudgetGuard(window_sec=0.2, max_calls=2, max_cost_cny=100.0)
        bg.record()
        bg.record()
        assert not bg.check()[0]
        time.sleep(0.3)
        assert bg.check()[0]

    def test_stats(self):
        bg = BudgetGuard(window_sec=60, max_calls=5, max_cost_cny=1.0, name="t")
        bg.record()
        s = bg.stats()
        assert s["name"] == "t"
        assert s["calls_in_window"] == 1
        assert s["max_calls"] == 5
        assert s["is_open"] is False

    def test_never_raises(self):
        """即使数据极端也不该抛。"""
        bg = BudgetGuard(window_sec=60, max_calls=1, max_cost_cny=0.01,
                        avg_cost_per_call=100.0)
        ok, _ = bg.check()
        assert isinstance(ok, bool)


class TestGlobalBudget:
    def setup_method(self):
        reset_budget()

    def test_singleton(self):
        a = get_budget()
        b = get_budget()
        assert a is b

    def test_check_budget_default(self):
        ok, reason = check_budget()
        assert ok, reason

    def test_record_increments(self):
        bg = get_budget()
        before = bg.stats()["calls_in_window"]
        record_llm_call()
        after = bg.stats()["calls_in_window"]
        assert after == before + 1
