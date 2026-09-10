# -*- coding: utf-8 -*-
"""校园地图（纯前端，无需后端）— 方案 B：手绘地图图片叠加（底图，无标记）

实现：
    - 两张手绘地图（天堂校区 / 仙林校区）作为各校区地图底图，用 Folium ImageOverlay 叠加。
    - 图片以 base64 内嵌进地图 HTML，无需静态文件服务器（单进程部署 / HF Spaces 也能用）。
    - 当前仅展示手绘底图；POI 数据仍保留在 CAMPUSES 中，可按需恢复标记渲染。

⚠️ 数据来源说明：
    - campus["center"] 为校区地理中心（估算值，请按需校准，仅用于让地图默认落在正确城市区域）。
    - pois 的 (x, y) 是「相对图片」的百分比：x:0=左 100=右；y:0=上 100=下。
      请按手绘图上的位置填写，不需要任何真实经纬度。
"""
from __future__ import annotations

import base64
import math
import struct
from pathlib import Path

import folium
import streamlit as st
from folium.raster_layers import ImageOverlay

_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "campus_maps"

# 每个校区：图片文件名、地理中心(估算)、图片地理半跨度、POI 列表。
# POI 的 (x, y) 为图片内百分比：x 0→左 100→右，y 0→上 100→下。
CAMPUSES: dict[str, dict] = {
    "天堂校区": {
        "image": "campus_tiantang.jpg",
        "center": (32.072, 118.764),   # ⚠️ 估算：南京工业职业技术大学天堂校区附近，请校准
        "span_lat": 0.006,             # 图片覆盖约 ±0.006° 纬度 ≈ 1.3km
        "pois": [
            # 数据来源：天堂校区 手绘图坐标（原点=图片左上角，坐标=标签文字中心像素点，按 1468x960 换算百分比；x:0=左100=右, y:0=上100=下）
            {"name": "东门", "x": 13.6, "y": 22.9, "desc": "校门"},
            {"name": "西门", "x": 39.5, "y": 93.8, "desc": "校门"},
            {"name": "北苑一栋", "x": 11.6, "y": 33.3, "desc": "学生宿舍"},
            {"name": "北苑二栋", "x": 16.3, "y": 27.1, "desc": "学生宿舍"},
            {"name": "南苑一栋", "x": 52.8, "y": 15.6, "desc": "学生宿舍"},
            {"name": "南苑二栋", "x": 55.2, "y": 6.2, "desc": "学生宿舍"},
            {"name": "综合楼", "x": 33.4, "y": 21.9, "desc": "教学综合楼"},
            {"name": "艺术工坊", "x": 9.5, "y": 42.7, "desc": "艺术实训"},
            {"name": "艺术茶吧", "x": 26.2, "y": 30.2, "desc": "休闲配套"},
            {"name": "北苑餐厅", "x": 19.1, "y": 37.5, "desc": "食堂"},
            {"name": "南苑餐厅", "x": 52.8, "y": 18.8, "desc": "食堂"},
            {"name": "运动场", "x": 45.6, "y": 27.1, "desc": "田径场"},
            {"name": "风雨球场", "x": 49.0, "y": 41.7, "desc": "球类场地"},
            {"name": "篮球场", "x": 40.9, "y": 55.2, "desc": "篮球场地"},
            {"name": "停车场", "x": 49.0, "y": 77.1, "desc": "停车区域"},
            {"name": "校训石", "x": 30.0, "y": 39.6, "desc": "景观石刻"},
            {"name": "炎培园", "x": 35.4, "y": 68.8, "desc": "园林景观"},
            {"name": "颐礼台", "x": 45.6, "y": 13.5, "desc": "广场平台"},

        ]
    },
    "仙林校区": {
        "image": "campus_xianlin.jpg",
        "center": (32.115, 118.918),   # ⚠️ 估算：南京工业职业技术大学仙林校区附近，请校准
        "span_lat": 0.006,
        "pois": [
            # 数据来源：仙林校区 手绘图坐标（原点=图片左上角，坐标=标签文字中心像素点，按 1358x960 换算百分比；x:0=左100=右, y:0=上100=下）
            {"name": "北大门", "x": 50.8, "y": 8.3, "desc": "校门"},
            {"name": "西大门", "x": 3.7, "y": 47.9, "desc": "校门"},
            {"name": "南大门", "x": 38.3, "y": 96.9, "desc": "校门"},
            {"name": "海棠苑1栋", "x": 10.7, "y": 27.6, "desc": "学生宿舍"},
            {"name": "海棠苑2栋", "x": 10.7, "y": 21.9, "desc": "学生宿舍"},
            {"name": "筠竹苑1栋", "x": 16.9, "y": 28.1, "desc": "学生宿舍"},
            {"name": "筠竹苑2栋", "x": 16.9, "y": 18.8, "desc": "学生宿舍"},
            {"name": "梧桐苑1-2栋", "x": 10.9, "y": 45.8, "desc": "学生宿舍"},
            {"name": "梧桐苑3栋", "x": 10.2, "y": 39.6, "desc": "学生宿舍"},
            {"name": "梧桐苑4-5栋", "x": 10.2, "y": 34.4, "desc": "学生宿舍"},
            {"name": "香樟苑1栋", "x": 17.7, "y": 41.7, "desc": "学生宿舍"},
            {"name": "香樟苑2栋", "x": 17.7, "y": 35.4, "desc": "学生宿舍"},
            {"name": "雪松苑1-2栋", "x": 10.7, "y": 65.6, "desc": "学生宿舍"},
            {"name": "雪松苑3栋", "x": 10.7, "y": 60.4, "desc": "学生宿舍"},
            {"name": "雪松苑4-5栋", "x": 10.7, "y": 55.2, "desc": "学生宿舍"},
            {"name": "青教公寓B1", "x": 18.3, "y": 66.1, "desc": "公寓"},
            {"name": "青教公寓B2", "x": 11.8, "y": 72.4, "desc": "公寓"},
            {"name": "筠竹苑G1", "x": 57.1, "y": 15.6, "desc": "学生宿舍"},
            {"name": "筠竹苑G2", "x": 57.1, "y": 18.8, "desc": "学生宿舍"},
            {"name": "筠竹苑G3", "x": 58.5, "y": 21.9, "desc": "学生宿舍"},
            {"name": "筠竹苑G4", "x": 57.1, "y": 25.0, "desc": "学生宿舍"},
            {"name": "双创大楼", "x": 64.1, "y": 17.7, "desc": "宿舍/实训楼"},
            {"name": "乐业楼", "x": 53.0, "y": 43.8, "desc": "教学楼"},
            {"name": "敬业楼", "x": 53.0, "y": 55.2, "desc": "教学楼"},
            {"name": "求真楼", "x": 60.8, "y": 55.2, "desc": "教学楼"},
            {"name": "乐群楼", "x": 52.3, "y": 70.8, "desc": "教学楼"},
            {"name": "行政楼", "x": 50.4, "y": 85.4, "desc": "行政办公"},
            {"name": "图书馆（求是楼）", "x": 60.8, "y": 43.8, "desc": "图书馆"},
            {"name": "学术交流中心", "x": 31.7, "y": 80.2, "desc": "会议接待"},
            {"name": "大学生创新发展中心", "x": 24.7, "y": 76.0, "desc": "创新创业"},
            {"name": "人工智能及工业互联网产教融合大楼（施工中）", "x": 61.1, "y": 71.9, "desc": "在建实训楼"},
            {"name": "第一食堂", "x": 23.6, "y": 26.0, "desc": "食堂"},
            {"name": "快递服务中心", "x": 23.6, "y": 17.7, "desc": "后勤服务"},
            {"name": "新体育场", "x": 36.5, "y": 34.4, "desc": "运动场"},
            {"name": "老体育场", "x": 40.9, "y": 34.4, "desc": "运动场"},
            {"name": "体育馆", "x": 44.6, "y": 27.1, "desc": "室内体育馆"},
            {"name": "运动场（篮球场）", "x": 30.2, "y": 22.9, "desc": "球类场地"},
            {"name": "拓展场地", "x": 39.8, "y": 18.8, "desc": "拓展实训场地"},
            {"name": "松山湖", "x": 36.8, "y": 54.2, "desc": "湖泊"},
            {"name": "文化广场", "x": 24.3, "y": 33.3, "desc": "广场"},
            {"name": "百工桥", "x": 24.3, "y": 56.2, "desc": "景观桥"},
            {"name": "匠心亭", "x": 27.2, "y": 66.7, "desc": "亭子景观"},
            {"name": "校训石刻", "x": 37.6, "y": 78.1, "desc": "景观石刻"},
            {"name": "黄炎培广场", "x": 37.6, "y": 85.4, "desc": "纪念广场"},
            {"name": "松山湖学生公寓", "x": 35.3, "y": 82.3, "desc": "临湖公寓"},
            {"name": "航空实训基地", "x": 50.1, "y": 27.1, "desc": "航空实训场地"},
            {"name": "城市轨道室外综合实训基地", "x": 50.1, "y": 16.7, "desc": "轨道实训场地"},
            {"name": "青春舞台", "x": 30.2, "y": 43.8, "desc": "户外舞台"},

        ]
    },
}


def _jpeg_size(path: Path) -> tuple[int, int]:
    """纯标准库读取 JPEG 尺寸 (width, height)，避免引入 Pillow 依赖。

    非标准 JPEG 或读取失败时退回 4:3 比例，不影响地图渲染。
    """
    try:
        with path.open("rb") as f:
            if f.read(2) != b"\xff\xd8":
                return 4, 3
            while True:
                b = f.read(1)
                while b and b != b"\xff":
                    b = f.read(1)
                marker = f.read(1)
                if marker in (b"\xc0", b"\xc1", b"\xc2", b"\xc3"):
                    f.read(3)
                    h, w = struct.unpack(">HH", f.read(4))
                    return w, h
                ln = struct.unpack(">H", f.read(2))[0]
                f.read(ln - 2)
    except Exception:
        return 4, 3


def _img_data_uri(path: Path) -> str:
    """把图片读成 data URI，内嵌进 Folium HTML，免去静态文件服务。"""
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _rel_to_latlon(bounds: list[list[float]], x: float, y: float) -> tuple[float, float]:
    """把图片内相对坐标 (x%, y%) 映射到图片地理边界的经纬度。

    bounds = [[south, west], [north, east]]；
    图片顶部 = y0 = north，图片左 = x0 = west。
    """
    (south, west), (north, east) = bounds
    lat = north - (y / 100.0) * (north - south)
    lon = west + (x / 100.0) * (east - west)
    return lat, lon


@st.cache_resource(show_spinner="正在加载校园地图…")
def _build_map(campus_key: str) -> folium.Map:
    """构建并缓存单个校区的叠加地图（避免每次交互重绘时反复构建）。"""
    campus = CAMPUSES[campus_key]
    img_path = _ASSET_DIR / campus["image"]
    clat, clon = campus["center"]
    dlat = campus["span_lat"]

    w, h = _jpeg_size(img_path)
    # 保持图片宽高比：经度跨度按纬线缩放换算，避免手绘图被拉伸
    dlon = dlat * (w / h) / math.cos(math.radians(clat))

    south, north = clat - dlat / 2, clat + dlat / 2
    west, east = clon - dlon / 2, clon + dlon / 2
    bounds = [[south, west], [north, east]]

    m = folium.Map(location=campus["center"], zoom_start=16, control_scale=True)
    ImageOverlay(
        image=_img_data_uri(img_path),
        bounds=bounds,
        opacity=1.0,
        interactive=False,
        cross_origin=False,
        zindex=1,
    ).add_to(m)
    m.fit_bounds(bounds)
    return m


def render_campus_map() -> None:
    """在校园地图 tab 中渲染：校区切换 + 手绘地图底图（无标记）。"""
    st.caption("手绘地图可缩放 / 拖拽；右上角可切换校区。")

    campus_key = st.selectbox("选择校区", list(CAMPUSES.keys()), index=0, key="campus_select")
    m = _build_map(campus_key)
    # 用 st.components.v1.html 嵌入 Folium 生成的完整 HTML，
    # 避免 streamlit-folium 自定义组件在 iframe/预览环境里加载失败。
    # key 绑定校区：切换校区 / 切回 tab 时强制重挂载 iframe，避免 srcdoc 不刷新导致空白。
    html = m.get_root().render()
    try:
        st.components.v1.html(
            html, height=520, scrolling=True, key=f"campus_map_{campus_key}"
        )
    except Exception:
        # 兜底：少数环境（如 AppTest 对带 key 的 components 支持不全）无法渲染 iframe，
        # 直接显示手绘原图，保证地图始终可见、不会整片空白。
        img_path = _ASSET_DIR / CAMPUSES[campus_key]["image"]
        st.image(str(img_path), caption=campus_key, use_container_width=True)
