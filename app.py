# -*- coding: utf-8 -*-
"""Streamlit 网页入口（v7.1）

启动：
    1) 先启动 FastAPI 后端：uvicorn api:app --port 8000
    2) 再启动前端：      streamlit run app.py

排查问题时在 URL 后加 ?debug=1 可显示调试信息（trace_id / 相似度 / 候选列表）。

--------------------------------------------------------------------------
v7.1 改动：前端去 AI 味 / 信息降噪

核心判断：**调试信息不是给用户的**。
    trace_id、相似度分数、候选进度条、意图数、vectorizer 全部默认隐藏，
    只有 ?debug=1 时才显示。之前一条回答叠 5 层，其中 3 层学生根本不看。

其余改动：
    1. 标题去掉 emoji 和技术栈（"v7 (FastAPI 后端)" 是写给开发看的）
    2. 5 色徽章 → 一行灰字来源说明（st.caption，自动适配深浅主题，零 HTML）
    3. AI 生成的橙色警示色块删掉 —— 和徽章说的是同一句话，只留一处
    4. 候选从「进度条 + 三位小数」改成「你可能还想问」的可点按钮
    5. 文案去客服腔：「正在思考…」→「查询中」，
       「已收到反馈，我们会改进」→ toast「谢谢」（不再在版面里残留）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests
import streamlit as st

from src import config, logger, ui_style


# ---------------------------------------------------------------- 来源说明
# 五个来源只保留**一行灰字**，不再做彩色徽章。
# 用 st.caption（而不是 markdown + HTML）好处：
#   - 自动适配深浅主题，不用写死颜色
#   - 不需要 unsafe_allow_html，少一个注入面
def source_of(r: dict) -> tuple[str, str]:
    """判断回答来源，返回 (kind, 给用户看的一行说明)。"""
    if r.get("matched"):
        return "kb", "来自知识库"

    fb = r.get("fallback") or {}
    ftype = fb.get("type", "")
    fsrc = fb.get("source", "")

    if ftype == "realtime":
        return "api", "实时数据 · 和风天气" if fsrc == "weather" else "实时数据"
    if fsrc == "llm":
        return "llm", "AI 生成 · 非官方答复"
    if ftype == "chat":
        return "chat", ""
    if ftype == "campus_only":
        return "none", "这个问题建议直接问相关部门"
    return "none", "知识库暂未收录"


def _debug_mode() -> bool:
    """URL 带 ?debug=1 才显示调试信息。

    st.query_params 在 1.30+ 才稳定，老版本回退到 experimental 接口。
    """
    try:
        return st.query_params.get("debug") == "1"
    except Exception:
        try:
            return st.experimental_get_query_params().get("debug", [""])[0] == "1"
        except Exception:
            return False


def render_candidates(r: dict) -> None:
    """调试模式下的候选列表（进度条 + 分数）。平时不显示。"""
    for c in r.get("candidates", []):
        col_q, col_s = st.columns([4, 1])
        with col_q:
            st.caption(c["question"])
        with col_s:
            st.caption(f"{c['score']:.3f}")
        st.progress(min(max(c["score"], 0.0), 1.0))


# ---------------------------------------------------------------- API 客户端
API_BASE = os.environ.get("FAQ_API_BASE", "http://127.0.0.1:8000")

# 未设置 FAQ_API_BASE 时（例如 Hugging Face Spaces 单进程部署），
# 直接在进程内调用 FaqBot，而不是发 HTTP 请求到独立后端。
_USE_LOCAL_BOT = not os.environ.get("FAQ_API_BASE")


@st.cache_resource(show_spinner="正在加载模型…")
def _get_bot():
    """懒加载并缓存 FaqBot 单例（首次调用时构建向量索引 + 加载 BGE）。"""
    from src.agent import FaqBot
    return FaqBot()


@st.cache_data(ttl=10)
def api_health() -> dict:
    """读 /health（有后端时）或检查进程内模型（无后端时），缓存 10 秒。"""
    if _USE_LOCAL_BOT:
        try:
            _get_bot()
            return {"status": "ok", "ready": True}
        except Exception as exc:
            return {"status": "error", "ready": False, "detail": str(exc)}
    try:
        r = requests.get(f"{API_BASE}/health", timeout=3)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"status": "error", "ready": False, "detail": str(exc)}


@st.cache_data(ttl=60)
def api_suggest() -> list[str]:
    """读 /suggest（有后端时）或直接取进程内推荐（无后端时），缓存 60 秒。"""
    if _USE_LOCAL_BOT:
        try:
            return _get_bot().suggest_questions()
        except Exception:
            return list(config.MANUAL_SUGGESTED_QUESTIONS)
    try:
        r = requests.get(f"{API_BASE}/suggest", timeout=3)
        r.raise_for_status()
        return r.json().get("questions", [])
    except Exception:
        return list(config.MANUAL_SUGGESTED_QUESTIONS)


def api_ask(query: str, user_id: str) -> dict:
    """调 /ask（有后端时）或进程内直答（无后端时）。失败时返回错误 dict。"""
    if _USE_LOCAL_BOT:
        try:
            return _get_bot().ask(query, user_id=user_id)
        except Exception as exc:
            return {
                "answer": "服务暂时不可用，请稍后再试。",
                "matched": False,
                "tag": None,
                "score": 0.0,
                "fallback": {"type": "error", "source": "fixed_api_down", "rule": ""},
                "candidates": [],
                "latency_ms": 0,
                "trace_id": "n/a",
                "vectorizer": "",
                "_error": str(exc),
            }
    try:
        r = requests.post(
            f"{API_BASE}/ask",
            json={"query": query, "user_id": user_id},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as exc:
        # 网络/服务挂了的兜底 — 一定要返回 dict 让前端渲染不崩
        return {
            "answer": "服务暂时不可用，请稍后再试。",
            "matched": False,
            "tag": None,
            "score": 0.0,
            "fallback": {"type": "error", "source": "fixed_api_down", "rule": ""},
            "candidates": [],
            "latency_ms": 0,
            "trace_id": "n/a",
            "vectorizer": "",
            "_error": str(exc),
        }


@st.cache_data(ttl=15)
def _feedback_stats() -> dict:
    return logger.summarize_feedback()


def _render_suggestions() -> None:
    """高频问题 chip 条。

    位置说明（这里有个反直觉的点）：
        st.chat_input 无论写在脚本的哪一行，Streamlit 都会把它塞进页面底部的
        固定容器，视觉上永远在最底下。所以这个函数放在渲染流程的最后一句，
        出来的效果就是「紧贴输入框上方」——正是我们想要的位置。

    为什么常驻而不是只在首屏显示：
        学生问完一个之后，往往紧接着还要问下一个（查完图书馆还想查宿舍）。
        放在首屏的话，问完一次就被对话顶走了，还得重新滚动。
    """
    suggestions = api_suggest()[: config.SUGGEST_COUNT]
    if not suggestions:
        return

    # key="sugbar" 会让 Streamlit 给容器加上 class="st-key-sugbar"，
    # CSS 才能只挑这一组按钮做 chip 样式，不影响页面上其他按钮。
    with st.container(key="sugbar"):
        st.caption("常见问题")
        for row in (suggestions[:4], suggestions[4:]):
            if not row:
                continue
            cols = st.columns(len(row))
            for col, q in zip(cols, row):
                with col:
                    if st.button(q, key=f"sug_{q}", use_container_width=True):
                        st.session_state.pending_query = q
                        st.rerun()


def main() -> None:
    # 无 emoji、无技术栈：学生不关心我们用了 FastAPI
    st.set_page_config(page_title="校园问答", page_icon=None)
    ui_style.inject()
    st.title("校园问答")
    st.caption("南京工业职业技术大学")

    DEBUG = _debug_mode()

    # ---------------------------------------------------------- 后端健康检查
    health = api_health()
    if not health.get("ready"):
        st.error("服务暂时不可用，请稍后再试。")
        if DEBUG:
            st.caption(
                f"API：{API_BASE} ｜ status={health.get('status', 'unknown')} ｜ "
                f"{health.get('detail', '')}"
            )
        st.stop()

    # 注：这里原本有个侧边栏（运行状态 / 反馈统计），已删除 —— 学生用不到，
    # 还白白占着左侧一栏。反馈统计挪到了页面底部，?debug=1 才显示。

    # ---------------------------------------------------------- 会话状态
    if "history" not in st.session_state:
        st.session_state.history = []

    # ---------------------------------------------------------- 首次引导
    # 只留一句说明。推荐问题不再放这里 —— 见文件末尾的 _render_suggestions()
    if not st.session_state.history:
        st.caption("答案来自学校通知；知识库没有的会如实告诉你，不会编。")

    # ---------------------------------------------------------- 提问
    query = st.chat_input("问点什么？比如：图书馆几点关门")
    if not query:
        query = st.session_state.pop("pending_query", None)

    if query:
        # LLM 兜底要 1~3 秒，spinner 让用户知道在处理。
        # 文案用中性的「查询中」而不是「正在思考…」——后者是拟人化 AI 味。
        with st.spinner("查询中"):
            result = api_ask(query, user_id="streamlit_user")
        st.session_state.history.append((query, result))

    # ---------------------------------------------------------- 渲染对话
    for i, (q, r) in enumerate(st.session_state.history):
        with st.chat_message("user"):
            st.write(q)

        with st.chat_message("assistant"):
            kind, source_line = source_of(r)

            st.write(r["answer"])

            # 来源：一行灰字，替代原来的彩色徽章 + 匹配度百分比
            if source_line:
                st.caption(source_line)

            # 未命中时把候选题变成「你可能还想问」的可点按钮，
            # 替代原来的「进度条 + 三位小数」——学生看不懂 0.872 是什么意思
            if not r.get("matched") and r.get("candidates"):
                st.caption("你可能还想问")
                cands = r["candidates"][:3]
                cols = st.columns(len(cands))
                for col, c in zip(cols, cands):
                    with col:
                        key = f"cand_{i}_{c['question']}"
                        if st.button(c["question"], key=key, use_container_width=True):
                            st.session_state.pending_query = c["question"]
                            st.rerun()

            # 调试信息：只在 ?debug=1 时出现
            if DEBUG:
                with st.expander("调试信息"):
                    st.caption(
                        f"trace_id: `{r.get('trace_id', 'n/a')}` ｜ "
                        f"耗时 {r.get('latency_ms', 0):.0f} ms"
                    )
                    if r.get("matched"):
                        st.caption(
                            f"命中意图 `{r.get('tag')}` ｜ "
                            f"相似度 {r.get('score', 0):.3f}"
                        )
                    else:
                        st.caption(
                            f"未命中 ｜ 最高相似度 {r.get('score', 0):.3f}"
                            f"（阈值 {config.SIMILARITY_THRESHOLD}）"
                        )
                    render_candidates(r)

            # 反馈：用 toast，不在版面里残留「已收到反馈，我们会改进」
            fb_key = f"fb_{i}"
            if fb_key in st.session_state:
                st.caption("已反馈")
            else:
                c_up, c_down, _ = st.columns([0.9, 0.9, 8])
                with c_up:
                    if st.button("有用", key=f"up_{i}"):
                        logger.log_feedback(r, "up")
                        st.session_state[fb_key] = "up"
                        st.toast("谢谢")
                        st.rerun()
                with c_down:
                    if st.button("没用", key=f"down_{i}"):
                        logger.log_feedback(r, "down")
                        st.session_state[fb_key] = "down"
                        st.toast("谢谢，我们会改进")
                        st.rerun()

    # ---------------------------------------------------------- 清空
    if st.session_state.history:
        if st.button("清空对话"):
            st.session_state.history = []
            for k in [k for k in st.session_state if k.startswith("fb_")]:
                del st.session_state[k]
            st.rerun()

    # ---------------------------------------------------------- 运营数据（仅 ?debug=1）
    # 好评率是运营要看的，但学生不需要，所以只在调试模式出现
    if DEBUG:
        with st.expander("反馈统计"):
            fb = _feedback_stats()
            if fb["total"] == 0:
                st.caption("暂无反馈")
            else:
                st.caption(f"好评率 {fb['up_rate']:.0%} · 共 {fb['total']} 条")
                if fb["top_bad"]:
                    for item in fb["top_bad"][:3]:
                        st.caption(f"{item['count']} 次 · {item['query']}")

    # ---------------------------------------------------------- 高频问题（输入栏上方）
    _render_suggestions()


if __name__ == "__main__":
    main()
