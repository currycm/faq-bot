# -*- coding: utf-8 -*-
"""成本熔断（W2 安全层 第四道防线）

目标：
    即使绕过限流，也不能让 DeepSeek API 当天的账单爆炸。
    按时间窗口（默认 1 小时）累计 LLM 调用次数 / 估算成本，
    超阈值即熔断：后续请求不再调 LLM，直接返回固定话术。

设计：
    - **滑动窗口**：每个 key 维护一个最近 N 秒内的计数。
      简单实现：把窗口分成 K 个 bucket（如 1 小时 = 60 个 1 分钟桶），
      每分钟轮转，累加时只算窗口内的桶。
    - **双指标**：调用次数 + 估算成本（按平均 token 数 × 单价）。
      任何一个超阈值都熔断。
    - **熔断恢复**：窗口自然滑出旧数据后，自动恢复。
    - **失败安全**：模块异常 → 放行（避免熔断器自己挂掉导致全站不可用）。

为什么不是简单计数器：
    简单"每小时清零"的计数器在 0:59 大量调用，1:00 又大量调用，
    等于 1 分钟内被刷了 2 倍。滑动窗口可以避免这种边界突袭。

注意：
    - 进程内 in-memory。多 worker 时每个 worker 独立计数（与限流同）。
    - 估算成本按"平均 200 tokens/次"粗算，误差可接受。
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional


@dataclass
class _Window:
    """滑动窗口：请求 (时间戳, 成本) 队列。

    2026-09 修复：只存时间戳导致成本熔断形同虚设（成本永远按估算
    次数×平均价线性增长，永远撞不到独立阈值）。现在每次记录带真实
    成本，次数与成本两个指标真正解耦。
    """
    events: Deque[tuple] = field(default_factory=deque)

    def _prune(self, window_sec: float) -> None:
        now = time.time()
        cutoff = now - window_sec
        dq = self.events
        while dq and dq[0][0] < cutoff:
            dq.popleft()

    def count_in(self, window_sec: float) -> int:
        self._prune(window_sec)
        return len(self.events)

    def cost_in(self, window_sec: float) -> float:
        self._prune(window_sec)
        return sum(cost for _ts, cost in self.events)

    def record(self, cost_cny: float = 0.0) -> None:
        self.events.append((time.time(), float(cost_cny)))


class BudgetGuard:
    """进程级成本熔断器。

    双指标：
        - max_calls_per_window: 窗口内最多调 LLM 几次
        - max_cost_per_window:   窗口内估算最多花多少钱（CNY）

    任一指标超阈值 → 触发熔断 → 返回 is_open=True。
    """

    def __init__(
        self,
        window_sec: int = 3600,
        max_calls: int = 500,
        max_cost_cny: float = 10.0,
        avg_cost_per_call: float = 0.01,
        name: str = "default",
    ):
        """
        :param window_sec:       滑动窗口长度（秒），默认 1 小时
        :param max_calls:        窗口内最多调用次数（防高频）
        :param max_cost_cny:     窗口内估算最大成本（元），防大账单
        :param avg_cost_per_call: 每次调用平均成本（元），粗算用
        :param name:             熔断器名（用于日志）
        """
        self.window_sec = float(window_sec)
        self.max_calls = int(max_calls)
        self.max_cost_cny = float(max_cost_cny)
        self.avg_cost_per_call = float(avg_cost_per_call)
        self.name = name
        self._window = _Window()
        self._lock = threading.Lock()
        # 最近一次被熔断的时间（仅用于日志，不影响逻辑）
        self._last_trip_at: Optional[float] = None

    def check(self, estimated_cost_cny: Optional[float] = None) -> tuple[bool, str]:
        """检查当前是否允许调用 LLM。

        :param estimated_cost_cny: 本次调用的估算成本（默认按 avg_cost_per_call）
        :return: (是否放行, 拒绝原因)

        2026-09 修复：成本按窗口内**已记录的真实成本**累计判断，
        不再用 (calls+1)×avg 估算 —— 旧逻辑在默认参数下成本熔断
        永远不可达（500 次上限先到），"双指标"实为单指标。
        注意：本方法只检查不记录，调用方应在 LLM 真正发生后
        record()。为缩小 TOCTOU 窗口，应把 check 放在 LLM 调用前
        一刻（见 fallback/router.py）。
        """
        try:
            cost = estimated_cost_cny if estimated_cost_cny is not None else self.avg_cost_per_call
            with self._lock:
                calls = self._window.count_in(self.window_sec)
                if calls >= self.max_calls:
                    return False, (
                        f"调用次数熔断：{self.window_sec:.0f}s 内已调用 {calls} 次，"
                        f"超过上限 {self.max_calls}"
                    )
                total_cost = self._window.cost_in(self.window_sec)
                if total_cost + cost >= self.max_cost_cny:
                    return False, (
                        f"成本熔断：{self.window_sec:.0f}s 内已花费 ¥{total_cost:.4f}，"
                        f"接近上限 ¥{self.max_cost_cny:.2f}"
                    )
            return True, ""
        except Exception as exc:
            # 熔断器自己挂了 → 放行（fail open），避免把全站打挂
            return True, f"budget_check_error:{exc}"

    def record(self, actual_cost_cny: Optional[float] = None) -> None:
        """记录一次调用（仅在调用真正发生后调用，避免假阳性）。

        :param actual_cost_cny: 本次调用的真实成本（元）。
                                None 时按 avg_cost_per_call 估算。
        """
        try:
            cost = actual_cost_cny if actual_cost_cny is not None else self.avg_cost_per_call
            with self._lock:
                self._window.record(cost)
        except Exception:
            pass

    def stats(self) -> dict:
        """查看熔断器状态（监控用）。"""
        with self._lock:
            calls = self._window.count_in(self.window_sec)
            cost = self._window.cost_in(self.window_sec)
            return {
                "name": self.name,
                "window_sec": self.window_sec,
                "calls_in_window": calls,
                "cost_in_window": round(cost, 6),
                "max_calls": self.max_calls,
                "max_cost_cny": self.max_cost_cny,
                # 2026-09 修复：双指标任一触顶即算熔断——此前只看次数，
                # 成本维度先爆时监控面板仍显示 is_open=False。
                "is_open": calls >= self.max_calls or cost >= self.max_cost_cny,
            }

    def reset(self) -> None:
        """清空窗口（测试 / 运维手动重置用）。"""
        with self._lock:
            self._window.events.clear()
            self._last_trip_at = None


# ===== 默认熔断器 =====
_budget: Optional[BudgetGuard] = None


def get_budget() -> BudgetGuard:
    global _budget
    if _budget is None:
        # 2026-09 修复：从 config 读取（此前写死导致 BUDGET_* 调了不生效）。
        # 默认：1 小时 500 次 / 10 元。
        from .. import config
        _budget = BudgetGuard(
            window_sec=getattr(config, "BUDGET_WINDOW_SEC", 3600),
            max_calls=getattr(config, "BUDGET_MAX_CALLS", 500),
            max_cost_cny=getattr(config, "BUDGET_MAX_COST_CNY", 10.0),
            avg_cost_per_call=getattr(config, "BUDGET_AVG_COST_CNY", 0.01),
            name="llm",
        )
    return _budget


def check_budget() -> tuple[bool, str]:
    """检查是否在预算内。"""
    return get_budget().check()


def record_llm_call(cost_cny: Optional[float] = None) -> None:
    """记录一次 LLM 调用（无论成功失败都计数）。"""
    get_budget().record(cost_cny)


def reset_budget() -> None:
    """重置熔断器（测试用）。"""
    get_budget().reset()
