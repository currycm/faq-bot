# -*- coding: utf-8 -*-
"""校园地图（纯前端，无需后端）

用 Folium 渲染交互式校园地图，标注图书馆 / 教学楼 / 食堂等 POI。
坐标目前是**示例占位**（南京市仙林片区），请替换为你的校园真实坐标。

依赖：folium + streamlit-folium（已加入 requirements.txt）
"""
from __future__ import annotations

import streamlit as st
import folium
from streamlit_folium import st_folium


# 示例校园中心点（南京市仙林片区）。⚠️ 占位数据，替换为你的校园真实经纬度。
CAMPUS_CENTER: tuple[float, float] = (32.0545, 118.9023)

# 示例 POI 列表。⚠️ 占位数据：name 改中文、loc 改真实坐标、desc 改简介即可。
CAMPUS_POIS: list[dict] = [
    {"name": "图书馆", "loc": (32.0558, 118.9030), "desc": "开放时间 8:00-22:00，凭校园卡入馆。"},
    {"name": "第一教学楼", "loc": (32.0538, 118.9015), "desc": "公共课与大班课主要教室。"},
    {"name": "学生食堂", "loc": (32.0542, 118.9042), "desc": "一层快餐、二层风味档口。"},
    {"name": "东区宿舍", "loc": (32.0565, 118.9010), "desc": "本科生宿舍区，门禁 23:00。"},
    {"name": "体育馆", "loc": (32.0528, 118.9050), "desc": "体育课与大型活动场地。"},
    {"name": "行政楼", "loc": (32.0550, 118.9028), "desc": "教务处、学工处办公地点。"},
    {"name": "西门", "loc": (32.0535, 118.8990), "desc": "离地铁站最近的大门。"},
]


@st.cache_resource(show_spinner="正在加载地图…")
def _build_map(center: tuple[float, float], zoom: int) -> folium.Map:
    """构建并缓存地图对象（避免每次交互重绘时反复 new Map）。"""
    m = folium.Map(location=center, zoom_start=zoom, control_scale=True)
    for p in CAMPUS_POIS:
        folium.Marker(
            location=p["loc"],
            tooltip=p["name"],
            popup=f"<b>{p['name']}</b><br>{p['desc']}",
        ).add_to(m)
    return m


def render_campus_map() -> None:
    """在校园地图 tab 中渲染交互地图 + 快速定位。"""
    st.caption("点击标记查看简介；用上方下拉框可快速定位到某个地点。")

    names = ["全部"] + [p["name"] for p in CAMPUS_POIS]
    choice = st.selectbox("快速定位", names, index=0, key="map_jump")

    if choice == "全部":
        center, zoom = CAMPUS_CENTER, 16
    else:
        p = next(x for x in CAMPUS_POIS if x["name"] == choice)
        center, zoom = p["loc"], 18

    m = _build_map(center, zoom)
    st_folium(m, height=480, key=f"campus_map_{choice}")
