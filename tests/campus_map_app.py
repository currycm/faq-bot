# -*- coding: utf-8 -*-
"""最小 app fixture：仅渲染校园地图，供 test_campus_map.py 做无后端冒烟测试。

不加载 FaqBot / BGE，因此运行快、不依赖网络，专门用于验证地图叠加与 POI 渲染。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from src.campus_map import render_campus_map

st.set_page_config(page_title="校园地图测试")
render_campus_map()
