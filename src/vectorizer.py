# -*- coding: utf-8 -*-
"""L2 向量化层

职责：把文本变成向量。这是整个架构中**唯一必须抽象成接口**的模块，
因为它是从 v1（TF-IDF）升级到 v2（BERT）、v3（BGE）的切入点。

接口契约（两种实现都必须遵守）：
    fit(corpus: list[str]) -> None        离线调用，只调一次
    transform(texts: list[str]) -> matrix 在线调用，每次请求都调

!! 铁律：在线链路只能 transform，绝不能 fit。
   一旦在线上重新 fit，词表和 IDF 权重会随单条输入改变，
   造成索引矩阵与查询向量不在同一个空间里 —— 表现是"同一个问题
   问两次，结果不一样"，而且极难排查。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from . import config


class BaseVectorizer(ABC):
    """向量化器抽象基类。上层召回代码只依赖这个接口。"""

    #: 供日志/评估打印，便于确认当前跑的是哪套方案
    name = "base"

    @abstractmethod
    def fit(self, corpus: list[str]) -> None:
        """离线：用语料库拟合词表 / 加载预训练权重。"""

    @abstractmethod
    def transform(self, texts: list[str]):
        """在线：把一批文本转成向量矩阵，shape = (n, dim)。"""

    @property
    def dim(self) -> int:
        return 0


# ------------------------------------------------------------------ v1: TF-IDF
class TfidfVectorizerImpl(BaseVectorizer):
    """TF-IDF 实现。

    优点：零依赖、毫秒级 fit、每个维度对应一个真实词汇（可解释）；
    缺点：只认词面重叠，"怎么挂失" 和 "校园卡遗失" 相似度是 0。
    """

    name = "tfidf"

    def __init__(self, token_pattern: str = r"(?u)\b\w+\b"):
        # 输入已经是"空格分词后的字符串"，所以词表按 \w+ 切即可
        self.vec = TfidfVectorizer(token_pattern=token_pattern)
        self._fitted = False
        self.matrix = None

    def fit(self, corpus: list[str]) -> None:
        self.matrix = self.vec.fit_transform(corpus)
        self._fitted = True

    def transform(self, texts: list[str]):
        if not self._fitted:
            raise RuntimeError(
                "TfidfVectorizerImpl 尚未 fit。请先调用 fit(corpus) 构建索引，"
                "在线问答阶段只能调用 transform。"
            )
        return self.vec.transform(texts)

    @property
    def dim(self) -> int:
        return len(self.vec.vocabulary_) if self._fitted else 0


# ------------------------------------------------------------------ v2: BERT
class BertVectorizerImpl(BaseVectorizer):
    """BERT 句向量实现（v2 阶段启用，CPU 较慢，400MB+）。

    延迟导入 torch / transformers：没装这两个包时，项目其余部分照常可用，
    只有真正把 VECTORIZER_TYPE 改成 "bert" 才需要安装。
    """

    name = "bert"

    def __init__(self, model_name: str | None = None, device: str | None = None):
        self.model_name = model_name or config.BERT_MODEL_NAME
        self.device = device or config.BERT_DEVICE
        self.tokenizer = None
        self.model = None
        self._fitted = False

    def fit(self, corpus: list[str]) -> None:
        """加载预训练权重。语料本身不参与训练，这里只做初始化 + 预热。"""
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except ImportError as exc:
            raise ImportError(
                "使用 BERT 向量化需要安装：pip install torch transformers\n"
                "（torch 建议从 https://pytorch.org 选择对应 CUDA 版本安装）"
            ) from exc

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self.model = AutoModel.from_pretrained(self.model_name).to(self.device)
        self.model.eval()                      # 关掉 dropout，保证结果稳定
        self._torch = torch
        self._fitted = True

        # 预热一次，避免首次请求把模型编译的耗时算进延迟
        self.transform(corpus[0:1] if corpus else ["预热"])

    def transform(self, texts: list[str]) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("BertVectorizerImpl 尚未 fit，请先调用 fit() 加载模型。")

        torch = self._torch
        encoded = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=config.BERT_MAX_LENGTH,
            return_tensors="pt",
        ).to(self.device)

        with torch.no_grad():
            output = self.model(**encoded).last_hidden_state

        # mean pooling：对非 padding 位置取平均，得到句向量
        mask = encoded["attention_mask"].unsqueeze(-1).float()
        pooled = (output * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
        return pooled.cpu().numpy()

    @property
    def dim(self) -> int:
        return self.model.config.hidden_size if self._fitted else 0


# ------------------------------------------------------------------ v3: BGE
class BgeVectorizerImpl(BaseVectorizer):
    """BGE 句向量实现（v3 推荐，CPU 友好）。

    加载方式：sentence-transformers（BGE 模型官方推荐方式）。
    归一化：默认对输出做 L2 normalize，让余弦相似度等价于点积。
    短文本优化：sentence-transformers 库会自动给短 query 加 BGE 的检索前缀，
                无需手动拼 prompt。

    安装：
        pip install sentence-transformers
    模型首次加载会从 HF Hub 下载 ~93MB（BGE-small-zh-v1.5）到本地缓存目录，
    之后离线可用。
    """

    name = "bge"

    def __init__(self, model_name: str | None = None, device: str | None = None):
        self.model_name = model_name or config.BGE_MODEL_NAME
        self.device = device or config.BGE_DEVICE
        self.model = None
        self._fitted = False

    def fit(self, corpus: list[str]) -> None:
        """加载 BGE 模型。语料不参与训练，仅做预热。

        网络配置（镜像 / 离线模式）在 src.config 里 import 阶段已设置好，
        这里只负责加载。
        """
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "使用 BGE 向量化需要安装：pip install sentence-transformers\n"
                "（sentence-transformers 会自动安装 torch CPU 版本）"
            ) from exc

        # trust_remote_code=False：BGE-small-zh-v1.5 是官方模型，无需自定义代码
        self.model = SentenceTransformer(self.model_name, device=self.device)
        self.model.eval() if hasattr(self.model, "eval") else None

        self._fitted = True
        # 预热一次，避免首次请求把模型编译耗时算进延迟
        self.transform(corpus[0:1] if corpus else ["预热"])
        print(f"[vectorizer:bge] 模型加载完成：{self.model_name} "
              f"dim={self.dim} device={self.device}")

    def transform(self, texts: list[str]) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("BgeVectorizerImpl 尚未 fit，请先调用 fit() 加载模型。")

        # sentence-transformers 的 encode 已内置：
        #   - tokenizer + 前向推理
        #   - BGE 官方推荐的 pooling（CLS + 归一化）
        #   - batch / progress_bar 开关
        vec = self.model.encode(
            texts,
            batch_size=config.BGE_BATCH_SIZE,
            normalize_embeddings=config.BGE_NORMALIZE,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return vec

    @property
    def dim(self) -> int:
        # sentence-transformers 6.x 把方法重命名了，兼容老版本
        if not self._fitted:
            return 0
        getter = getattr(self.model, "get_embedding_dimension",
                         None) or getattr(self.model, "get_sentence_embedding_dimension")
        return getter()


# ------------------------------------------------------------------ 工厂
def build_vectorizer(vectorizer_type: str | None = None) -> BaseVectorizer:
    """按配置创建向量化器。新增方案时只需要在这里加一个分支。"""
    vtype = (vectorizer_type or config.VECTORIZER_TYPE).lower()
    if vtype == "tfidf":
        return TfidfVectorizerImpl()
    if vtype == "bert":
        return BertVectorizerImpl()
    if vtype == "bge":
        return BgeVectorizerImpl()
    raise ValueError(f"不支持的向量化方案：{vtype}（可选 tfidf / bert / bge）")
