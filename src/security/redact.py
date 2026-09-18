# -*- coding: utf-8 -*-
"""PII 脱敏（W2 安全层 第一道防线）

职责：
    把用户问题里的敏感个人信息（手机号、身份证、邮箱、银行卡、网址、IP）
    替换成 [手机号] / [身份证] / [邮箱] 等占位符。

设计原则：
    1. 替换而非删除 —— 保留语义，LLM 仍能理解上下文（"我手机 [手机号] 丢了"）
    2. 多遍扫描 —— 每种模式独立 sub，互不干扰
    3. 宽容输入 —— 不假定 query 是干净的，单条 query 可能有多种 PII
    4. 必须留痕 —— 命中 PII 必须能拿到 hits 列表，方便日志统计与审计
    5. 容错优先 —— 任何异常都返回原始文本，绝不让脱敏模块把主流程搞挂

不做什么：
    - 不修改回答文本（LLM 自己回答里出现 PII 不归本模块管）
    - 不做 NLP（纯正则覆盖 99% 场景，速度 <1ms）
    - 不调用网络（避免脱敏本身成为攻击面）
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, List, Optional


# === 归一化（2026-09 修复：全角/零宽字符绕过） ===
# NFKC 把全角数字/字母/＠ 转成半角，全角空格转普通空格；
# 之后再删除零宽字符（U+200B 等），攻击者靠插字符绕过脱敏的路被封死。
_ZERO_WIDTH_RE = re.compile(r"[​-‏‪-‮﻿]")
_CONTROL_LINEBREAK_RE = re.compile(r"[\x00-\x08\x0e-\x1f]")


def _normalize(text: str) -> str:
    """匹配前的统一归一化：NFKC → 删零宽 → 删控制符。"""
    text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = _CONTROL_LINEBREAK_RE.sub("", text)
    return text


# === PII 模式定义 ===
# 每条 (名称, regex, placeholder, validator)
# validator: 可选函数，接收 match 后的字符串，返回 True 才算真命中
#            用于银行卡 Luhn 校验、IPv4 范围校验，避免误伤长数字串
# 注意：所有模式都跑在归一化之后的文本上。

# 手机号：允许 +86 / 086 / 86 国码前缀（前缀后可带空格/连字符），
# 号码中间也允许空格/连字符（138-0013-8000、138 0013 8000 都是常见写法）。
# 2026-09 修复：旧版 (?<!\d) 直接否定"1"前一位是数字，导致
# "+8613800138000" 里整条号码漏脱敏——前缀必须并入模式一起匹配。
_MOBILE_RE = re.compile(r"(?<!\d)(?:\+?0?86[\s-]?)?1[3-9]\d(?:[\s-]?\d{4}){2}(?!\d)")
# 身份证：18 位，最后一位可以是数字或 X/x
_IDCARD_RE = re.compile(
    r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])"
    r"(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)"
)
# 邮箱
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 银行卡：16-19 位数字，允许空格/连字符分隔（卡面打印格式），过 Luhn 校验
_BANKCARD_RE = re.compile(r"(?<!\d)\d(?:[\s-]?\d){15,18}(?!\d)")
# URL：含 hxxp 变体（常见规避写法）
_URL_RE = re.compile(
    r"(?i)\b(?:https?|hxxps?|hxxp)://[^\s<>\"'，。；]+"
    r"|\bwww\.[^\s<>\"'，。；]+"
)
# IPv4
_IPV4_RE = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")


def _luhn_ok(num: str) -> bool:
    """Luhn 算法：银行卡号的标准校验。
    避免把"1234567890123456"这种纯顺序号误判为卡号。
    """
    if not num.isdigit():
        return False
    s = 0
    for i, d in enumerate(reversed(num)):
        n = int(d)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        s += n
    return s % 10 == 0


def _looks_like_ipv4(s: str) -> bool:
    """IPv4 四段都在 0~255，避免把版本号"1.2.3"误判成 IP。"""
    parts = s.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False


# (名称, regex, placeholder, validator) —— 顺序很重要，长模式优先
_PATTERNS: List[tuple] = [
    ("身份证", _IDCARD_RE, "[身份证]", None),
    # 银行卡匹配串可能含空格/连字符，Luhn 校验前先去掉分隔符
    ("银行卡", _BANKCARD_RE, "[银行卡]", lambda m: _luhn_ok(re.sub(r"[\s-]", "", m))),
    ("邮箱", _EMAIL_RE, "[邮箱]", None),
    ("URL", _URL_RE, "[网址]", None),
    ("手机号", _MOBILE_RE, "[手机号]", None),
    ("IP", _IPV4_RE, "[IP]", _looks_like_ipv4),
]


@dataclass
class RedactResult:
    """脱敏结果。

    Attributes:
        original:   原始文本
        sanitized:  脱敏后的文本（用于传给 LLM、写日志）
        hits:       命中的 PII 列表（按首次发现顺序），例 ["手机号", "身份证"]
    """

    original: str
    sanitized: str
    hits: List[str] = field(default_factory=list)

    @property
    def has_pii(self) -> bool:
        return bool(self.hits)


def redact(text: Optional[str]) -> RedactResult:
    """对一段文本执行 PII 脱敏。

    用法：
        result = redact(user_query)
        if result.has_pii:
            logger.log_redaction(result.hits)   # 审计：用户主动透露了多少敏感信息
        llm_input = result.sanitized            # 喂给 LLM 的必须是 sanitized

    异常策略：内部任何异常都被吞掉，返回与原文等价的 RedactResult，
    确保脱敏模块本身不会把主流程搞挂。
    """
    if not text:
        return RedactResult(original=text or "", sanitized=text or "", hits=[])

    try:
        # 2026-09 修复：先在归一化文本上匹配（全角数字、全角 ＠、零宽字符
        # 无法再绕过），sanitized 也输出归一化文本（全角→半角，无副作用）。
        sanitized = _normalize(text)
        hits: List[str] = []

        for name, regex, placeholder, validator in _PATTERNS:

            def _replace(
                match: re.Match,
                _name: str = name,
                _validator: Optional[Callable[[str], bool]] = validator,
                _placeholder: str = placeholder,
            ) -> str:
                matched = match.group(0)
                if _validator and not _validator(matched):
                    return matched  # 不符合校验，原样保留（不计数）
                if _name not in hits:
                    hits.append(_name)
                return _placeholder

            sanitized = regex.sub(_replace, sanitized)

        return RedactResult(original=text, sanitized=sanitized, hits=hits)
    except Exception:
        # 兜底：脱敏模块挂了不能影响主流程
        return RedactResult(original=text, sanitized=text, hits=[])
