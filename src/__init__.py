# -*- coding: utf-8 -*-
"""FAQ 问答机器人 —— 分层实现

    L1 preprocess  文本预处理（分词 / 去停用词 / 归一化）
    L2 vectorizer  向量化（TF-IDF / BERT，同一接口可插拔）
    L3 retriever   召回（余弦相似度 Top-K）
    L4 ranker      精排（v1 占位，v2 启用 Cross-Encoder）
    L5 agent       主编排 + 阈值判定 + 兜底
    L6 入口        src.agent 命令行 / app.py 网页
    L7 logger      日志采集与未命中问题反馈
"""

__version__ = "1.0.0"
