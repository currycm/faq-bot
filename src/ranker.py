# -*- coding: utf-8 -*-
"""L4 排序层（v1 占位）

召回层用的是"双塔"结构：问题与候选问题各自独立编码，再比对向量。
优点是快（候选向量可以预先算好），缺点是两者之间没有交互，精度有限。

排序层引入 Cross-Encoder：把"用户问题 + 候选问题"拼成一句话喂给 BERT，
让模型充分交互后打分。

    召回（Bi-Encoder）：   快，粗排，从 1000 条里筛出 20 条
    排序（Cross-Encoder）：慢，精排，从 20 条里挑出最优 1 条

这是工业级检索系统的标准两段式设计。

v1 阶段这里只做直通（pass-through），等召回率遇到瓶颈再补实现。
补的时候上层 agent.py 一行都不用改 —— 因为接口已经定好了。
"""
from __future__ import annotations

from . import config
from .retriever import Hit


class BaseRanker:
    """排序器接口：输入候选列表，输出重排后的候选列表。"""

    name = "base"

    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        raise NotImplementedError


class PassThroughRanker(BaseRanker):
    """v1 默认实现：不做任何重排，直接返回召回顺序。"""

    name = "none"

    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        return hits


class CrossEncoderRanker(BaseRanker):
    """v2 实现：BERT Cross-Encoder 精排。

    启用方式：
        pip install torch transformers sentence-transformers
        把 config.ENABLE_RERANK 改成 True

    示意图：
        input  = "[CLS] 用户问题 [SEP] 候选问题 [SEP]"
        output = 一个 0~1 的相关性分数
    """

    name = "cross-encoder"

    def __init__(self, model_name: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"):
        self.model_name = model_name
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise ImportError(
                "使用精排需要安装：pip install sentence-transformers torch"
            ) from exc
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        if not hits:
            return hits
        pairs = [[query, h.question] for h in hits]
        scores = self.model.predict(pairs)
        for hit, s in zip(hits, scores):
            hit.score = float(s)
        return sorted(hits, key=lambda h: h.score, reverse=True)


def build_ranker(enable: bool | None = None) -> BaseRanker:
    """按配置创建排序器。"""
    enable = config.ENABLE_RERANK if enable is None else enable
    if not enable:
        return PassThroughRanker()
    return CrossEncoderRanker()
