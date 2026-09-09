# -*- coding: utf-8 -*-
"""校园地图（纯前端，无需后端）— 方案 B：手绘地图图片叠加 + 可点击 POI

实现：
    - 两张手绘地图（天堂校区 / 仙林校区）作为各校区地图底图，用 Folium ImageOverlay 叠加。
    - 图片以 base64 内嵌进地图 HTML，无需静态文件服务器（单进程部署 / HF Spaces 也能用）。
    - POI 用「图片内相对坐标 (x%, y%)」定义，自动映射到图片地理边界，
      保证红色标记精确落在手绘图对应位置，与真实经纬度解耦。

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
from streamlit_folium import st_folium

_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "campus_maps"

# 每个校区：图片文件名、地理中心(估算)、图片地理半跨度、POI 列表。
# POI 的 (x, y) 为图片内百分比：x 0→左 100→右，y 0→上 100→下。
CAMPUSES: dict[str, dict] = {
    "天堂校区": {
        "image": "campus_tiantang.jpg",
        "center": (32.072, 118.764),   # ⚠️ 估算：南京工业职业技术大学天堂校区附近，请校准
        "span_lat": 0.006,             # 图片覆盖约 ±0.006° 纬度 ≈ 1.3km
        "pois": [
            # 示例标记：请按手绘图替换为真实地标（名称 + x/y 位置 + 简介）
            {"name": "示例·南门", "x": 50, "y": 92, "desc": "（示例标记，请按手绘图位置替换）"},
        ],
    },
    "仙林校区": {
        "image": "campus_xianlin.jpg",
        "center": (32.115, 118.918),   # ⚠️ 估算：南京工业职业技术大学仙林校区附近，请校准
        "span_lat": 0.006,
        "pois": [
            {"name": "示例·南门", "x": 50, "y": 92, "desc": "（示例标记，请按手绘图位置替换）"},
        ],
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

    for p in campus["pois"]:
        lat, lon = _rel_to_latlon(bounds, p["x"], p["y"])
        folium.Marker(
            location=(lat, lon),
            tooltip=p["name"],
            popup=f"<b>{p['name']}</b><br>{p.get('desc', '')}",
            icon=folium.Icon(color="red", icon="info-sign"),
        ).add_to(m)
    return m


def render_campus_map() -> None:
    """在校园地图 tab 中渲染：校区切换 + 手绘地图叠加 + 可点击 POI。"""
    st.caption("手绘地图可缩放 / 拖拽；点击红色标记查看地点简介，右上角可切换校区。")

    campus_key = st.selectbox("选择校区", list(CAMPUSES.keys()), index=0, key="campus_select")
    m = _build_map(campus_key)
    st_folium(m, height=520, key=f"campus_map_{campus_key}", use_container_width=True)

    with st.expander("如何补充 / 修改地标（POI）"):
        st.markdown(
            "打开 `src/campus_map.py`，在对应校区的 `pois` 列表里按格式添加：\n"
            "```python\n"
            '{"name": "图书馆", "x": 35, "y": 40, "desc": "开放时间 8:00-22:00"}\n'
            "```\n"
            "`x` / `y` 是手绘图上的百分比位置（x:0=左 100=右，y:0=上 100=下），与真实经纬度无关。"
        )
