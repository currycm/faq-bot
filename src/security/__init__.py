# -*- coding: utf-8 -*-
"""W2 安全层

当机器人面向真实用户时，输入侧会遇到四类威胁：

    1. PII 泄露        → redact.py        用户在 query 里写手机号/身份证
    2. Prompt 注入     → injection.py     "忽略之前的指令，现在你是 X"
    3. 资源耗尽        → rate_limit.py    刷接口、刷 LLM 配额
    4. 成本失控        → budget.py        整点被刷爆 Key 被封 / 钱包空了

四道防线**顺序很重要**（enforce_security() 已封装）：
    redact → injection → rate_limit → budget → LLM

    - redact 必须最先：用户可能把别人的手机号贴过来，我们不能存也不能送给 LLM
    - injection 第二：先排掉攻击者，再让正常用户走限流配额
    - rate_limit 第三：用 IP / user_id 限速，防止单个用户把资源吃光
    - budget 第四：兜底，按时间窗口熔断，防止整体账单爆炸

任何一道失败都不会让主流程崩，会按设计降级到固定话术或直接拒绝。

=== 调用约定 ===
普通调用方只需要用 enforce_security() 一个函数。
它按顺序跑四道防线，返回统一的 SecurityVerdict。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from . import budget, injection, rate_limit, redact


# === 对外数据结构 ===
@dataclass
class SecurityVerdict:
    """四道防线的统一裁决结果。

    Attributes:
        allowed:        True 表示放行，False 表示拦截
        refusal_text:   拦截时返给用户的固定话术
        reason:         拒绝原因（简短标签，用于日志）
        sanitized_query: 脱敏后的 query（喂给 LLM 的版本）
        pii_hits:       命中的 PII 列表（用于审计与日志）
        injection_rules: 命中的注入规则（仅 medium 也记录）
        budget_consumed: 本次是否消耗了预算（用于上层决定是否调 LLM）
    """
    allowed: bool = True
    refusal_text: str = ""
    reason: str = ""
    sanitized_query: str = ""
    pii_hits: List[str] = field(default_factory=list)
    injection_rules: List[str] = field(default_factory=list)
    budget_consumed: bool = False


# === 统一编排 ===
def enforce_security(
    query: Optional[str],
    ip: Optional[str] = None,
    user_id: Optional[str] = None,
    will_call_llm: bool = False,
) -> SecurityVerdict:
    """四道防线统一编排。

    :param query:        用户问题（None/空 → 直接放行）
    :param ip:           客户端 IP（用于 IP 维度限流）
    :param user_id:      用户 ID（用于登录态维度限流）
    :param will_call_llm: 本次请求是否会真正调用 LLM。
                         True 时才会触发 budget 检查（FAQ 命中不消耗 LLM 预算）。

    :return: SecurityVerdict
        - allowed=True：sanitized_query 是脱敏后的，可以直接喂给 LLM
        - allowed=False：refusal_text 是返给用户的固定话术

    异常策略：内部任何子模块异常都不会让本函数抛错，会按"fail-open"处理，
    即尽量放行（避免安全模块自身挂掉导致全站不可用）。
    """
    from .. import config, logger  # 延迟导入避免循环

    # 1. 空 query 直接放行（由调用方决定如何处理空输入）
    if not query:
        return SecurityVerdict(allowed=True, sanitized_query="")

    # 2. 总开关：关掉时全部放行（仅调试用）
    if not getattr(config, "SECURITY_ENABLED", True):
        rr = redact.redact(query)
        return SecurityVerdict(
            allowed=True,
            sanitized_query=rr.sanitized,
            pii_hits=rr.hits,
        )

    # ----- 第一关：injection 检测 -----
    if getattr(config, "INJECTION_ENABLED", True):
        try:
            verdict = injection.detect(query)
        except Exception:
            verdict = injection.InjectionVerdict(safe=True)

        if verdict.blocked:
            # 记录攻击事件（用于审计）
            if getattr(config, "SECURITY_LOG_ENABLED", True):
                try:
                    logger.write_jsonl(config.LOG_PATH, {
                        "event": "security_injection_blocked",
                        "rules": verdict.rules,
                        "ip": ip,
                        "user_id": user_id,
                        "query_preview": (query or "")[:80],
                    })
                except Exception:
                    pass
            return SecurityVerdict(
                allowed=False,
                refusal_text=getattr(config, "INJECTION_REFUSAL_TEXT", "")
                    or injection.get_refusal_text(),
                reason="injection:" + ",".join(verdict.rules),
                sanitized_query=query or "",
                injection_rules=verdict.rules,
            )
        medium_rules = [r for r in verdict.rules if r]  # 全记，medium 也带上

    else:
        medium_rules = []

    # ----- 第二关：限流（rate_limit） -----
    try:
        ok, reason = rate_limit.check_rate_limit(ip, user_id)
    except Exception:
        ok, reason = True, ""
    if not ok:
        return SecurityVerdict(
            allowed=False,
            refusal_text=reason or "请求过快，请稍后再试",
            reason="rate_limit",
            sanitized_query=query or "",
        )

    # ----- 第三关：预算（budget，仅 LLM 调用时检查） -----
    budget_consumed = False
    if will_call_llm:
        try:
            ok, reason = budget.check_budget()
        except Exception:
            ok, reason = True, ""
        if not ok:
            return SecurityVerdict(
                allowed=False,
                refusal_text="系统繁忙，请稍后再试",
                reason="budget:" + reason,
                sanitized_query=query or "",
            )
        budget_consumed = True

    # ----- 第四关：PII 脱敏（redact） -----
    if getattr(config, "REDACTION_ENABLED", True):
        try:
            rr = redact.redact(query)
            sanitized = rr.sanitized
            pii_hits = rr.hits
        except Exception:
            sanitized = query
            pii_hits = []
    else:
        sanitized = query
        pii_hits = []

    # 命中 PII 也写一条审计日志（方便统计"用户主动透露了多少敏感信息"）
    if pii_hits and getattr(config, "SECURITY_LOG_ENABLED", True):
        try:
            logger.write_jsonl(config.LOG_PATH, {
                "event": "security_redaction",
                "hits": pii_hits,
                "ip": ip,
                "user_id": user_id,
                "query_preview": (query or "")[:80],
            })
        except Exception:
            pass

    return SecurityVerdict(
        allowed=True,
        sanitized_query=sanitized,
        pii_hits=pii_hits,
        injection_rules=medium_rules,
        budget_consumed=budget_consumed,
    )


# === 模块导出 ===
__all__ = [
    "enforce_security",
    "SecurityVerdict",
    "redact",
    "injection",
    "rate_limit",
    "budget",
]