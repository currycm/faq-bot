# -*- coding: utf-8 -*-
"""L3 召回层

职责：拿用户问题向量，与索引矩阵算余弦相似度，返回 Top-K 候选。

v1 用全量暴力计算（numpy / scipy 稀疏矩阵运算）。
500 条语料下耗时约 1~5 ms —— 这个阶段**不要引入 Faiss**，
过早优化只会增加调试成本，对几百条语料零收益。

什么时候才需要换：
    < 1 万条     暴力余弦（本项目）
    1 万~100 万  稀疏优化 / sklearn NearestNeighbors
    > 100 万     ANN 索引（Faiss / Milvus）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from . import preprocess


@dataclass
class Hit:
    """一条召回结果。"""
    index: int        # 在展平语料中的下标
    question: str     # 命中的预设问法（原始文本，用于展示）
    answer: str       # 对应答案
    tag: str          # 意图标签
    score: float      # 余弦相似度
    # 精排分（sigmoid 后 0~1）。仅 ENABLE_RERANK=True 时由 ranker 填写；
    # 与 score 不同量纲，命中判定走 config.RERANK_THRESHOLD（见 ranker.py）
    rerank_score: float | None = None


class Retriever:
    """索引 + 检索。构造时建索引（离线），search 时可反复调用（在线）。

    !! 关键设计：预处理统一由本类调用，上层传原始文本即可。
    曾经踩过的坑：索引用未分词的原始句子、查询用分词后的句子，
    两边词汇表完全对不上，相似度恒为 0，而且不报任何错。
    把预处理内聚在这里，调用方就不可能漏掉。
    """

    def __init__(
        self,
        vectorizer,
        records: list[dict],
        text_fn: Callable[[str], str] | None = None,
    ):
        """
        :param vectorizer: 已 fit 的向量化器
        :param records: 展平后的语料，每条形如
                        {"question": str, "answer": str, "tag": str}
        :param text_fn: 文本 → 向量化器输入格式 的处理函数，默认 preprocess.cut
        """
        self.vectorizer = vectorizer
        self.records = records
        self.text_fn = text_fn or preprocess.cut
        # 离线构建索引矩阵：这一步只在启动时做一次
        self.matrix = vectorizer.transform([self.text_fn(r["question"]) for r in records])

    @property
    def size(self) -> int:
        return len(self.records)

    def search(self, query: str, top_k: int = 3) -> list[Hit]:
        """检索 Top-K 候选。注意这里只 transform，不 fit。"""
        if not self.records:
            return []

        q_vec = self.vectorizer.transform([self.text_fn(query)])
        sims = cosine_similarity(q_vec, self.matrix)[0]

        top_k = max(1, min(top_k, len(sims)))
        # argsort 升序，取末尾 top_k 个再倒序 → 相似度从高到低
        idx = np.argsort(sims)[-top_k:][::-1]

        return [
            Hit(
                index=int(i),
                question=self.records[i]["question"],
                answer=self.records[i]["answer"],
                tag=self.records[i]["tag"],
                score=float(sims[i]),
            )
            for i in idx
        ]
