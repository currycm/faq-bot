# -*- coding: utf-8 -*-
"""Redis 分布式后端（可选）：多 worker / 多实例下精确的限流与预算熔断

背景：
    令牌桶与成本熔断默认是进程内 in-memory（rate_limit.py / budget.py），
    gunicorn -w 2 时每个 worker 独立计数，实际额度 ≈ N × 配置值
    （实测 80 并发放行 52 次 ≈ 2×30，见 README「已知限制」）。
    本模块把两份计数搬到 Redis，所有 worker 共享同一状态。

启用方式：
    设环境变量 FAQ_REDIS_URL（如 redis://127.0.0.1:6379/0）。
    未设 URL 或 Redis 连不上时，自动退回进程内实现 —— 行为与旧版
    完全一致，不会因为 Redis 挂掉而拒服务。

失败策略（与安全层整体一致：宁可退化，不可放空）：
    - 初始化失败（连不上 / redis 包缺失）→ get_ip_limiter / get_budget
      直接构造进程内版本；
    - 运行中出错 → 限流退回本进程的桶继续限流（不是直接放行），
      预算同样退回进程内熔断器；错误日志按 60s 节流，避免高 QPS 刷屏。

已知取舍：
    - 令牌桶用 Lua 保证「读-算-写」原子；预算窗口的 check / record 仍是
      两步，与进程内版本一样存在 TOCTOU 窗口（见 budget.BudgetGuard.check
      注释），量级可接受。
    - 时间源：令牌桶用 Redis TIME（与状态同一次原子更新，天然一致）；
      预算窗口用各 worker 的 time.time()（同机部署时钟一致；跨机器部署
      时钟漂移大会影响窗口精度）。
    - Lua 脚本的语义应在真实 Redis 上联调确认（单元测试用 FakeRedis
      只覆盖包装层逻辑）。
"""

from __future__ import annotations

import time
import uuid
from typing import Optional

from .. import config, logger
from .budget import BudgetGuard
from .rate_limit import RateLimiter

_TOKEN_BUCKET_LUA = """
local key      = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill   = tonumber(ARGV[2])
local cost     = tonumber(ARGV[3])
local t        = redis.call('TIME')
local now      = tonumber(t[1]) + tonumber(t[2]) / 1000000
local state    = redis.call('HMGET', key, 'tokens', 'ts')
local tokens   = tonumber(state[1])
local ts       = tonumber(state[2])
if tokens == nil or ts == nil then
    tokens = capacity
    ts = now
end
tokens = math.min(capacity, tokens + (now - ts) * refill)
if tokens < 0 then tokens = 0 end
local allowed = 0
if tokens >= cost then
    tokens = tokens - cost
    allowed = 1
end
redis.call('HSET', key, 'tokens', tokens, 'ts', now)
-- 桶从空到满需要 capacity/refill 秒，2 倍兜底 + 60s，闲置桶自动回收
redis.call('PEXPIRE', key, math.ceil((capacity / refill) * 2 * 1000) + 60000)
return {allowed, tostring(tokens)}
"""


def _throttled_log(event: str, detail: dict, state: dict) -> None:
    """同一来源的错误日志最多 60s 记一条，避免高 QPS 下刷爆日志。"""
    now = time.time()
    if now - state.get("last", 0.0) < 60:
        return
    state["last"] = now
    logger.write_jsonl(config.LOG_PATH, {"event": event, **detail})


class RedisRateLimiter:
    """与 rate_limit.RateLimiter 同接口的 Redis 令牌桶（跨进程共享）。

    :param client: 测试注入用；生产不传，内部按 url 自建。
    """

    def __init__(
        self, url: str, capacity: int, refill_rate: float, name: str, socket_timeout: float = 1.0, client=None
    ):
        import redis as redis_lib

        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self.name = name
        self._prefix = "faqbot:rl"
        self._client = (
            client
            if client is not None
            else redis_lib.Redis.from_url(
                url,
                socket_timeout=socket_timeout,
                socket_connect_timeout=socket_timeout,
                decode_responses=True,
            )
        )
        # Redis 故障时的进程内降级桶：同一个 key 在本进程内继续计数
        self._fallback = RateLimiter(capacity=capacity, refill_rate=refill_rate, name=f"{name}-fallback")
        self._script = self._client.register_script(_TOKEN_BUCKET_LUA)
        self._err_state: dict = {}

    def allow(self, key: Optional[str], cost: float = 1.0) -> bool:
        key = key or "__unidentified__"
        try:
            res = self._script(
                keys=[f"{self._prefix}:{self.name}:{key}"],
                args=[self.capacity, self.refill_rate, cost],
            )
            return int(res[0]) == 1
        except Exception as exc:
            _throttled_log("redis_limiter_error", {"limiter": self.name, "error": str(exc)[:200]}, self._err_state)
            return self._fallback.allow(key, cost)

    def reset(self, key: Optional[str] = None) -> None:
        """清空某个 key（或本限流器的全部桶）。用于测试与运维手动解禁。"""
        try:
            if key is None:
                pattern = f"{self._prefix}:{self.name}:*"
                for k in self._client.scan_iter(pattern):
                    self._client.delete(k)
            else:
                self._client.delete(f"{self._prefix}:{self.name}:{key or '__unidentified__'}")
        except Exception as exc:
            _throttled_log(
                "redis_limiter_error", {"limiter": self.name, "op": "reset", "error": str(exc)[:200]}, self._err_state
            )
            self._fallback.reset(key)

    def stats(self) -> dict:
        return {
            "name": self.name,
            "backend": "redis",
            "capacity": self.capacity,
            "refill_rate": self.refill_rate,
        }


class RedisBudgetGuard:
    """与 budget.BudgetGuard 同接口的 Redis 滑动窗口熔断器（ZSET 实现）。

    member 形如 "<ts>:<cost>:<uuid>"，score 存时间戳：
    窗口裁剪用 score，成本从 member 解析。窗口内最多 BUDGET_MAX_CALLS
    条记录，ZRANGE 全量拉取的开销可忽略。
    """

    def __init__(
        self,
        url: str,
        window_sec: float = 3600,
        max_calls: int = 500,
        max_cost_cny: float = 10.0,
        avg_cost_per_call: float = 0.01,
        name: str = "llm",
        socket_timeout: float = 1.0,
        client=None,
    ):
        import redis as redis_lib

        self.window_sec = float(window_sec)
        self.max_calls = int(max_calls)
        self.max_cost_cny = float(max_cost_cny)
        self.avg_cost_per_call = float(avg_cost_per_call)
        self.name = name
        self._key = f"faqbot:budget:{name}"
        self._client = (
            client
            if client is not None
            else redis_lib.Redis.from_url(
                url,
                socket_timeout=socket_timeout,
                socket_connect_timeout=socket_timeout,
                decode_responses=True,
            )
        )
        self._fallback = BudgetGuard(
            window_sec=window_sec,
            max_calls=max_calls,
            max_cost_cny=max_cost_cny,
            avg_cost_per_call=avg_cost_per_call,
            name=f"{name}-fallback",
        )
        self._err_state: dict = {}

    @staticmethod
    def _member_cost(member: str) -> float:
        try:
            return float(member.split(":")[1])
        except (IndexError, ValueError):
            return 0.0

    def _window_snapshot(self) -> tuple[int, float]:
        """裁剪过期记录，返回 (窗口内调用次数, 窗口内总成本)。"""
        pipe = self._client.pipeline()
        pipe.zremrangebyscore(self._key, 0, time.time() - self.window_sec)
        pipe.zcard(self._key)
        pipe.zrange(self._key, 0, -1)
        _, calls, members = pipe.execute()
        total = sum(self._member_cost(m) for m in members)
        return int(calls), total

    def check(self, estimated_cost_cny: Optional[float] = None) -> tuple[bool, str]:
        """检查当前是否允许调用 LLM。接口与 BudgetGuard.check 一致。"""
        cost = estimated_cost_cny if estimated_cost_cny is not None else self.avg_cost_per_call
        try:
            calls, total = self._window_snapshot()
            if calls >= self.max_calls:
                return False, (f"调用次数熔断：{self.window_sec:.0f}s 内已调用 {calls} 次，超过上限 {self.max_calls}")
            if total + cost >= self.max_cost_cny:
                return False, (
                    f"成本熔断：{self.window_sec:.0f}s 内已花费 ¥{total:.4f}，接近上限 ¥{self.max_cost_cny:.2f}"
                )
            return True, ""
        except Exception as exc:
            _throttled_log("redis_budget_error", {"error": str(exc)[:200]}, self._err_state)
            return self._fallback.check(estimated_cost_cny)

    def record(self, actual_cost_cny: Optional[float] = None) -> None:
        """记录一次调用（仅在 LLM 真正发生后调用，接口与 BudgetGuard 一致）。"""
        cost = actual_cost_cny if actual_cost_cny is not None else self.avg_cost_per_call
        try:
            now = time.time()
            member = f"{now:.6f}:{cost:.8f}:{uuid.uuid4().hex}"
            pipe = self._client.pipeline()
            pipe.zadd(self._key, {member: now})
            pipe.zremrangebyscore(self._key, 0, now - self.window_sec)
            pipe.pexpire(self._key, int(self.window_sec * 2 * 1000) + 60000)
            pipe.execute()
        except Exception as exc:
            _throttled_log("redis_budget_error", {"op": "record", "error": str(exc)[:200]}, self._err_state)
            self._fallback.record(actual_cost_cny)

    def stats(self) -> dict:
        try:
            calls, total = self._window_snapshot()
            return {
                "name": self.name,
                "backend": "redis",
                "window_sec": self.window_sec,
                "calls_in_window": calls,
                "cost_in_window": round(total, 6),
                "max_calls": self.max_calls,
                "max_cost_cny": self.max_cost_cny,
                # 语义与 BudgetGuard.stats 对齐："下一次 check 会不会被挡"
                "is_open": (calls >= self.max_calls or total + self.avg_cost_per_call >= self.max_cost_cny),
            }
        except Exception:
            return self._fallback.stats()

    def reset(self) -> None:
        """清空窗口（测试 / 运维手动重置用）。"""
        try:
            self._client.delete(self._key)
        except Exception:
            self._fallback.reset()
