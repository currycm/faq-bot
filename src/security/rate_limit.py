# -*- coding: utf-8 -*-
"""令牌桶限流（W2 安全层 第三道防线）

目标：
    防止单个 IP / 单个用户短时间内把资源（CPU / LLM 配额 / 数据库连接）
    吃光，让正常用户也跟着受影响。

算法：
    经典令牌桶（Token Bucket）。每个 key 一个桶，桶里有 capacity 个令牌，
    每秒补充 refill_rate 个。请求来时先消耗 1 个令牌，没令牌就拒绝。

    - 桶容量 capacity 决定"突发"上限：用户瞬时可以打 capacity 个请求
    - 补充速率 refill_rate 决定"稳态"上限：长期平均每秒不超过 refill_rate

双维度：
    - IP 维度：防匿名刷接口（默认 30/分钟/ IP）
    - user_id 维度：防登录态刷接口（默认 60/分钟/用户）

    两个维度**独立计数**：IP 命中先看 IP 桶，user_id 命中看 user_id 桶，
    任一桶空都拒绝。登录用户享受更宽松的额度。

注意：
    - 进程内 in-memory 实现。多 worker 时每个 worker 独立计数，
      实际限流上限 ≈ NUM_WORKERS × 配置值。生产环境如需精确，应改 Redis。
    - 内存常驻桶表 key 数 = 唯一 IP 数 + 唯一 user_id 数。
      启动时按需懒分配，请求结束不删除（避免热点用户反复创建桶）。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class _Bucket:
    """单个令牌桶。"""
    tokens: float
    last_refill: float  # 上次补充时间（time.time()）

    def try_consume(self, cost: float, capacity: float, refill_rate: float) -> bool:
        """尝试消耗 cost 个，返回 True 表示成功。"""
        now = time.time()
        elapsed = now - self.last_refill
        # 补充令牌（按时间比例）
        self.tokens = min(capacity, self.tokens + elapsed * refill_rate)
        self.last_refill = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


class RateLimiter:
    """进程级令牌桶限流器。

    用法：
        limiter = RateLimiter(capacity=30, refill_rate=0.5)   # 30 个桶，0.5 个/秒
        if not limiter.allow("1.2.3.4"):
            return JSONResponse(429, ...)
    """

    def __init__(self, capacity: int = 30, refill_rate: float = 0.5,
                 name: str = "default"):
        """构造限流器。

        :param capacity:   桶容量（突发上限）
        :param refill_rate: 每秒补充令牌数（稳态速率 = 1/refill_rate 秒一次）
        :param name:       限流器名（用于日志区分维度）
        """
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self.name = name
        self._buckets: Dict[str, _Bucket] = {}
        self._lock = threading.Lock()  # 进程内并发安全

    def allow(self, key: Optional[str], cost: float = 1.0) -> bool:
        """检查 key 是否能通过。

        :param key:  维度标识（IP / user_id）。None 或空串视为放行（未识别）。
        :param cost: 本次消耗的令牌数（默认 1）。
        :return:     True 放行 / False 拒绝
        """
        if not key:
            return True  # 未识别的请求放行（避免把正常流量挡掉）

        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=self.capacity, last_refill=time.time())
                self._buckets[key] = bucket
            return bucket.try_consume(cost, self.capacity, self.refill_rate)

    def reset(self, key: Optional[str] = None) -> None:
        """重置某个 key（或全部）的桶。用于测试或运维手动解禁。"""
        with self._lock:
            if key is None:
                self._buckets.clear()
            else:
                self._buckets.pop(key, None)

    def stats(self) -> dict:
        """查看限流器状态（监控用）。"""
        with self._lock:
            return {
                "name": self.name,
                "capacity": self.capacity,
                "refill_rate": self.refill_rate,
                "tracked_keys": len(self._buckets),
            }


# ===== 默认限流器（按需懒创建）=====
# IP 维度：30 个桶，0.5 个/秒 → 平均 1 次/2秒，突发 30 个
_ip_limiter: Optional[RateLimiter] = None
# user_id 维度：60 个桶，1 个/秒 → 平均 1 次/秒，突发 60 个
_user_limiter: Optional[RateLimiter] = None


def get_ip_limiter() -> RateLimiter:
    global _ip_limiter
    if _ip_limiter is None:
        _ip_limiter = RateLimiter(capacity=30, refill_rate=0.5, name="ip")
    return _ip_limiter


def get_user_limiter() -> RateLimiter:
    global _user_limiter
    if _user_limiter is None:
        _user_limiter = RateLimiter(capacity=60, refill_rate=1.0, name="user")
    return _user_limiter


def check_rate_limit(ip: Optional[str], user_id: Optional[str]) -> tuple[bool, str]:
    """双维度检查。返回 (是否通过, 拒绝原因)。"""
    if not ip and not user_id:
        return True, ""  # 都未识别，放行

    if ip:
        limiter = get_ip_limiter()
        if not limiter.allow(ip):
            return False, f"IP {ip} 请求过快，请稍后再试"
    if user_id:
        limiter = get_user_limiter()
        if not limiter.allow(user_id):
            return False, f"用户 {user_id} 请求过快，请稍后再试"
    return True, ""


def reset_all() -> None:
    """清空所有桶（测试用）。"""
    global _ip_limiter, _user_limiter
    if _ip_limiter:
        _ip_limiter.reset()
    if _user_limiter:
        _user_limiter.reset()
