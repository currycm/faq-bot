# -*- coding: utf-8 -*-
"""v7.1 前端界面测试（用 Streamlit 官方 AppTest，无需启动服务器）

运行：
    python tests/test_ui.py

AppTest 会真实执行一遍 app.py 的渲染逻辑，能抓到：
    - Python 运行时异常
    - 组件是否按预期渲染
    - 交互（点按钮）后的状态变化

!! 需要后端在跑：docker compose up -d（或 uvicorn api:app --port 8000）
   后端不可用时整组测试自动 skip（而不是误报失败）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
import requests  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

API_BASE = "http://127.0.0.1:8000"


def _backend_ready() -> bool:
    try:
        r = requests.get(f"{API_BASE}/health", timeout=3)
        return bool(r.json().get("ready"))
    except Exception:
        return False


requires_backend = pytest.mark.skipif(
    not _backend_ready(),
    reason=f"后端未就绪（{API_BASE}/health），跳过前端测试",
)


def _main_text(at) -> str:
    """主区所有 markdown + caption 拼成一个字符串。

    !! 必须排除注入的 <style> 块：CSS 里有 border-radius、0.8 之类字样，
       会把「来源不用 HTML 徽章」「调试字段不外泄」两条断言误伤成红灯。
    """
    md = " ".join(m.value for m in at.main.markdown if "<style" not in m.value)
    cap = " ".join(c.value for c in at.main.caption)
    return md + "\n" + cap


@requires_backend
def test_initial_render():
    """首次打开：无异常 + 有 7 条推荐问题。"""
    print("=" * 60)
    print("测试 1：首次渲染")
    print("=" * 60)

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300)
    at.run()

    if at.exception:
        print(f"  渲染异常：{at.exception}")
        raise AssertionError("app.py 渲染报错")

    print("  无渲染异常")
    titles = [t.value for t in at.title]
    print(f"  标题：{titles}")

    # 标题不该出现 AI 味词汇和技术栈
    head = " ".join(titles + [c.value for c in at.main.caption])
    for noise in ("智能", "助手", "FastAPI", "v7"):
        assert noise not in head, f"标题区不该出现 {noise!r}（那是对开发说的话）"

    labels = [b.label for b in at.button]
    suggested = [l for l in labels if l not in ("重新加载语料", "清空对话", "有用", "没用")]
    print(f"  推荐问题按钮 ({len(suggested)} 个)：")
    for q in suggested:
        print(f"    - {q}")

    assert len(suggested) >= 7, f"推荐问题不足 7 条，只有 {len(suggested)} 条"
    print(f"\n  首次渲染通过，推荐问题 {len(suggested)} 条\n")


@requires_backend
def test_source_lines():
    """提问后：答案渲染 + 来源说明正确。

    v7.1 起来源从「彩色徽章」改成「一行灰字」，文案也变了。
    """
    print("=" * 60)
    print("测试 2：来源说明")
    print("=" * 60)

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300)
    at.run()

    cases = [
        ("图书馆几点开门", "来自知识库"),
        ("北京今天天气怎么样", "实时数据"),
    ]

    prev_len = 0
    for q, expect in cases:
        at.chat_input[0].set_value(q).run()
        if at.exception:
            raise AssertionError(f"提问 {q!r} 时报错：{at.exception}")

        # 只看本次新增的部分，避免上一条消息的来源说明干扰
        combined = _main_text(at)
        new_part = combined[prev_len:]
        prev_len = len(combined)

        print(f"  问题：{q!r} → 期望来源含 {expect!r}")
        assert expect in new_part, f"{q!r} 的来源说明里没有 {expect!r}\n新增文本：{new_part}"

    print("\n  来源说明渲染正常\n")


@requires_backend
def test_no_badge_html():
    """防回归：来源不能用 HTML 徽章，必须是纯文本 caption。

    徽章方案的问题：写死颜色、深浅主题不适配、需要 unsafe_allow_html。
    """
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300)
    at.run()
    at.chat_input[0].set_value("图书馆几点开门").run()

    for m in at.main.markdown:
        if "<style" in m.value:
            continue
        assert "border-radius" not in m.value, "来源说明不该再用 HTML 徽章样式"
        assert "<span" not in m.value, "来源说明不该再用 HTML 标签"

    print("  来源已是纯文本，未使用 HTML 徽章")


@requires_backend
def test_theme_injected():
    """防回归：自定义 CSS 必须被注入（否则页面退回 Streamlit 默认皮肤）。"""
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300)
    at.run()

    styles = [m.value for m in at.markdown if "<style" in m.value]
    assert styles, "没有注入任何自定义 CSS"

    css = styles[0]
    for key in (
        "stHeader",           # 去顶部彩虹条
        "stFooter",           # 去 Made with Streamlit
        "st-key-qa_ask_",     # 提问气泡（靠右）
        "st-key-qa_answer_",  # 回答气泡（靠左）
        "st-key-qa_history",  # 对话区整体滚动容器
        "stSidebarCollapseButton",  # 去左上角收起栏
        "st-key-sugbar",      # 高频问题 chip 条
    ):
        assert key in css, f"CSS 里缺少针对 {key} 的覆盖规则"

    # 左右分栏靠 margin 自动值实现（不依赖父级 flex，DOM 换版本不会静默失效）
    assert "margin-left: auto" in css, "提问气泡没有靠右（缺 margin-left:auto）"
    assert "margin-right: auto" in css, "回答气泡没有靠左（缺 margin-right:auto）"

    # 收起后按钮会换成 stExpandSidebarButton，只隐藏前者会漏
    assert "stExpandSidebarButton" in css, "侧边栏展开按钮没隐藏，收起后会冒出来"

    print(f"  自定义 CSS 已注入（{len(css)} 字符）")


@requires_backend
def test_debug_hidden_by_default():
    """防回归：默认不能出现调试字段（trace_id / 相似度 / 候选分数）。

    这些是给开发排查用的，设 FAQ_DEBUG=1 才该显示。
    """
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300)
    at.run()
    at.chat_input[0].set_value("图书馆几点开门").run()
    at.chat_input[0].set_value("怎么申请助学贷款").run()

    combined = _main_text(at)
    for noise in ("trace_id", "相似度", "耗时", "0.9", "0.8"):
        assert noise not in combined, f"默认界面不该出现调试字段 {noise!r}"

    print("  调试信息默认已隐藏")


@requires_backend
def test_debug_shown_when_enabled():
    """正向：设 FAQ_DEBUG=1 时调试面板必须出现。

    2026-09 修复：此前只有上面那条负向断言（默认不出现），
    _DEBUG_ENABLED 逻辑写反、永远 False 也测不出来 —— 补这条互补。
    FAQ_DEBUG 是进程环境变量，run 前设好、finally 里清掉。
    （不用 monkeypatch：本文件支持 `python tests/test_ui.py` 直跑，
      直接调用时拿不到 fixture。）
    """
    import os

    os.environ["FAQ_DEBUG"] = "1"
    try:
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300)
        at.run()
        at.chat_input[0].set_value("图书馆几点开门").run()

        combined = _main_text(at)
        assert "trace_id" in combined, "FAQ_DEBUG=1 时调试面板未出现"
    finally:
        os.environ.pop("FAQ_DEBUG", None)

    print("  FAQ_DEBUG=1 时调试信息已显示")


def test_suggestions_above_input():
    """防回归：7 个高频问题必须渲染在输入栏上方（代码顺序 = 视觉顺序）。

    !! 重要：app.py 用 st.tabs 把问答拆成了 tab。在 st.tabs 内部，
    st.chat_input **不会**浮动到底部固定容器，而是按代码顺序内联渲染。
    因此视觉上要让输入栏落在最底端，它必须是 tab 内脚本的最后一个元素，
    _render_suggestions()（紧贴输入框上方）排在其前。

    另外校验 container key 和 CSS 类名是配套的 —— 改了 key 忘了改 CSS，
    chip 样式会静默失效（跟主色要在 config.toml 和 ui_style.py 两处同步是同类坑）。
    """
    src = (ROOT / "app.py").read_text(encoding="utf-8").splitlines()

    # 只看真正的代码行：注释和 def 行里也会出现这些名字
    def _code_line(needle: str):
        return next(
            (
                i
                for i, l in enumerate(src)
                if needle in l and not l.strip().startswith(("#", "def", '"', "见"))
            ),
            None,
        )

    chat_line = _code_line("st.chat_input(")
    sug_line = _code_line("_render_suggestions()")
    assert chat_line is not None, "找不到 st.chat_input"
    assert sug_line is not None, "找不到 _render_suggestions() 的调用"
    # 在 st.tabs 内 chat_input 不浮动，必须排在最后才视觉置底；
    # 推荐问题区(_render_suggestions)在它之前 → 紧贴输入框上方。
    assert chat_line > sug_line, (
        f"st.chat_input（第 {chat_line + 1} 行）必须在 "
        f"_render_suggestions()（第 {sug_line + 1} 行）之后，否则在 st.tabs 内"
        f"输入栏不会落在底端"
    )

    # key 与 CSS 类名配套
    m = re.search(r'st\.container\(key="([^"]+)"\)', "\n".join(src))
    assert m, "推荐区没有用 st.container(key=...) 包起来，CSS 无法只作用于这一组按钮"
    key = m.group(1)
    from src import ui_style

    assert f".st-key-{key}" in ui_style.CSS, (
        f"ui_style.py 里缺少 .st-key-{key} 的样式规则"
    )

    print(f"  推荐区位置正确（第 {sug_line + 1} 行 > 输入栏第 {chat_line + 1} 行），key={key}")


def test_single_scroll_layer_and_no_collapse():
    """防回归：滚动只保留最外层（对话区），单条消息不滚、问答也不折叠。

    历史上踩过的坑：给提问/回答正文各加了 max-height + overflow-y:auto，
    一屏里挂好几个滚动条，滚轮滚哪个得看光标位置，很难用。
    """
    from src import ui_style

    assert ui_style._BOXES == ('[class*="st-key-qa_history"]',), (
        "可滚动容器应只剩对话区一个，实际：" f"{ui_style._BOXES}"
    )

    src = (ROOT / "app.py").read_text(encoding="utf-8")
    for label in ('st.expander("提问"', 'st.expander("回答"'):
        assert label not in src, f"问答仍被折叠（{label}），应改为完整展示"

    # 左右分栏的容器 key 必须存在，否则 CSS 选不中
    for key in ("qa_ask_", "qa_answer_"):
        assert key in src, f"app.py 里没有 {key} 容器，气泡样式会静默失效"

    print("  滚动仅一层，问答不再折叠")


@requires_backend
def test_feedback_button():
    """点"有用"后：写入反馈日志 + 按钮变为已反馈状态。"""
    print("=" * 60)
    print("测试 3：反馈按钮")
    print("=" * 60)

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300)
    at.run()

    at.chat_input[0].set_value("图书馆几点开门").run()

    up_btns = [b for b in at.button if b.label == "有用"]
    assert up_btns, "没有找到『有用』按钮"
    print(f"  找到『有用』按钮 {len(up_btns)} 个")

    up_btns[0].click().run()

    if at.exception:
        raise AssertionError(f"点击反馈按钮报错：{at.exception}")

    combined = _main_text(at)
    assert "已反馈" in combined, "点击后未显示已反馈状态"
    print("  点击后显示：已反馈")

    # 验证真的写进了日志文件
    from src import logger

    stats = logger.summarize_feedback()
    print(f"  反馈统计：{stats}")
    assert stats["total"] > 0, "反馈没有写入日志文件"
    print(f"\n  反馈闭环正常，累计 {stats['total']} 条反馈\n")


if __name__ == "__main__":
    test_initial_render()
    test_source_lines()
    test_no_badge_html()
    test_debug_hidden_by_default()
    test_debug_shown_when_enabled()
    test_feedback_button()
    print("=" * 60)
    print("  前端测试全部通过")
    print("=" * 60)
