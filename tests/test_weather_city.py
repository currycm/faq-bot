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


# ---------------------------------------------------------------- 3d 预报
def _mock_auth(monkeypatch):
    """绕过真实 key / GeoAPI：预报逻辑测试只关心取哪一天、字段对不对。"""
    monkeypatch.setattr(weather, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(weather, "_lookup_location", lambda c: "101190101")


def test_detect_forecast_day():
    assert weather.detect_forecast_day("明天会下雨吗") == "明天"
    assert weather.detect_forecast_day("后天北京天气") == "后天"
    assert weather.detect_forecast_day("明后天天气") == "后天"
    assert weather.detect_forecast_day("今天天气怎么样") is None
    assert weather.detect_forecast_day("") is None


def test_forecast_uses_daily_entry(monkeypatch):
    """问「明天」必须取 daily[1]，字段映射正确。"""
    _mock_auth(monkeypatch)
    fetched = []

    def fake_fetch(location_id):
        fetched.append(location_id)
        return [
            {"fxDate": "2026-09-14", "textDay": "晴", "tempMin": "20",
             "tempMax": "28", "windDirDay": "东南风", "windScaleDay": "3"},
            {"fxDate": "2026-09-15", "textDay": "小雨", "tempMin": "16",
             "tempMax": "22", "windDirDay": "东北风", "windScaleDay": "4"},
        ]

    monkeypatch.setattr(weather, "_fetch_forecast", fake_fetch)
    r = weather.get_forecast("南京", "明天")
    assert r is not None
    assert r.day == "明天"
    assert r.date == "2026-09-15"
    assert r.weather == "小雨"
    assert r.temp_range == "16~22"
    assert r.wind == "东北风 4级"
    assert fetched == ["101190101"]


def test_forecast_day_after_tomorrow_offset(monkeypatch):
    """后天 → daily[2]。"""
    _mock_auth(monkeypatch)
    daily = [{"fxDate": f"2026-09-{14 + i}", "textDay": "晴", "tempMin": "20",
              "tempMax": "28", "windDirDay": "东风", "windScaleDay": "3"}
             for i in range(3)]
    monkeypatch.setattr(weather, "_fetch_forecast", lambda loc: daily)
    r = weather.get_forecast("南京", "后天")
    assert r is not None and r.date == "2026-09-16"


def test_forecast_insufficient_days(monkeypatch):
    """接口只返回 1 天时问「后天」→ None（上层降级），不能 IndexError。"""
    _mock_auth(monkeypatch)
    monkeypatch.setattr(weather, "_fetch_forecast",
                        lambda loc: [{"fxDate": "2026-09-14"}])
    assert weather.get_forecast("南京", "后天") is None


def test_format_answer_forecast_fallback(monkeypatch):
    """预报查询失败时返回中性兜底话术，不裸抛。"""
    monkeypatch.setattr(weather, "get_forecast", lambda c, d: None)
    ans = weather.format_answer("南京", day="明天")
    assert "天气" in ans
