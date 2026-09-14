# -*- coding: utf-8 -*-
"""答案缓存与慢路径隔离测试（2026-09 抗并发改造，对应评审建议 ①②③）

钉死四个行为：
    1. 归一化 query → 命中即返回（热问法不再重算 BGE）
    2. **缓存不得绕过 W2 安全层** —— 限流仍每请求扣令牌（最关键的一条）
    3. 语料热更新（reload）后缓存必须作废，不能返回上一版答案
    4. 慢路径闸位占满时快速降级，不排队拖垮检索路径
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import agent as agent_mod  # noqa: E402
from src.agent import FaqBot  # noqa: E402
from src.cache import TTLCache, build_cache_key  # noqa: E402

Q = "图书馆几点开门"


# ==================================================== build_cache_key 归一化
def test_cache_key_merges_punctuation_variants():
    """同一问法的常见写法必须落在同一个键上，否则缓存白搭。"""
    base = build_cache_key(Q)
    for variant in (f"{Q}？", f"{Q}！", f"{Q}。", f"{Q}!!!", f" {Q} ", f"{Q} "):
        assert build_cache_key(variant) == base, variant


def test_cache_key_normalizes_fullwidth_and_case():
    assert build_cache_key("ＣＥＴ４报名") == build_cache_key("cet4报名")


def test_cache_key_keeps_different_questions_apart():
    """归一化不能"合并"语义不同的问法 —— 宁可少命中，不能答错。"""
    assert build_cache_key(Q) != build_cache_key("图书馆几点关门")
    assert build_cache_key(Q) != build_cache_key("图书馆在哪")


# ============================================================== TTLCache
def test_ttl_expiry():
    c = TTLCache(maxsize=4, ttl=0.2)
    c.set("a", 1)
    assert c.get("a") == 1
    time.sleep(0.25)
    assert c.get("a") is None


def test_lru_eviction():
    c = TTLCache(maxsize=2, ttl=0)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1        # a 变成最近使用
    c.set("c", 3)                 # 应淘汰 b
    assert c.get("a") == 1
    assert c.get("c") == 3
    assert c.get("b") is None


def test_stats_counts_hits_and_misses():
    c = TTLCache(maxsize=4, ttl=0)
    c.get("x")                    # miss
    c.set("x", 1)
    c.get("x")                    # hit
    s = c.stats()
    assert s["hits"] == 1 and s["misses"] == 1
    assert s["hit_rate"] == 0.5


def test_thread_safe_under_concurrency():
    """多线程并发读写不炸、不越界（FastAPI 线程池下必然并发）。"""
    c = TTLCache(maxsize=64, ttl=0)
    errs: list[Exception] = []

    def worker(n: int) -> None:
        try:
            for i in range(300):
                c.set(f"k{(n + i) % 128}", i)
                c.get(f"k{i % 128}")
        except Exception as exc:          # pragma: no cover
            errs.append(exc)

    ts = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errs
    assert c.stats()["size"] <= 64


# ===================================================== agent 集成（用 tfidf 提速）
@pytest.fixture
def bot():
    return FaqBot(vectorizer_type="tfidf")


def test_repeat_query_hits_cache(bot, monkeypatch):
    monkeypatch.setattr(agent_mod.config, "ANSWER_CACHE_ENABLED", True)
    agent_mod._answer_cache.clear()

    r1 = bot.ask(Q, user_id="c1", client_ip="10.11.1.1", trace_id="t1")
    r2 = bot.ask(Q, user_id="c2", client_ip="10.11.1.2", trace_id="t2")

    assert r1["matched"], "语料里应能命中"
    assert r1["cache_hit"] is False
    assert r2["cache_hit"] is True, "第二次同样问法应走缓存"
    assert r1["answer"] == r2["answer"]
    assert r1["tag"] == r2["tag"]
    # 每请求字段仍必须是本次请求的，不能被缓存带出来
    assert r2["user_id"] == "c2"
    assert r2["trace_id"] == "t2"


def test_cache_never_bypasses_rate_limit(bot, monkeypatch):
    """最关键的一条：缓存查找必须在 enforce_security 之后。

    否则同样的问法反复发就能白嫖 —— 限流形同虚设。
    """
    monkeypatch.setattr(agent_mod.config, "ANSWER_CACHE_ENABLED", True)
    agent_mod._answer_cache.clear()

    ip = "10.77.77.77"                    # 独立 IP，避免与其他用例互扰
    cap = agent_mod.config.RATE_LIMIT_IP_CAPACITY
    hits = [bot.ask(Q, user_id=f"rl-{i}", client_ip=ip)["matched"]
            for i in range(cap)]
    assert all(hits), "额度内应全部命中（说明缓存没把请求提前短路掉）"

    blocked = bot.ask(Q, user_id="rl-over", client_ip=ip)
    assert not blocked["matched"], "超额度后必须被限流拦住"
    assert blocked["fallback"]["type"] == "security"


def test_cache_disabled_still_works(bot, monkeypatch):
    monkeypatch.setattr(agent_mod.config, "ANSWER_CACHE_ENABLED", False)
    agent_mod._answer_cache.clear()
    r = bot.ask(Q, user_id="d1", client_ip="10.12.1.1")
    assert r["matched"] and r["cache_hit"] is False
    assert agent_mod._answer_cache.stats()["size"] == 0


def test_reload_invalidates_cache(bot, monkeypatch):
    """语料换版后必须清缓存，否则会继续返回旧答案。"""
    monkeypatch.setattr(agent_mod.config, "ANSWER_CACHE_ENABLED", True)
    agent_mod._answer_cache.clear()
    bot.ask(Q, user_id="re1", client_ip="10.13.1.1")
    assert agent_mod._answer_cache.stats()["size"] >= 1

    bot.reload()
    assert agent_mod._answer_cache.stats()["size"] == 0, "reload 后缓存应被清空"


def test_slow_path_gate_degrades_fast(bot):
    """闸位满 → 立刻返回固定兜底，而不是排队等 LLM（保护检索路径）。"""
    gate = agent_mod._slow_path_gate
    n = agent_mod.config.SLOW_PATH_MAX_CONCURRENCY
    for _ in range(n):
        assert gate.acquire(blocking=False)
    try:
        r = bot.ask("如何评价三体这部小说", user_id="g1", client_ip="10.14.1.1")
        assert r["fallback"] is not None
        assert r["fallback"]["type"] == "overload"
        assert r["answer"] == agent_mod.config.FALLBACK_TEXT
    finally:
        for _ in range(n):
            gate.release()
