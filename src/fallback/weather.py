# -*- coding: utf-8 -*-
"""和风天气 API 客户端

申请：https://dev.qweather.com/  → 个人开发者免费 1000 次/天
文档：https://dev.qweather.com/docs/api/

流程：
    1. 先调 GeoAPI 把城市名转成 LocationID（如南京 → 101190101）
    2. 再用 LocationID 调 WeatherAPI 拿当前天气
"""

from __future__ import annotations

import gzip
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

from .. import config, logger


# 天况代码 → 描述（和风天气 v7 标准）
# https://dev.qweather.com/docs/resource/icons/
_WEATHER_ICONS = {
    "100": "晴",
    "101": "多云",
    "102": "少云",
    "103": "晴间多云",
    "104": "阴",
    "150": "晴",
    "300": "阵雨",
    "301": "强阵雨",
    "302": "雷阵雨",
    "305": "小雨",
    "306": "中雨",
    "307": "大雨",
    "310": "暴雨",
    "400": "小雪",
    "401": "中雪",
    "402": "大雪",
    "403": "暴雪",
    "500": "雾",
    "501": "薄雾",
    "502": "霾",
}


# 内置城市 LocationID 表。
# !! GeoAPI 在部分和风账号上**未开通**（用标准域名 + 个性化 host 都返回 404），
#    所以我们优先查这张表，省一次网络请求，失败再回退 GeoAPI。
#    江苏 13 市已全收录，方便本校师生查其他江苏城市天气。
_CITY_LOCATIONS = {
    # 江苏
    "南京": "101190101",
    "无锡": "101190201",
    "徐州": "101190801",
    "常州": "101191101",
    "苏州": "101190401",
    "南通": "101190501",
    "连云港": "101191001",
    "淮安": "101190901",
    "盐城": "101190701",
    "扬州": "101190601",
    "镇江": "101191201",
    "泰州": "101191301",
    "宿迁": "101191401",
    # 直辖市
    "北京": "101010100",
    "上海": "101020100",
    "天津": "101030100",
    "重庆": "101040100",
    # 省会
    "广州": "101280101",
    "深圳": "101280601",
    "杭州": "101210101",
    "武汉": "101200101",
    "成都": "101270101",
    "西安": "101110101",
    "济南": "101120101",
    "青岛": "101120201",
    "长沙": "101250101",
    "郑州": "101180101",
    "合肥": "101220101",
    "福州": "101230101",
    "厦门": "101230201",
    "南昌": "101240101",
    "昆明": "101290101",
    "贵阳": "101260101",
    "南宁": "101300101",
    "海口": "101310101",
    "三亚": "101310201",
    "兰州": "101160101",
    "西宁": "101150101",
    "银川": "101170101",
    "呼和浩特": "101080101",
    "乌鲁木齐": "101130101",
    "拉萨": "101140101",
    "哈尔滨": "101050101",
    "长春": "101060101",
    "沈阳": "101070101",
    "大连": "101070201",
    "太原": "101100101",
    "石家庄": "101090101",
}

# 「天气/气温」前面可能出现的时间词，抽取城市名时要剥掉
_TIME_WORDS = r"(?:今天|明天|后天|昨天|现在|这周|周末|最近|这几天)"

# 兜底用的地名正则：抓「XX 今天天气怎么样」里的 XX
_CITY_BEFORE_WEATHER = re.compile(r"([\u4e00-\u9fa5]{2,7}?)" + _TIME_WORDS + r"?的?(?:天气|气温|气候)")

# 问句里的口头禅/疑问前缀，抽到地名里要去掉。
# 2026-09 修复：补齐疑问词（为什么/怎么/如何/哪里/知道），并用循环
# 剥到剥不动为止 —— 旧逻辑只剥一次，"我想知道天气"剥完剩"知道"，
# 被当成城市查 GeoAPI，然后因为 city 非空不回落到默认城市，
# 用户只能看到"暂时拿不到天气数据"。
_CITY_NOISE_PREFIX = re.compile(
    r"^(?:请问|帮我|帮我查一下|帮我查|查一下|查询|查查|看一下|看看|告诉我"
    r"|我想|我想知道|想知道|我要|麻烦|为什么|怎么|如何|哪里|哪儿|知道)"
)


def extract_city(query: str) -> Optional[str]:
    """从用户问句里抽城市名。抽不到返回 None（由调用方回落到默认城市）。

    为什么需要这个函数（2026-09-08 Docker 联调实测发现的 bug）：
        之前 router 直接调 weather.format_answer() 不传城市，
        于是「北京今天天气怎么样」永远回答默认的 config.HEFENG_CITY（南京）。
        实时接口明明通了，答案却是错的——这类错误比接口挂掉更危险，因为它看起来很正常。

    两级策略：
        1. 命中内置城市表（零网络请求，且能纠错 —— 表里的城市一定能查到）
        2. 抓「天气」前面的地名，交给 GeoAPI 解析（支持表外城市）
    """
    if not query:
        return None

    # 1) 内置城市表：长名优先，避免「南京」被「南」类短名抢先命中
    for name in sorted(_CITY_LOCATIONS, key=len, reverse=True):
        if name in query:
            return name

    # 2) 表外城市：抓「XX天气」的 XX
    m = _CITY_BEFORE_WEATHER.search(query)
    if m:
        cand = _CITY_NOISE_PREFIX.sub("", m.group(1))
        # 循环剥：噪音前缀可能叠多层（"帮我查一下" → "查一下" → ""）
        while True:
            stripped = _CITY_NOISE_PREFIX.sub("", cand)
            if stripped == cand:
                break
            cand = stripped
        cand = re.sub(r"^" + _TIME_WORDS, "", cand)
        # 剥完仍有疑问词/动词残留 → 视为没抽到，回落到默认城市
        if len(cand) >= 2 and not _CITY_NOISE_PREFIX.match(cand):
            return cand
    return None


def detect_forecast_day(query: str) -> Optional[str]:
    """识别问句指向的未来日期，返回 "明天" / "后天"；None 表示问的是现在。

    只接和风 3d 预报（今天 + 未来两天），"周末""下周"等更远的日期
    不支持 —— 宁可按实况回答，也不硬编日期。
    """
    if not query:
        return None
    if "后天" in query:  # "明后天" 也命中这里
        return "后天"
    if "明天" in query:
        return "明天"
    return None


@dataclass
class WeatherResult:
    city: str
    weather: str
    temp: str
    feels: str
    wind: str
    humidity: str
    raw: dict

    def format(self) -> str:
        return (
            f"{self.city}当前天气：{self.weather}，"
            f"气温 {self.temp}°C（体感 {self.feels}°C），"
            f"{self.wind}，湿度 {self.humidity}%。"
        )


@dataclass
class ForecastResult:
    city: str
    day: str  # "明天" / "后天"
    date: str  # fxDate，形如 2026-09-15
    weather: str  # 白天天气现象
    temp_range: str  # "12~18"
    wind: str
    raw: dict

    def format(self) -> str:
        return f"{self.city}{self.day}（{self.date}）：{self.weather}，气温 {self.temp_range}°C，{self.wind}。"


def _get_api_key() -> str:
    # 2026-09 清理：不再二次读 os.environ —— 密钥统一走 config._load_secret
    return config.HEFENG_API_KEY


def _decode_body(data: bytes) -> str:
    """和风返回的是 gzip 压缩内容，且会忽略 Accept-Encoding: identity。

    urllib 不会自动解压 gzip，直接 .decode() 只会得到一堆乱码，
    进而 json.loads 抛异常 —— 表现就是"配了 key 却一直拿不到天气"。
    """
    if data[:2] == b"\x1f\x8b":  # gzip magic number
        try:
            data = gzip.decompress(data)
        except OSError:
            pass  # 解压失败就当普通文本处理
    return data.decode("utf-8", "replace")


def _http_get(url: str, params: dict, timeout: float) -> Optional[dict]:
    """标准库 GET，自动加 key。失败返回 None（调用方负责降级）。"""
    params = {**params, "key": _get_api_key()}
    full = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        full,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(_decode_body(resp.read()))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        # 和风的错误详情在 HTTPError 的响应体里（如 403 Invalid Host），
        # 不读出来就只剩一个 "HTTP Error 403"，完全没法排查。
        detail = ""
        if isinstance(exc, urllib.error.HTTPError):
            try:
                detail = _decode_body(exc.read())[:300]
            except Exception:
                detail = "(响应体读取失败)"
        logger.write_jsonl(
            config.LOG_PATH,
            {
                "event": "weather_api_error",
                "url": url,
                "code": getattr(exc, "code", None),
                "detail": detail,
                "error": str(exc),
            },
        )
        return None


def _lookup_location(city: str) -> Optional[str]:
    """城市名 → LocationID。

    和风的 GeoAPI（`/v2/city/lookup`）部分账号未开通，会返回 404。
    所以优先走内置表，表中没有再回退到 GeoAPI。
    """
    # 1. 内置表（绝大多数校园场景就够用，覆盖国内主要城市 + 江苏 13 市）
    if city in _CITY_LOCATIONS:
        return _CITY_LOCATIONS[city]

    # 2. GeoAPI 兜底（如果账号开通了 GeoAPI 服务）
    data = _http_get(
        f"{config.HEFENG_GEO_URL}/v2/city/lookup",
        {"location": city, "number": 1},
        timeout=config.HEFENG_TIMEOUT,
    )
    if data and data.get("code") == "200":
        locs = data.get("location") or []
        if locs:
            return locs[0]["id"]
    return None


def _fetch_current(location_id: str) -> Optional[dict]:
    """当前天气实况。"""
    data = _http_get(
        f"{config.HEFENG_BASE_URL}/v7/weather/now",
        {"location": location_id},
        timeout=config.HEFENG_TIMEOUT,
    )
    if not data or data.get("code") != "200":
        return None
    return data.get("now")


def _fetch_forecast(location_id: str) -> Optional[list]:
    """未来 3 天预报（含今天）。和风 3d 在个人开发者免费额度内。"""
    data = _http_get(
        f"{config.HEFENG_BASE_URL}/v7/weather/3d",
        {"location": location_id},
        timeout=config.HEFENG_TIMEOUT,
    )
    if not data or data.get("code") != "200":
        return None
    return data.get("daily")


def get_weather(city: Optional[str] = None) -> Optional[WeatherResult]:
    """查询当前天气。任一步失败返回 None，由上层降级。

    :param city: 城市名（如"南京"），默认走 config.HEFENG_CITY
    """
    if not config.HEFENG_ENABLED:
        return None
    if not _get_api_key():
        return None

    city = city or config.HEFENG_CITY
    loc_id = _lookup_location(city)
    if not loc_id:
        return None
    now = _fetch_current(loc_id)
    if not now:
        return None

    icon = now.get("icon", "101")
    return WeatherResult(
        city=city,
        weather=_WEATHER_ICONS.get(icon, now.get("text", "未知")),
        temp=now.get("temp", "?"),
        feels=now.get("feelsLike", "?"),
        wind=f"{now.get('windDir', '')} {now.get('windScale', '?')}级".strip(),
        humidity=now.get("humidity", "?"),
        raw=now,
    )


def get_forecast(city: Optional[str], day: str) -> Optional[ForecastResult]:
    """查询某城市"明天/后天"的预报。任一步失败返回 None，由上层降级。

    !! 直接用 textDay：daily 的 text 本身就是中文现象描述，
       不需要再过 _WEATHER_ICONS 表。
    """
    if not config.HEFENG_ENABLED:
        return None
    if not _get_api_key():
        return None

    # daily[0]=今天 / [1]=明天 / [2]=后天
    offset = {"明天": 1, "后天": 2}.get(day, 0)
    if offset == 0:
        return None

    city = city or config.HEFENG_CITY
    loc_id = _lookup_location(city)
    if not loc_id:
        return None
    daily = _fetch_forecast(loc_id)
    if not daily or len(daily) <= offset:
        return None
    d = daily[offset]
    return ForecastResult(
        city=city,
        day=day,
        date=d.get("fxDate", "?"),
        weather=d.get("textDay", "未知"),
        temp_range=f"{d.get('tempMin', '?')}~{d.get('tempMax', '?')}",
        wind=f"{d.get('windDirDay', '')} {d.get('windScaleDay', '?')}级".strip(),
        raw=d,
    )


def format_answer(city: Optional[str] = None, day: Optional[str] = None) -> str:
    """对外统一接口：返回答案字符串，失败时返回固定兜底。

    :param day: "明天"/"后天" 时走 3d 预报接口；None 走实况。
    """
    try:
        r = get_forecast(city, day) if day else get_weather(city)
    except Exception as exc:  # 兜底的兜底
        logger.write_jsonl(config.LOG_PATH, {"event": "weather_exception", "error": str(exc)})
        return config.FALLBACK_TEXT

    if r is None:
        # 之前这里跟了一句"（和风天气 API key 未配置或网络异常）"，
        # 把供应商名和密钥状态透给了用户 —— 对用户零价值，还显得服务不靠谱。
        return "暂时拿不到天气数据，稍后再试，或者直接看手机自带的天气 App。"

    return r.format()
