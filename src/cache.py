# -*- coding: utf-8 -*-
"""答案缓存：归一化 query → 语料命中结果（进程内 LRU + TTL，线程安全）。

为什么需要：
    FAQ 场景的重复率极高（首页那 7 条高频问题就是证据），但每个请求都要
    重走一遍 BGE 编码 + 余弦检索。实测单进程吞吐被 GIL 压在 ~105 rps，且
    并发一高延迟就线性变差 —— 而**同样的问法反复算**是其中最没必要的一笔。
    加上这层后热问法命中即返回，CPU 开销与延迟一起降下来。

缓存什么（刻意收紧范围）：
    只缓存 **语料命中（matched=True）** 的结果 —— 它是 query 的确定性函数。
    兜底类（LLM / 天气 / 闲聊）**不缓存**，原因有二：
      · 天气有时效、LLM 文本不稳定，缓存会产出陈旧答案；
      · 兜底失败（超时 / 限流）一旦被缓存，会把**临时故障固化成长期答案**。
    兜底路径的吞吐另有预算熔断兜着（默认 500 次/小时），本来就不是并发瓶颈。

安全性（重要）：
    缓存查找发生在 **W2 安全层之后**（见 agent.FaqBot.ask 的执行顺序），
    所以限流、注入检测、PII 脱敏仍然**每个请求都执行** —— 缓存不会绕过
    任何安全策略。tests/test_cache.py 里有对应的防回归断言。

一致性：
    `FaqBot.reload()` 重载语料后会 **清空缓存**，避免返回上一版语料的答案。

约束（用的时候要知道）：
    缓存假设"答案只取决于 query"。所以**运行期动态改配置不会生效于已缓存的
    问法** —— 例如临时换掉 ranker、改 SIMILARITY_THRESHOLD / RERANK_THRESHOLD。
    生产里这些都是启动期静态值，没有影响；但**写测试时要注意**：若用例用替身
    换掉 ranker/retriever 再问同一个问题，需要先把 ANSWER_CACHE_ENABLED 关掉
    （tests/test_ranker.py 就是这么做的），或调用 reload() 清缓存。
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Optional

from .preprocess import normalize

__all__ = ["TTLCache", "build_cache_key"]


def build_cache_key(query: str) -> str:
    """归一化后的缓存键。

    复用 preprocess.normalize（全角转半角 / 转小写 / 去标点 / 折叠空白），
    与检索侧用的是同一套归一化 —— 这样"能检索到同一条答案"的几种写法
    （「图书馆几点开门？」/「图书馆几点开门」/「图书馆几点开门!」）
    会落在同一个缓存键上，不会各自占一格。
    """
    return normalize(query)


class TTLCache:
    """带 TTL 的 LRU 缓存（纯标准库，线程安全）。

    :param maxsize: 最多缓存多少条，超出按 LRU 淘汰
    :param ttl: 条目存活秒数；<=0 表示不按时间过期（只按 LRU 淘汰）
    """

    def __init__(self, maxsize: int = 512, ttl: float = 300.0):
        self.maxsize = max(1, int(maxsize))
        self.ttl = float(ttl)
        self._data: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self._misses += 1
                return None
            expire_at, value = item
            if self.ttl > 0 and expire_at < time.time():
                del self._data[key]
                self._misses += 1
                return None
            self._data.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        expire_at = time.time() + self.ttl if self.ttl > 0 else float("inf")
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (expire_at, value)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)
                self._evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._data),
                "maxsize": self.maxsize,
                "ttl": self.ttl,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate": round(self._hits / total, 4) if total else 0.0,
            }
