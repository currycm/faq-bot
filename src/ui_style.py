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

# 需要"可垂直滚动"的容器 —— 只留最外层一个：
#   qa_history  — 整个对话区（消息多了整体上下滚动）
#
# 为什么单条消息不各自滚了：
#   上一版给提问/回答正文各加了 max-height + overflow-y:auto，
#   结果一屏里同时挂着好几个滚动条，滚轮滚到哪个得看光标停在谁上面，
#   稍不留神就把里层滚到底、外层纹丝不动，很难用。
#   现在只保留最外层滚动，滚轮行为唯一、可预期。
_BOXES = ('[class*="st-key-qa_history"]',)


def sel(pseudo: str = "") -> str:
    """拼出选择器列表，可带伪元素/伪类。

    ⚠️ 这里必须**逐个**拼接，不能写成 `A, B::x {}`：
       选择器列表里的伪元素只作用于它紧跟的那个选择器，前面的会被当成
       普通元素、白白吃下伪元素的样式。实测把 `::-webkit-scrollbar{width:8px}`
       写成列表形式后，没带伪元素的那个容器真的被设成了 width:8px，
       正文被挤成一个字一行的竖排（加上 8px padding 正好 16px 宽）。
    """
    return ",\n".join(b + pseudo for b in _BOXES)

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

/* ---- 左右分栏对话气泡 ----
   提问靠右、回答靠左，像常见 IM 那样一眼分得清谁说的。
   实现只用 margin 自动值 + fit-content 宽度，不依赖父级是不是 flex ——
   Streamlit 内部 DOM 层级换版本就可能变，用 flex 属性（align-self）
   绑死在某层上，升级一次就静默失效一次。
   靠右：margin-left:auto 吃掉左侧所有剩余空间；靠左：margin-right:auto。
   宽度 fit-content 让短消息收缩成小气泡，max-width 兜住长消息的换行。 */

/* 对话区：整段对话的唯一滚动容器，行距压紧一点，别让气泡飘得太散 */
[class*="st-key-qa_history"] {{
    gap: 0.5rem !important;
}}

/* 提问气泡 */
[class*="st-key-qa_ask_"] {{
    width: fit-content;
    max-width: 76%;
    margin-left: auto;
    background: #EEF4FA;
    border-radius: 14px 14px 4px 14px;
    padding: 10px 14px;
    gap: 0.15rem !important;
}}

/* 回答气泡 */
[class*="st-key-qa_answer_"] {{
    width: fit-content;
    max-width: 84%;
    margin-right: auto;
    background: #FFFFFF;
    border: 1px solid #E8E7E3;
    border-radius: 14px 14px 14px 4px;
    padding: 10px 14px;
    gap: 0.15rem !important;
}}

/* 附属操作区（候选问题 / 调试 / 反馈）：贴在该轮回答下方，占满整行，
   不然里面的 st.columns 会被 fit-content 挤成窄条 */
[class*="st-key-qa_meta_"] {{
    margin-left: 2px;
    margin-bottom: 10px;
}}

/* 气泡内那句话（提问/回答）本来就叫「提问」「回答」，比正文再浅一档，
   和来源说明同色同级，不跟内容抢注意力 */
[class*="st-key-qa_ask_"] [data-testid="stCaptionContainer"],
[class*="st-key-qa_answer_"] [data-testid="stCaptionContainer"] {{
    font-size: 12px !important;
    color: #8A8981 !important;
}}

/* 窄屏：气泡占宽放宽，但别顶满，留出左右对比的余地 */
@media (max-width: 640px) {{
    [class*="st-key-qa_ask_"] {{ max-width: 88%; }}
    [class*="st-key-qa_answer_"] {{ max-width: 92%; }}
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

/* ---- 可折叠问答块（提问 / 回答） ----
   用原生 st.expander：它的开合由 React 管理，内部按钮/输入仍可用；
   纯 HTML 折叠面板做不到这点（自绘 DOM 里放不了 Streamlit 组件）。 */

/* 图标兜底：折叠箭头是 Material Symbols 连字（keyboard_arrow_right/down，
   DOM 里 data-testid="stIconMaterial"）。浏览器一旦没把字体应用到该 span
   （离线/受限环境实测会复现），连字会以原文渲染并和标题叠成一团
   （"key提问art...down"）。这里隐藏图标字符、改用纯 CSS 画箭头 ——
   不依赖任何字体文件，什么环境都一致。 */
[data-testid="stExpander"] summary [data-testid="stIconMaterial"] {{
    visibility: hidden !important;
}}
[data-testid="stExpander"] summary {{
    position: relative !important;
    padding-right: 30px !important;
}}
[data-testid="stExpander"] summary::after {{
    content: "";
    position: absolute;
    right: 12px;
    top: 50%;
    width: 7px;
    height: 7px;
    border-right: 2px solid #6B6A66;
    border-bottom: 2px solid #6B6A66;
    transform: translateY(-50%) rotate(-45deg);   /* 收起：指向右 */
    transition: transform 0.2s ease;
}}
[data-testid="stExpander"] details[open] summary::after {{
    transform: translateY(-50%) rotate(45deg);    /* 展开：指向下 */
}}

[data-testid="stExpander"] > details > div {{
    animation: qaFade 0.22s ease-out;
}}
@keyframes qaFade {{
    from {{ opacity: 0; transform: translateY(-4px); }}
    to   {{ opacity: 1; transform: none; }}
}}
/* 尊重系统「减少动态效果」偏好 */
@media (prefers-reduced-motion: reduce) {{
    [data-testid="stExpander"] > details > div {{ animation: none !important; }}
}}
/* 键盘可达：Streamlit 默认焦点环很弱，这里补一个清晰的 */
[data-testid="stExpander"] summary:focus-visible {{
    outline: 2px solid {PRIMARY} !important;
    outline-offset: 2px !important;
    border-radius: 8px !important;
}}
[data-testid="stExpander"] summary:hover {{
    background: #F7F7F5 !important;
    border-radius: 8px !important;
}}
/* 窄屏：标题允许换行，别被裁掉一截 */
@media (max-width: 640px) {{
    [data-testid="stExpander"] summary p {{
        white-space: normal !important;
        font-size: 13px !important;
    }}
}}

/* ---- 限高滚动容器 ----
   app.py 用 st.container(key=...) 给容器起名，Streamlit 会把它渲染成
   class="st-key-<key>"，正好拿来精准选中（不用 :has()，也不用 nth-child）。

   只有一层滚动：st-key-qa_history 整个对话区 —— 消息多了整体上下滚。
   单条提问/回答不再限高、不再自带滚动条（见文件上方 _BOXES 的说明）。

   用 max-height 而不是固定 height：内容短时高度由内容决定，
   不出现滚动条、也不留一大片空白；超出上限才可滚。 */
{sel()} {{
    overflow-y: auto;
    overflow-x: hidden;
    /* 滚到头再滚时不要把滚动传给外层，避免"滚着滚着整页跳走" */
    overscroll-behavior: contain;
    /* 给滚动条留呼吸位，内容不贴边 */
    padding-right: 8px;
    /* 触屏惯性滚动 */
    -webkit-overflow-scrolling: touch;
    /* 关键：Streamlit 全局注入了一段 `@supports (scrollbar-color:transparent
       transparent)` 规则，把 scrollbar-width 设成 thin、scrollbar-color 设成
       transparent（含 hover 态），作用在通配选择器上。
       而 Chromium 的规则是——标准属性只要不是 auto，就**忽略 ::-webkit-scrollbar**。
       不覆盖它，下面那套自定义滚动条一行都不会生效（实测退化成会自动隐藏的原生条，
       gutter 为 0、看起来像没有滚动条）。这里显式改回 auto，把控制权交还伪元素。 */
    scrollbar-width: auto !important;
    scrollbar-color: auto !important;
}}
/* 整个对话区的可视高度上限。
   用 min(68vh, 620px)：矮屏按比例、大屏不无限拉长，
   桌面端后面还有常见问题条和输入框，对话区太贪心会把它们挤出视口。 */
[class*="st-key-qa_history"] {{
    max-height: min(68vh, 620px);
}}
/* WebKit 滚动条：细、圆角、暖灰，和整体中性色一致。
   透明边框 + background-clip: content-box 让滑块比轨道窄一档，视觉更轻。 */
{sel("::-webkit-scrollbar")} {{
    width: 8px;
}}
{sel("::-webkit-scrollbar-track")} {{
    background: transparent;
}}
{sel("::-webkit-scrollbar-thumb")} {{
    background: #D6D4CE;
    border: 2px solid transparent;
    background-clip: content-box;
    border-radius: 8px;
}}
{sel("::-webkit-scrollbar-thumb:hover")} {{
    background: #B9B7B0;
    background-clip: content-box;
}}
/* Firefox 没有 ::-webkit-scrollbar，改用标准属性画细滚动条。
   踩过的坑：Chromium(≥121) 一旦看到 scrollbar-width/color 就**忽略**
   上面那些 ::-webkit-scrollbar 规则，退回成会自动隐藏的原生滚动条。
   而 `@supports not selector(::-webkit-scrollbar)` 并不能区分浏览器——
   Chromium 同样不支持该选择器，判断结果为真，等于白写。
   所以用 Firefox 专属的 -moz-appearance 做特性查询，只在 Firefox 生效。 */
@supports (-moz-appearance: none) {{
    {sel()} {{
        scrollbar-width: thin !important;
        scrollbar-color: #D6D4CE transparent !important;
    }}
}}
/* 平滑滚动。滚轮本身由浏览器接管，这条主要让程序化滚动/锚点跳转也顺滑 */
@media (prefers-reduced-motion: no-preference) {{
    {sel()} {{
        scroll-behavior: smooth;
    }}
}}

/* ---- 窄屏 / 矮屏适配 ----
   手机竖屏视口高，68vh 够用；横屏手机（高度常 <560px）连 68vh 也偏大，
   会让下面的输入框被挤出屏幕，所以单独压一档。 */
@media (max-width: 640px) {{
    [class*="st-key-qa_history"] {{
        max-height: 62vh;
        padding-right: 4px;      /* 窄屏省一点水平空间 */
    }}
}}
@media (max-height: 560px) {{
    [class*="st-key-qa_history"] {{
        max-height: 46vh;
    }}
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
