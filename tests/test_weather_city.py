# -*- coding: utf-8 -*-
"""天气问句的城市名抽取测试

背景（2026-09-08 Docker 联调实测）：
    router 调 weather.format_answer() 时没传城市，导致「北京今天天气怎么样」
    返回的是默认城市 config.HEFENG_CITY（南京）的天气。接口 200、延迟正常、
    答案格式也正常，只有城市是错的——这种 bug 靠看日志发现不了。
"""
from __future__ import annotations

import pytest

from src.fallback import weather


@pytest.mark.parametrize(
    "query, expected",
    [
        ("北京今天天气怎么样", "北京"),
        ("上海明天会下雨吗", "上海"),
        ("帮我查一下苏州的天气", "苏州"),
        ("广州气温多少", "广州"),
        ("西安天气预报", "西安"),
        ("哈尔滨现在天气", "哈尔滨"),
    ],
)
def test_extract_city_from_builtin_table(query, expected):
    """问句里出现内置城市表中的城市 → 直接命中。"""
    assert weather.extract_city(query) == expected


def test_long_city_name_wins_over_short():
    """长名优先：避免「连云港」被更短的同前缀城市抢走。"""
    assert weather.extract_city("连云港天气") == "连云港"


@pytest.mark.parametrize(
    "query",
    [
        "今天天气怎么样",
        "明天会下雨吗",
        "今天几度",
        "现在热不热",
        "",
    ],
)
def test_no_city_returns_none(query):
    """没提城市 → None，由调用方回落到默认城市（不能瞎猜）。"""
    assert weather.extract_city(query) is None


def test_unknown_city_is_still_extracted():
    """表外城市（如甘肃天水）也要能抽出来，交给 GeoAPI 解析。"""
    assert weather.extract_city("天水今天天气怎么样") == "天水"


def test_question_prefix_is_stripped():
    """口语前缀「请问/帮我查一下」不能被当成城市名的一部分。"""
    assert weather.extract_city("请问无锡天气如何") == "无锡"
