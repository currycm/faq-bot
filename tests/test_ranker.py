# -*- coding: utf-8 -*-
"""精排层测试（不联网：模型用替身；重点验证分数解耦与加载失败降级）

2026-09 精排修复的三个关键行为，这里全部钉死：
    1. rerank 只填 hit.rerank_score，绝不覆盖余弦分 hit.score
    2. 命中判定走 RERANK_THRESHOLD（独立量纲），余弦阈值不再掺和
    3. 精排模型加载失败 → 降级为直通，启动绝不崩
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.agent import FaqBot  # noqa: E402
from src.ranker import CrossEncoderRanker, PassThroughRanker, build_ranker  # noqa: E402
from src.retriever import Hit  # noqa: E402


def _hit(question: str, score: float) -> Hit:
    return Hit(question=question, answer="a", tag="t", score=score)


class _FakeModel:
    """替身模型：候选问题里带的关键字 → 固定精排分。"""

    def __init__(self, scores: dict):
        self.scores = scores

    def predict(self, pairs):
        return [next((v for k, v in self.scores.items() if k in q), 0.0) for _query, q in pairs]


class _FakeRanker:
    """把 top1 的精排分钉成固定值，验证 agent 命中判定走 RERANK_THRESHOLD。"""

    name = "fake"

    def __init__(self, score: float):
        self.score = score

    def rerank(self, query, hits):
        if hits:
            hits[0].rerank_score = self.score
        return hits


def test_rerank_keeps_cosine_and_sets_rerank_score():
    r = object.__new__(CrossEncoderRanker)  # 绕过 __init__，不加载真模型
    r.model_name = "fake"
    r.model = _FakeModel({"b": 0.9, "a": 0.1})
    hits = [_hit("a", 0.80), _hit("b", 0.70)]
    out = r.rerank("q", hits)
    assert [h.question for h in out] == ["b", "a"]  # 按精排分重排
    assert out[0].score == 0.70  # !! 余弦分不被覆盖
    assert out[0].rerank_score == pytest.approx(0.9)


def test_passthrough_leaves_rerank_score_none():
    out = PassThroughRanker().rerank("q", [_hit("a", 0.80)])
    assert out[0].rerank_score is None


def test_build_ranker_disabled(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_RERANK", False)
    assert isinstance(build_ranker(), PassThroughRanker)


def test_build_ranker_load_failure_falls_back(monkeypatch, capsys):
    """精排模型加载失败 → 降级为直通，绝不让启动崩掉。"""
    monkeypatch.setattr(config, "ENABLE_RERANK", True)

    def _boom(*a, **k):
        raise RuntimeError("model download failed")

    monkeypatch.setattr("src.ranker.CrossEncoderRanker", _boom)
    r = build_ranker()
    assert isinstance(r, PassThroughRanker)
    assert "降级" in capsys.readouterr().err


@pytest.fixture
def tfidf_bot():
    return FaqBot(vectorizer_type="tfidf")


@pytest.fixture(autouse=True)
def _no_answer_cache(monkeypatch):
    """本模块用替身换掉 ranker，需要每次 ask 都真的跑一遍检索 + 精排。

    答案缓存（src/cache.py）按归一化 query 命中，第二次同样问法会**直接返回
    上次结果、跳过 ranker** —— 那样这个用例就测不到精排阈值了。
    所以这里显式关掉缓存，把关注点隔离干净。
    （等价约束：运行期替换 ranker / 改阈值不会反映到已缓存的问法上；
      生产里这些是启动期静态配置，且 reload() 会清缓存。）
    """
    monkeypatch.setattr(config, "ANSWER_CACHE_ENABLED", False)


def test_agent_matching_uses_rerank_threshold(tfidf_bot, monkeypatch):
    """精排分高 → 命中；精排分低但余弦分很高 → 仍拒答（量纲已解耦）。"""
    monkeypatch.setattr(config, "RERANK_THRESHOLD", 0.8)

    tfidf_bot.ranker = _FakeRanker(0.9)
    r = tfidf_bot.ask("图书馆几点开门", client_ip="10.9.0.1")
    assert r["matched"] is True
    assert r["rerank_score"] == pytest.approx(0.9)
    assert r["candidates"][0]["rerank_score"] == pytest.approx(0.9)

    tfidf_bot.ranker = _FakeRanker(0.3)
    r2 = tfidf_bot.ask("图书馆几点开门", client_ip="10.9.0.2")
    assert r2["matched"] is False  # 余弦分再高也拦得住
    assert r2["score"] >= 0.5  # score 仍是余弦相似度
    assert r2["rerank_score"] == pytest.approx(0.3)
