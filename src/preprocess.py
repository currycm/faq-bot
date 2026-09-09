# -*- coding: utf-8 -*-
"""L1 文本预处理层

职责：把用户原始输入归一化成"干净的词元串"，交给向量化层。

处理的四件事：
    1. 全角 → 半角、繁体 → 简体（可选）、大写 → 小写
    2. 去除标点与空白字符
    3. 中文分词（jieba）
    4. 去停用词

注意：
    TF-IDF 方案必须先分词（否则中文一整句会被当成一个 token）；
    BERT 方案自带 WordPiece 分词器，提前用 jieba 切开反而会破坏输入，
    所以这里把每一步都做成可插拔的开关，由上层决定启用哪些。
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

import jieba

from . import config

# jieba 首次加载词典时会打印一堆 loading 日志，静音掉
jieba.setLogLevel(logging.WARNING)

# 只保留中文、英文、数字，其余（标点、表情、特殊符号）一律丢弃
_KEEP_PATTERN = re.compile(r"[^一-龥a-zA-Z0-9]+")


# ------------------------------------------------------------------ 归一化
def to_halfwidth(text: str) -> str:
    """全角字符转半角。

    全角ＡＢＣ１２３（U+FF01–U+FF5E）与半角 ABC123 在词表里是两个不同的
    token，不统一会导致"图书馆Ａ座"匹配不上"图书馆A座"。
    """
    result = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:                 # 全角空格
            result.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:     # 全角字符区间
            result.append(chr(code - 0xFEE0))
        else:
            result.append(ch)
    return "".join(result)


def normalize(text: str) -> str:
    """统一字符形态：全角转半角、英文转小写、去掉标点与多余空白。"""
    text = to_halfwidth(text or "")
    text = text.lower()
    text = _KEEP_PATTERN.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


# ------------------------------------------------------------------ 停用词
@lru_cache(maxsize=1)
def load_stopwords(path: str | Path | None = None) -> frozenset[str]:
    """加载停用词表，结果缓存，避免每次请求都读文件。"""
    path = Path(path) if path else config.STOPWORDS_PATH
    if not path.exists():
        return frozenset()
    words = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            w = line.strip()
            if w and not w.startswith("#"):   # 支持 # 注释行
                words.add(w)
    return frozenset(words)


# ------------------------------------------------------------------ 分词
def tokenize(text: str, remove_stopwords: bool | None = None) -> list[str]:
    """分词 → 词元列表。"""
    if remove_stopwords is None:
        remove_stopwords = config.REMOVE_STOPWORDS

    text = normalize(text)
    if not text:
        return []

    tokens = jieba.lcut(text)

    if remove_stopwords:
        stop = load_stopwords()
        tokens = [t for t in tokens if t.strip() and t not in stop]
    else:
        tokens = [t for t in tokens if t.strip()]
    return tokens


def cut(text: str, remove_stopwords: bool | None = None) -> str:
    """分词并以空格拼接 —— TF-IDF 方案的直接输入格式。

    TfidfVectorizer 默认按空白切分，所以先分好词再用空格连起来，
    等价于"手动指定 token 边界"。
    """
    return " ".join(tokenize(text, remove_stopwords))


def add_words(words) -> None:
    """向分词器添加领域自定义词，防止专业名词被切碎。"""
    if isinstance(words, str):
        words = [words]
    for w in words:
        jieba.add_word(w)


def register_custom_words() -> None:
    """注册 config.CUSTOM_WORDS 中的所有领域词。项目启动时调用一次。"""
    add_words(config.CUSTOM_WORDS)
