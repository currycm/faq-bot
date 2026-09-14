# -*- coding: utf-8 -*-
"""L4 排序层

召回层用的是"双塔"结构：问题与候选问题各自独立编码，再比对向量。
优点是快（候选向量可以预先算好），缺点是两者之间没有交互，精度有限。

排序层引入 Cross-Encoder：把"用户问题 + 候选问题"拼成一句话喂给模型，
让两段文本充分交互后打分。

    召回（Bi-Encoder）：   快，粗排，从 1000 条里筛出 20 条
    排序（Cross-Encoder）：慢，精排，从 20 条里挑出最优 1 条

这是工业级检索系统的标准两段式设计。

v1 直通（pass-through）；精排实现见 CrossEncoderRanker（默认关闭）。

【2026-09 修复：精排分数与余弦分数解耦】
    旧实现把 cross-encoder 分数直接覆盖 hit.score —— 而上层 agent 的
    命中判定拿的是余弦阈值（SIMILARITY_THRESHOLD=0.60），两种分数完全
    不同量纲，启用精排等于拿 0.60 去比一个不相干的分数。现在：
      - hit.score        保留余弦相似度（对外展示 / evaluate 兼容）
      - hit.rerank_score 存精排分（sigmoid 后 0~1）
      - agent 命中判定：有 rerank_score → 比 config.RERANK_THRESHOLD；
        没有 → 比 config.SIMILARITY_THRESHOLD（与旧行为一致）
    !! 打开 ENABLE_RERANK 前必须用 python evaluate.py --scan 重新标定
       RERANK_THRESHOLD（config 里的 0.5 只是占位）。
"""
from __future__ import annotations

import sys

from . import config
from .retriever import Hit


class BaseRanker:
    """排序器接口：输入候选列表，输出重排后的候选列表。"""

    name = "base"
    # True 表示 rerank 会产出 rerank_score，agent 据此切换命中阈值
    has_rerank = False

    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        raise NotImplementedError


class PassThroughRanker(BaseRanker):
    """默认实现：不做任何重排，直接返回召回顺序。"""

    name = "none"

    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        return hits


class CrossEncoderRanker(BaseRanker):
    """Cross-Encoder 精排。

    启用方式：
        1. 确认 sentence-transformers + torch 已装（requirements.txt 有注释）
        2. config.ENABLE_RERANK = True（首次会下载 RERANK_MODEL_NAME，约 1.1GB）
        3. 用 evaluate.py --scan 标定 config.RERANK_THRESHOLD
    """

    name = "cross-encoder"
    has_rerank = True

    def __init__(self, model_name: str | None = None):
        # 2026-09 修复：默认模型从英文的 cross-encoder/mmarco-mMiniLMv2
        # 换成中文可用的 BAAI/bge-reranker-base —— 旧模型对中文 query
        # 和候选基本打不出区分度。
        self.model_name = model_name or config.RERANK_MODEL_NAME
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise ImportError(
                "使用精排需要安装：pip install sentence-transformers torch"
            ) from exc
        try:
            # 显式 sigmoid：分数落在 0~1，RERANK_THRESHOLD 才有稳定语义
            from torch import nn
            self.model = CrossEncoder(self.model_name, activation_fn=nn.Sigmoid())
        except TypeError:
            # 个别 sentence-transformers 版本签名不同 → 退回默认加载
            self.model = CrossEncoder(self.model_name)

    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        if not hits:
            return hits
        pairs = [[query, h.question] for h in hits]
        scores = self.model.predict(pairs)
        for hit, s in zip(hits, scores):
            hit.rerank_score = float(s)
        # 主序按精排分；同分时余弦分高者优先（保留召回层信息）
        return sorted(hits, key=lambda h: (h.rerank_score, h.score), reverse=True)


def build_ranker(enable: bool | None = None) -> BaseRanker:
    """按配置创建排序器。

    精排模型加载失败（离线 / 下载中断 / 显存不足）时不让启动崩掉：
    降级为直通，行为等价于 ENABLE_RERANK=False，只在 stderr 提醒。
    """
    enable = config.ENABLE_RERANK if enable is None else enable
    if not enable:
        return PassThroughRanker()
    try:
        return CrossEncoderRanker()
    except Exception as exc:
        print(f"[ranker] ⚠️ 精排模型加载失败，降级为直通（不重排）：{exc}",
              file=sys.stderr)
        return PassThroughRanker()
