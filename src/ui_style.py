# -*- coding: utf-8 -*-
"""前端视觉 token 与 CSS 覆盖（v7.1 方案 B：去 Streamlit 默认皮肤）

为什么单独放一个文件：
    app.py 是业务逻辑，一大段 CSS 塞在里面会把真正重要的东西淹掉。
    放在 src/ 下（而不是项目根目录）是因为 Dockerfile 只 COPY api.py / app.py / src/ / data/，
    根目录新建 .py 不会被打进镜像，容器里 import 会炸。

设计原则：
    1. **不加东西，只做减法** —— 去掉 Streamlit 的彩虹条、页脚、彩色气泡、过重描边
    2. **中性色为主** —— 暖灰 #E8E7E3 系，主色用沉稳的蓝而不是 AI 产品爱用的紫
    3. **不写死深色** —— 所有颜色按浅色调（.streamlit/config.toml 锁 base = "light"）。
       要支持深色主题，得把这些硬编码色换成 CSS 变量，别直接改 base。
"""
from __future__ import annotations

import streamlit as st

# 主色：沉稳蓝。不用紫/渐变——那是"AI 产品"的视觉套路
PRIMARY = "#2C6EAB"

CSS = f"""
<style>
/* 去掉顶部那条彩虹渐变（Streamlit 最强识别特征） */
header[data-testid="stHeader"] {{
    background-image: none !important;
    background-color: transparent !important;
}}

/* 去掉底部 "Made with Streamlit" */
[data-testid="stFooter"] {{ display: none !important; }}

/* 正文宽度收到易读区间，别拉满整屏 */
.block-container {{
    max-width: 46rem !important;
    padding-top: 2.5rem !important;
    padding-bottom: 2rem !important;
}}

/* 标题收小。默认 h1 太大，像 landing page 而不是工具 */
h1 {{
    font-size: 22px !important;
    font-weight: 500 !important;
    letter-spacing: -0.01em !important;
}}

/* 中文字体栈：系统默认字体常把中文渲染得发虚 */
html, body, [class*="css"], [data-testid] {{
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC",
                 "Hiragino Sans GB", "Microsoft YaHei", "Segoe UI",
                 sans-serif !important;
}}

/* 聊天气泡：去掉彩色背景，改成细边框。
   用户气泡保留浅灰底做区分，助手气泡白底无底色 */
[data-testid^="stChatMessage"] {{
    background: transparent !important;
    border: 1px solid #E8E7E3 !important;
    border-radius: 10px !important;
    padding: 12px 14px !important;
    margin-bottom: 8px !important;
}}
[data-testid^="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {{
    background: #F7F7F5 !important;
    border-color: transparent !important;
}}

/* 说明文字（来源、提示）：默认太浅，加深一档 */
[data-testid="stCaptionContainer"] {{
    color: #6B6A66 !important;
    font-size: 13px !important;
}}

/* 按钮：统一圆角，描边压淡，字重回归常规 */
[data-testid="stButton"] > button {{
    border-radius: 8px !important;
    border-color: #DDDCD7 !important;
    font-weight: 400 !important;
    transition: border-color 0.15s ease !important;
}}
[data-testid="stButton"] > button:hover {{
    border-color: {PRIMARY} !important;
    color: {PRIMARY} !important;
}}

/* 去掉左上角侧边栏的收起/展开按钮。
   两个都要写：收起后 Streamlit 会把 stSidebarCollapseButton 换成 stExpandSidebarButton，
   只隐藏前者的话，一点侧边栏空白处就会冒出个 ">" 来 */
[data-testid="stSidebarCollapseButton"],
[data-testid="stExpandSidebarButton"] {{
    display: none !important;
}}

/* 高频问题 chip 条（app.py 里 st.container(key="sugbar") 生成的容器）。
   位置在对话下方、输入框上方，做小做轻，别抢答案的戏 */
.st-key-sugbar {{
    border-top: 1px solid #EFEEEA !important;
    padding-top: 8px !important;
    margin-top: 4px !important;
}}
.st-key-sugbar [data-testid="stCaptionContainer"] {{
    font-size: 11px !important;
    color: #A3A29A !important;
}}
/* Streamlit 的按钮默认 min-height 2.5rem，不覆盖就压不下去 */
.st-key-sugbar [data-testid="stButton"] > button {{
    font-size: 12px !important;
    padding: 2px 6px !important;
    min-height: 0 !important;
    height: auto !important;
    line-height: 1.7 !important;
    border-radius: 999px !important;
    border-color: #E8E7E3 !important;
    background: #FFFFFF !important;
    color: #55554F !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
}}
.st-key-sugbar [data-testid="stButton"] > button:hover {{
    background: #F2F7FB !important;
    border-color: {PRIMARY} !important;
    color: {PRIMARY} !important;
}}
/* 行距压缩：默认 1rem 太松，7 个 chip 会占掉小半屏 */
.st-key-sugbar div[data-testid="stVerticalBlock"],
.st-key-sugbar div[data-testid="stHorizontalBlock"] {{
    gap: 0.35rem !important;
}}

/* 输入框 */
[data-testid="stChatInput"] textarea {{
    border-radius: 10px !important;
    border-color: #DDDCD7 !important;
}}

/* 侧边栏底色和主区拉开一点，别两个都是纯白 */
[data-testid="stSidebar"] {{
    background: #FAFAF8 !important;
}}
</style>
"""


def inject() -> None:
    """把 CSS 注入页面。必须在 st.set_page_config() 之后调用，且只调一次。"""
    st.markdown(CSS, unsafe_allow_html=True)
