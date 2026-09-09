# -*- coding: utf-8 -*-
"""校园地图（方案 B：手绘地图图片叠加 + 可点击 POI）渲染测试。

纯前端、不依赖后端 / 网络 / BGE，用于验证：
    - 手绘地图图片能成功以 base64 内嵌并叠加到 Folium 地图
    - 双校区切换下拉正常渲染
    - 渲染过程不抛异常
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402


def test_campus_map_renders():
    at = AppTest.from_file(str(ROOT / "tests" / "campus_map_app.py"), default_timeout=120)
    at.run()

    assert not at.exception, f"校园地图渲染异常：{at.exception}"

    # 校区切换下拉应存在
    assert any(s.label == "选择校区" for s in at.selectbox), "未渲染校区选择下拉"

    # 两个校区都能切换且不报错
    campus_box = next(s for s in at.selectbox if s.label == "选择校区")
    campus_box.set_value("仙林校区").run()
    assert not at.exception, f"切换到仙林校区后渲染异常：{at.exception}"

    print("校园地图渲染正常：校区下拉存在、双校区切换无异常")
