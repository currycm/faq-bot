# -*- coding: utf-8 -*-
"""兜底路由器

职责：检索未命中后，决定这个问题交给谁。

匹配顺序（先到先得）：
    1. 闲聊关键词    → 固定话术
    2. 实时关键词    → 调对应 API（天气 / 后续可加课表/成绩）
    3. 校园事务关键词 → 固定话术（绝不让 LLM 编校务）
    4. 默认          → LLM 兜底（通识问答）
    5. 任何 API/LLM 失败 → 降级到 FALLBACK_TEXT

为什么先判闲聊：闲聊问题（如"你好"）绝不该触发 LLM，浪费 token。
为什么校园事务要拦截在 LLM 之前：用户问"大四还能转专业吗"，
即便 FAQ 没命中，也不能让 LLM 编一个看起来"合理"的答案 —— 这是底线。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .. import config, logger
from . import llm_client, weather


class QueryType(str, Enum):
    CHAT = "chat"             # 闲聊 / 打招呼
    REALTIME = "realtime"     # 实时查询（天气 / 课表 / 校历）
    CAMPUS = "campus_only"    # 疑似校园事务但未命中
    GENERAL = "general"       # 通识问答 → 走 LLM
    UNKNOWN = "unknown"       # 兜底兜底


@dataclass
class RouterDecision:
    query_type: QueryType
    answer: str
    source: str        # 哪个子模块给的答案（fixed / llm / weather）
    rule: str          # 命中的规则名，方便调试


# ---------------------------------------------------------------- 关键词工具
def _contains_any(text: str, keywords: list[str]) -> Optional[str]:
    """子串匹配（不依赖分词）。返回首个命中的关键词，没有则 None。

    用 re 而不是 in：避免大小写、标点差异（如"WiFi" / "wifi"）漏匹配。
    """
    text_lower = text.lower()
    for kw in keywords:
        # 关键词含英文时不区分大小写；中文直接子串匹配
        if any(c.isascii() and c.isalpha() for c in kw):
            if re.search(re.escape(kw), text_lower, re.IGNORECASE):
                return kw
        else:
            if kw in text:
                return kw
    return None


def _classify(query: str) -> QueryType:
    """纯规则分类，不调任何外部 API。"""
    q = query.strip()

    # 1. 闲聊（必须在最前：闲聊不该触发任何 API）
    if _contains_any(q, config.CHAT_KEYWORDS):
        return QueryType.CHAT

    # 2. 实时查询
    if _contains_any(q, config.REALTIME_KEYWORDS):
        return QueryType.REALTIME

    # 3. 校园事务（拦截所有"听起来像校务"的问题）
    if _contains_any(q, config.CAMPUS_KEYWORDS):
        return QueryType.CAMPUS

    # 4. 默认：通识
    return QueryType.GENERAL


# ---------------------------------------------------------------- 答案生成
def _answer_chat() -> tuple[str, str]:
    """闲聊：固定话术即可，节省 token。"""
    text = (
        "你好，我是南京工业职业技术大学的智能助手小南～\n"
        "问我校园里的事儿我比较拿手，比如选课、校园卡、宿舍、奖学金……\n"
        "其他话题我也能聊，但不一定都对哦。"
    )
    return text, "fixed_chat"


def _answer_realtime(query: str) -> tuple[str, str]:
    """实时查询：目前只支持天气，其他类型走兜底。"""
    if _contains_any(query, ["天气", "气温", "下雨", "下雪", "刮风", "几度",
                              "穿什么", "热不热", "冷不冷", "晴", "阴",
                              "云", "雾", "霾", "天气预报"]):
        # !! 必须把城市传进去，否则「北京天气」会回答成默认城市（config.HEFENG_CITY）
        ans = weather.format_answer(weather.extract_city(query))
        return ans, "weather"

    # 其它实时类（校历日期/课表）暂未接入，TODO
    text = ("这个问题需要查询实时数据，目前还没接入对应系统。\n"
            "你可以直接到教务系统或学校官网查询。")
    return text, "fixed_realtime_unsupported"


def _answer_campus() -> tuple[str, str]:
    """校园事务未命中：硬兜底，绝不让 LLM 编。"""
    text = (
        "这个问题涉及到学校的具体政策，目前的知识库还没有覆盖。\n"
        "建议直接联系相关部门，或者把问题反馈给管理员补充到知识库。\n"
        "👉 教务处 / 学工处 / 后勤处 / 数智化中心（详见学校官网）"
    )
    return text, "fixed_campus"


def _answer_general(query: str, sanitized_query: Optional[str] = None) -> tuple[str, str]:
    """通识问答：调 LLM 兜底。失败则降级到固定话术。

    :param query:          原 query（仅日志/审计用）
    :param sanitized_query: 脱敏后的 query（实际送给 LLM 的版本）。
                          None 时退回 query，保持向后兼容。
    """
    if not config.DEEPSEEK_ENABLED:
        return config.FALLBACK_TEXT, "fixed_general_disabled"

    # 优先用 sanitized_query 喂给 LLM，避免敏感信息进入 prompt
    llm_input = sanitized_query if sanitized_query is not None else query
    ans = llm_client.format_answer(llm_input)
    # 通过"DeepSeek 生成"标签判断是否真的拿到 LLM 回复
    if "DeepSeek 生成" in ans:
        return ans, "llm"
    return ans, "fixed_general_fallback"


# ---------------------------------------------------------------- 公开入口
def dispatch(query: str, sanitized_query: Optional[str] = None) -> RouterDecision:
    """主入口。返回 RouterDecision(query_type, answer, source, rule)。

    :param query:          原始 query（用于分类 + 路由器审计日志）
    :param sanitized_query: W2 脱敏后的 query（仅在 LLM 通道使用）。
                          留空时路由器自动 fallback 到原 query。
    """
    q = (query or "").strip()
    if not q:
        return RouterDecision(
            query_type=QueryType.UNKNOWN,
            answer="请输入你的问题～",
            source="fixed_empty",
            rule="empty",
        )

    qt = _classify(q)
    rule = ""

    if qt is QueryType.CHAT:
        ans, src = _answer_chat()
        rule = "chat_keyword"
    elif qt is QueryType.REALTIME:
        ans, src = _answer_realtime(q)
        rule = "realtime_keyword"
    elif qt is QueryType.CAMPUS:
        ans, src = _answer_campus()
        rule = "campus_keyword"
    elif qt is QueryType.GENERAL:
        ans, src = _answer_general(q, sanitized_query=sanitized_query)
        rule = "default_llm"
    else:
        ans, src = config.FALLBACK_TEXT, "fixed_unknown"
        rule = "unknown"

    # 路由日志：调试 + 后续可用于做路由器质量分析
    if config.ROUTER_LOG_ENABLED:
        logger.write_jsonl(config.LOG_PATH, {
            "event": "fallback_dispatch",
            "query": q,
            "type": qt.value,
            "source": src,
            "rule": rule,
        })

    return RouterDecision(query_type=qt, answer=ans, source=src, rule=rule)


class FallbackRouter:
    """对外类形式，方便测试 mock。"""
    def __init__(self):
        pass

    def route(self, query: str, sanitized_query: Optional[str] = None) -> RouterDecision:
        return dispatch(query, sanitized_query=sanitized_query)