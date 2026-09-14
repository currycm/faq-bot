# -*- coding: utf-8 -*-
"""Streamlit 网页入口（v7.1）

启动：
    1) 先启动 FastAPI 后端：uvicorn api:app --port 8000
    2) 再启动前端：      streamlit run app.py

排查问题时在启动前端的终端里设 FAQ_DEBUG=1 可显示调试信息（trace_id / 相似度 / 候选列表）。
仅环境变量生效，URL ?debug=1 参数已废弃（2026-09 修复：任何访客都能加参数，属无鉴权信息泄露）。

--------------------------------------------------------------------------
v7.1 改动：前端去 AI 味 / 信息降噪

核心判断：**调试信息不是给用户的**。
    trace_id、相似度分数、候选进度条、意图数、vectorizer 全部默认隐藏，
    只有 FAQ_DEBUG=1 时才显示。之前一条回答叠 5 层，其中 3 层学生根本不看。

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
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests
import streamlit as st
import streamlit.components.v1 as components

from src import config, logger, ui_style
from src.campus_map import render_campus_map


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

    # 服务故障必须和「知识库没收录」分开说。
    # 之前没有这一支，error 会落到最后的默认分支、显示成「知识库暂未收录」——
    # 我们自己的服务挂了，却让学校知识库背锅，用户还会以为"学校确实没这条规定"。
    if ftype == "error":
        return "error", "服务暂时不可用，稍后再试"

    if ftype == "realtime":
        return "api", "实时数据 · 和风天气" if fsrc == "weather" else "实时数据"
    if fsrc == "llm":
        return "llm", "AI 生成 · 非官方答复"
    if ftype == "chat":
        return "chat", ""
    if ftype == "campus_only":
        return "none", "这个问题建议直接问相关部门"
    return "none", "知识库暂未收录"


# ---------------------------------------------------------------- 调试开关
# 调试面板只认环境变量 FAQ_DEBUG=1，不再认 URL ?debug=1。
# 2026-09 修复：URL 参数任何访客都能加，等于无鉴权暴露 API 基址、
# trace_id、内部阈值、候选分数和反馈统计。改为环境变量后，
# 线上不开就谁也看不到；运维排查时在自己终端/容器里临时打开。
_DEBUG_ENABLED = os.environ.get("FAQ_DEBUG", "").strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------- 对话区滚动
# 对话区是独立滚动容器（CSS 见 ui_style.py 的 .st-key-qa_history）。
# 自己滚动的容器有个副作用：追加新消息时浏览器不会跟着走。
# 页面重跑后 React 复用同一个 DOM 节点，scrollTop 保持不变，
# 而 scrollHeight 变大了 —— 结果就是新回答在视口下方，用户看不到，
# 得自己手动往下滚。所以要在新消息出现后把它滚到底。
#
# 关键点一：**必须带 <script> 标签**。components.html 不会替你补，
#   少了标签这段 JS 就只是 iframe 里的一段纯文本，静默不执行
#   （排查时表现为"代码明明写对了却没反应"，很费时间）。
# 关键点二：这里刻意**用普通字符串 + replace 拼 count**，不用 f-string。
#   脚本里全是 JS 的 `{}`（对象字面量），塞进 f-string 要写成 `{{}}`，
#   改一次错一次（之前 ui_style.py 的 CSS 就栽在这上面，直接把页面白屏）。
#
# 关键点三（2026-09 修复，真机 Playwright 实测定位）：
#   点对话区里的按钮（有用/没用/候选问题）会让**按钮获得焦点**；
#   重跑把该按钮从 DOM 卸载后，浏览器会把最近的可滚动祖先
#   —— 也就是 qa_history —— **滚回顶部**。
#   对照实验（容器 scrollTop 可辨）：
#     · 纯 JS `btn.click()`（不聚焦）：538 → 526（保持，仅内容变矮 12px）
#     · `btn.focus(); btn.click()`：  517 → **0**（跳顶）
#   所以修复不是"重跑后一律不滚"，而是"点击那一刻先记住位置，重跑完放回去"。
#   快照/计数都挂在**父窗口**上 —— 组件 iframe 每次重跑都会重建，父窗口变量不会。
_AUTOSCROLL_JS = """
<script>
(function () {
  var w = window.parent, doc = w.document;
  var n = __COUNT__, prev = w.__qaScrollCount;
  w.__qaScrollCount = n;

  var SEL = '[class*="st-key-qa_history"]';
  function box() { return doc.querySelector(SEL); }

  // 每轮重跑都重挂点击监听 —— 组件 iframe 每轮都会被销毁重建，它挂到「父文档」
  // 上的监听会随之失效（挂在父窗口上的变量则保留）。只挂一次会静默失灵：
  // 表现为回调根本不进。
  if (w.__qaClickHandler) {
    doc.removeEventListener('click', w.__qaClickHandler, true);
  }
  w.__qaClickHandler = function (e) {
    var t = e.target, el = box();
    if (!t || !t.closest || !el || !t.closest(SEL)) return;

    // 记下点击前的滚动位置，作为重跑后的还原目标
    w.__qaSnapTop = el.scrollTop;

    // 2026-09 修复「点『有用』后页面滚回顶部」的根因：
    // 点击让按钮**获得焦点**；重跑把该按钮从 DOM 卸载后，浏览器会把最近的可
    // 滚动祖先（也就是 qa_history）滚回顶部。
    // 直接让按钮失焦，就没有"卸载聚焦元素"这回事 —— 位置原地不动。
    // 该按钮点完本来就会被「已反馈」替换掉，失焦不影响它的任何功能。
    // 键盘激活（Enter/Space）时浏览器的激活序列可能把焦点给回去，补一个延后一拍的 blur。
    var btn = t.closest('button');
    if (btn) {
      btn.blur();
      w.setTimeout(function () { try { btn.blur(); } catch (err) {} }, 0);
    }
  };
  doc.addEventListener('click', w.__qaClickHandler, true);

  w.requestAnimationFrame(function () {
    w.requestAnimationFrame(function () {
      // 消息真的变多 → 滚到底（快照作废）
      if (prev === undefined || n > prev) {
        w.__qaSnapTop = null;
        var el = box();
        if (!el) return;
        var reduce = w.matchMedia && w.matchMedia('(prefers-reduced-motion: reduce)').matches;
        el.scrollTo({ top: el.scrollHeight, behavior: reduce ? 'auto' : 'smooth' });
        return;
      }

      // 其它重跑（点「有用」等）→ 把位置放回去。
      // 用「多帧重试」而不是一次赋值：DOM 节点可能正在被替换，而且重置有可能
      // 发生在我们赋值**之后**，一次赋值会被反超；逐帧重试能压住。
      var want = w.__qaSnapTop;
      if (want === null || want === undefined) return;
      var tries = 20;
      var apply = function () {
        var el = box();
        if (el && el.scrollTop !== want) el.scrollTop = want;
        if (el && el.scrollTop === want) { w.__qaSnapTop = null; return; }
        if (--tries > 0) w.requestAnimationFrame(apply);
      };
      apply();
    });
  });
})();
</script>
"""


def _autoscroll_history(count: int) -> None:
    """消息数变化时把对话区滚到底部（height=0 的隐藏 iframe，不占版面）。"""
    components.html(_AUTOSCROLL_JS.replace("__COUNT__", str(count)), height=0)


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
    # 2026-09 修复：截断对两条路径统一生效。此前只有本地模式截断，
    # HTTP 模式下超 200 字的 query 会被 api.py 的 AskRequest(max_length=200)
    # 以 422 拒绝，raise_for_status 抛错后用户看到"服务暂时不可用"，
    # 把输入校验错误误报成了宕机。
    query = (query or "").strip()[:200]
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
    tab_qa, tab_map = st.tabs(["💬 校园问答", "🗺️ 校园地图"])
    with tab_map:
        render_campus_map()
    with tab_qa:
        st.title("校园问答")
        st.caption("南京工业职业技术大学")

        DEBUG = _DEBUG_ENABLED

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
        # 还白白占着左侧一栏。反馈统计挪到了页面底部，FAQ_DEBUG=1 时才显示。

        # ---------------------------------------------------------- 会话状态
        if "history" not in st.session_state:
            st.session_state.history = []

        # ---------------------------------------------------------- 首次引导
        # 只留一句说明。推荐问题不再放这里 —— 见文件末尾的 _render_suggestions()
        if not st.session_state.history:
            st.caption("答案来自学校通知；知识库没有的会如实告诉你，不会编。")

        # ---------------------------------------------------------- 渲染对话
        total = len(st.session_state.history)

        # 整个对话区包进一个「限高 + 可垂直滚动」的容器
        # （class="st-key-qa_history"，样式见 ui_style.py）。
        # 不加这层的话：连续提问会让页面被无限顶长，输入框越推越远，
        # 想回看上一轮还得整页滚动。加了之后对话区自己滚，页面其余部分不动。
        with st.container(key="qa_history"):
            for i, (q, r) in enumerate(st.session_state.history):
                kind, source_line = source_of(r)

                # ---- 提问：靠右的气泡 ----
                # key 生成 class="st-key-qa_ask_<i>"，ui_style.py 用
                # margin-left:auto + width:fit-content 把它推到右侧。
                # 不再做折叠：问答内容原样完整展示，想看哪轮滚动即可。
                with st.container(key=f"qa_ask_{i}"):
                    st.caption("提问")
                    st.write(q)

                # ---- 回答：靠左的气泡 ----
                # 只有「正文 + 来源」进气泡；下面的候选问题按钮、调试信息、
                # 反馈按钮留在气泡外，随时可点，不会被长回答挤到屏幕外面去。
                with st.container(key=f"qa_answer_{i}"):
                    st.caption("回答")
                    st.write(r["answer"])

                    # 来源：一行灰字，替代原来的彩色徽章 + 匹配度百分比
                    if source_line:
                        st.caption(source_line)

                # ---- 该轮的附属操作（紧跟回答，左对齐、气泡外） ----
                with st.container(key=f"qa_meta_{i}"):
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

                    # 调试信息：只在 FAQ_DEBUG=1 时出现
                    if DEBUG:
                        with st.expander("调试信息"):
                            st.caption(
                                f"trace_id: `{r.get('trace_id', 'n/a')}` ｜ "
                                f"耗时 {r.get('latency_ms', 0):.0f} ms"
                            )
                            # api_ask 失败时的底层异常串只在调试模式可见
                            if r.get("_error"):
                                st.caption(f"错误详情：{r['_error']}")
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
                        # 横向容器：按钮按内容宽度排布。
                        # 原来用 st.columns([0.9, 0.9, 8])，每个按钮只分到约 9%
                        # 的行宽，装不下「有用」两个字（含内边距），于是标签被
                        # 挤成竖排「有/用」；横向容器不做等分，不会挤压。
                        with st.container(horizontal=True, gap="small"):
                            if st.button("有用", key=f"up_{i}"):
                                logger.log_feedback(r, "up")
                                st.session_state[fb_key] = "up"
                                st.toast("谢谢")
                                st.rerun()
                            if st.button("没用", key=f"down_{i}"):
                                logger.log_feedback(r, "down")
                                st.session_state[fb_key] = "down"
                                st.toast("谢谢，我们会改进")
                                st.rerun()

        # 新消息出现后把对话区滚到底部（放在容器外，不占滚动内容）。
        # 「清空对话」不在这里：它在容器外，长对话时也始终够得着。
        _autoscroll_history(total)

        # ---------------------------------------------------------- 清空
        if st.session_state.history:
            if st.button("清空对话"):
                st.session_state.history = []
                for k in [k for k in st.session_state if k.startswith("fb_")]:
                    del st.session_state[k]
                st.rerun()

        # ---------------------------------------------------------- 运营数据（仅 FAQ_DEBUG=1）
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

        # ---------------------------------------------------------- 提问
        # 放在 tab 内脚本最末 → 内联渲染在底部；
        # 因为 st.chat_input 在 st.tabs 内不会浮动到底部，必须排在最后才视觉置底。
        query = st.chat_input("问点什么？比如：图书馆几点关门")
        if not query:
            query = st.session_state.pop("pending_query", None)
        if query:
            # 2026-09 修复：此前所有前端用户共用 "streamlit_user" 这一个
            # 限流身份，任一用户连续提问就能把全校挡在限流外面。
            # 现在每个浏览器会话一个随机 user_id，用户维度互相隔离。
            st.session_state.setdefault("user_id", uuid.uuid4().hex[:12])
            # LLM 兜底要 1~3 秒，spinner 让用户知道在处理。
            # 文案用中性的「查询中」而不是「正在思考…」——后者是拟人化 AI 味。
            with st.spinner("查询中"):
                result = api_ask(query, user_id=st.session_state.user_id)
            st.session_state.history.append((query, result))
            st.rerun()


if __name__ == "__main__":
    main()
