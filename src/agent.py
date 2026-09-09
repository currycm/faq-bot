# -*- coding: utf-8 -*-
"""L5 答案生成层 + L6 交互入口（编排）

把 L1~L4、L7 串成一条完整链路：

    用户提问 → 预处理 → 向量化 transform → 召回 Top-K → [精排] → 阈值判定 → 返回答案 → 写日志

运行方式：
    python -m src.agent            # 命令行交互
    streamlit run app.py           # 网页
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from . import config, logger, preprocess
from .ranker import build_ranker
from .retriever import Retriever
from .vectorizer import TfidfVectorizerImpl, build_vectorizer


def setup_stdio() -> None:
    """Windows 控制台默认编码可能是 GBK，打印中文会乱码。强制 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
            if enc != "utf8":
                stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


# ------------------------------------------------------------------ 语料
def load_corpus(path: Path | None = None) -> list[dict]:
    """加载语料 JSON。"""
    path = Path(path) if path else config.CORPUS_PATH
    if not path.exists():
        raise FileNotFoundError(f"语料文件不存在：{path}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    intents = data.get("intents", [])
    if not intents:
        raise ValueError(f"语料为空，请在 {path} 里补充 intents")

    # 轻量校验：tag 必须唯一，否则日志统计会串
    seen = set()
    for it in intents:
        tag = it.get("tag")
        if not tag:
            raise ValueError(f"存在缺少 tag 的意图：{it}")
        if tag in seen:
            raise ValueError(f"tag 重复：{tag}（tag 必须全局唯一）")
        seen.add(tag)
        if not it.get("questions"):
            raise ValueError(f"意图 {tag} 缺少 questions")
        if not it.get("answer"):
            raise ValueError(f"意图 {tag} 缺少 answer")
    return intents


def flatten(intents: list[dict]) -> list[dict]:
    """意图聚合结构 → 展平成 (问题, 答案, tag) 三元组。

    检索是在"问法"粒度上做的：一个意图挂 5 条问法，
    就等于索引里有 5 条指向同一答案的候选，命中概率大幅提升。
    """
    return [
        {"question": q, "answer": it["answer"], "tag": it["tag"]}
        for it in intents
        for q in it["questions"]
    ]


# ------------------------------------------------------------------ 兜底 v4
def fallback(query: str, hits: list, threshold: float) -> str:
    """v4 兜底策略：路由器分发。

    顺序（路由器内部）：
        1. 闲聊 → 固定话术
        2. 实时（天气等）→ 调 API
        3. 校园事务未命中 → 固定话术（绝不进 LLM）
        4. 通识 → LLM 兜底
        5. 任何层失败 → 降级到 FALLBACK_TEXT

    原 FALLBACK_MODE 的"human"分支仍保留作为最后的人工兜底。
    """
    # 关掉路由器时，保留旧逻辑
    if not getattr(config, "FALLBACK_ROUTER_ENABLED", False):
        return _legacy_fallback(query, hits, threshold)

    from .fallback import dispatch
    decision = dispatch(query)
    return decision.answer


def _legacy_fallback(query: str, hits: list, threshold: float) -> str:
    """旧版兜底：仅在 FALLBACK_ROUTER_ENABLED=False 时使用。"""
    mode = config.FALLBACK_MODE

    if mode == "human":
        return config.FALLBACK_HUMAN_TEXT

    if mode == "llm":
        # 走新版 LLM 客户端
        from .fallback import llm_client
        ans = llm_client.format_answer(query)
        if "通义千问生成" in ans:
            return ans
        return config.FALLBACK_TEXT

    # 默认 fixed：固定话术 + 条件性推荐
    text = config.FALLBACK_TEXT
    if config.SHOW_SUGGESTIONS and hits:
        top = hits[0]
        if (threshold - top.score) < 0.10 and top.score >= threshold * 0.7:
            suggestions = "\n".join(f"  · {h.question}" for h in hits[:3])
            text += "\n\n你可能想问：\n" + suggestions
    return text


# ------------------------------------------------------------------ 主体
class FaqBot:
    """FAQ 问答机器人。构造时建索引（离线），ask() 可反复调用（在线）。"""

    def __init__(
        self,
        corpus_path: Path | None = None,
        vectorizer_type: str | None = None,
        threshold: float | None = None,
        enable_rerank: bool | None = None,
    ):
        self.corpus_path = Path(corpus_path) if corpus_path else config.CORPUS_PATH
        self.threshold = config.SIMILARITY_THRESHOLD if threshold is None else threshold

        preprocess.register_custom_words()

        self.intents = load_corpus(self.corpus_path)
        self.records = flatten(self.intents)

        # ---- 离线索引链路：只在启动时跑一次 ----
        t0 = time.perf_counter()
        self.vectorizer = build_vectorizer(vectorizer_type)
        # !! 关键：预处理函数必须按向量化器类型切换。
        #   - TF-IDF：fit 必须用切词后的字符串，否则词表与查询不一致
        #   - BGE/BERT：模型自带 tokenizer，外层切词反而破坏完整语义
        self.text_fn = (
            preprocess.cut
            if isinstance(self.vectorizer, TfidfVectorizerImpl)
            else preprocess.normalize
        )
        self.vectorizer.fit([self.text_fn(r["question"]) for r in self.records])
        self.retriever = Retriever(
            self.vectorizer, self.records, text_fn=self.text_fn
        )
        self.ranker = build_ranker(enable_rerank)
        self.build_ms = (time.perf_counter() - t0) * 1000

    # -------------------------------------------------------------- 在线问答
    def ask(self, query: str, top_k: int | None = None,
            user_id: str | None = None,
            trace_id: str | None = None,
            client_ip: str | None = None) -> dict:
        """回答一个问题。

        返回结构：
            {
              "query": 原始问题,
              "answer": 答案文本,
              "matched": 是否命中 FAQ,
              "tag": 命中意图（未命中为 None）,
              "score": 最高相似度,
              "latency_ms": 耗时,
              "fallback": {            # 检索未命中时由路由器填入
                "type":   问题分类 (chat/realtime/campus_only/general),
                "source": 答案来源  (fixed/llm/weather),
                "rule":   触发规则
              },
              "security": {            # W2 安全层
                "reason": "",               # 拒绝原因（无拒绝时为空）
                "pii_hits": [],             # 命中的 PII 类型
                "injection_rules": [],      # 命中的注入规则（仅日志，不阻断时也记）
              },
              "candidates": [{"question","tag","score"}, ...]
            }

        :param user_id: 用户 ID（来自登录态 / Session），用于限流和审计
        :param trace_id: 请求链路 ID，便于跨模块追踪问题
        :param client_ip: 客户端 IP，用于 IP 级限流和审计
        """
        from .security import enforce_security
        from .security.budget import record_llm_call

        t0 = time.perf_counter()
        query = (query or "").strip()
        if not query:
            return {"query": query, "answer": "请输入你的问题～", "matched": False,
                    "tag": None, "score": 0.0, "latency_ms": 0,
                    "fallback": None, "candidates": [],
                    "security": {"reason": "", "pii_hits": [],
                                 "injection_rules": []}}

        top_k = top_k or config.TOP_K

        # ---- W2 安全层 第一阶段：注入检测 + 限流（每个请求必走）----
        # will_call_llm=False：FAQ 命中不消耗 LLM 预算；budget 留到未命中分支再检查
        sec_pre = enforce_security(
            query, ip=client_ip, user_id=user_id, will_call_llm=False,
        )
        if not sec_pre.allowed:
            result = {
                "query": query,
                "answer": sec_pre.refusal_text,
                "matched": False,
                "tag": None,
                "score": 0.0,
                "matched_question": None,
                "top_guess": None,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                "vectorizer": self.vectorizer.name,
                "fallback": {"type": "security", "source": "fixed",
                             "rule": sec_pre.reason},
                "security": {
                    "reason": sec_pre.reason,
                    "pii_hits": sec_pre.pii_hits,
                    "injection_rules": sec_pre.injection_rules,
                },
                "candidates": [],
                "user_id": user_id,
                "trace_id": trace_id,
                "client_ip": client_ip,
            }
            logger.log_query(result)
            return result

        # ---- 在线链路：只 transform，绝不 fit ----
        # 预处理由 Retriever 内部统一执行，保证与建索引时完全一致
        hits = self.retriever.search(query, top_k=top_k)
        hits = self.ranker.rerank(query, hits)

        best = hits[0] if hits else None
        best_score = best.score if best else 0.0
        matched = bool(best is not None and best_score >= self.threshold)

        # 用于汇总的 pii_hits 与 injection_rules
        all_pii_hits = list(sec_pre.pii_hits)
        all_injection_rules = list(sec_pre.injection_rules)
        security_reason = ""

        if matched:
            answer = best.answer
            fallback_info = None
        else:
            # ---- W2 安全层 第二阶段：budget 检查 + 完整 redact（仅在可能调 LLM 时）----
            sec_full = enforce_security(
                query, ip=client_ip, user_id=user_id, will_call_llm=True,
            )
            if not sec_full.allowed:
                # budget / 二次 injection 命中 → 拒答
                answer = sec_full.refusal_text
                fallback_info = {"type": "security", "source": "fixed",
                                 "rule": sec_full.reason}
                security_reason = sec_full.reason
                sanitized_for_llm = sec_full.sanitized_query
            else:
                sanitized_for_llm = sec_full.sanitized_query
                # !! 关键：dispatch() 只能调一次。
                #    路由器内部会触发 LLM / 天气 API，调两次 = 双倍费用 + 双倍延迟。
                #    之前这里 fallback() 调一次、下面又调一次，属于实打实的浪费。
                if getattr(config, "FALLBACK_ROUTER_ENABLED", False):
                    from .fallback import dispatch
                    # 把脱敏后的 query 透传给 LLM 通道；路由器分类仍用原 query
                    decision = dispatch(query, sanitized_query=sanitized_for_llm)
                    answer = decision.answer
                    fallback_info = {
                        "type": decision.query_type.value,
                        "source": decision.source,
                        "rule": decision.rule,
                    }
                    # LLM 真调了 → 记录预算
                    if decision.source == "llm":
                        record_llm_call()
                else:
                    answer = fallback(query, hits, self.threshold)
                    fallback_info = {"type": "legacy", "source": config.FALLBACK_MODE,
                                     "rule": ""}
                    # 旧 llm 模式直接调 LLM 也算一次
                    if config.FALLBACK_MODE == "llm":
                        record_llm_call()

                # 汇总 PII / injection 命中
                all_pii_hits = list(set(all_pii_hits) | set(sec_full.pii_hits))

        result = {
            "query": query,
            "answer": answer,
            "matched": matched,
            "tag": best.tag if matched else None,
            "score": round(best_score, 4),
            "matched_question": best.question if matched else None,
            "top_guess": best.tag if best else None,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "vectorizer": self.vectorizer.name,
            "fallback": fallback_info,
            "security": {
                "reason": security_reason,
                "pii_hits": all_pii_hits,
                "injection_rules": all_injection_rules,
            },
            "candidates": [{"question": h.question, "tag": h.tag,
                            "score": round(h.score, 4)} for h in hits],
            "user_id": user_id,
            "trace_id": trace_id,
            "client_ip": client_ip,
        }

        logger.log_query(result)
        return result

    # -------------------------------------------------------------- 语料热更新
    def reload(self) -> tuple[int, int]:
        """重新加载语料并重建索引，无需重启服务。"""
        self.intents = load_corpus(self.corpus_path)
        self.records = flatten(self.intents)
        # !! 关键：reload 必须按当前向量化器类型走同一条预处理路径
        #   否则重建后索引矩阵和在线查询不一致，score 全部失真
        self.vectorizer.fit([self.text_fn(r["question"]) for r in self.records])
        self.retriever = Retriever(
            self.vectorizer, self.records, text_fn=self.text_fn
        )
        logger.log_reload(self.corpus_path, len(self.intents), len(self.records))
        return len(self.intents), len(self.records)

    def stats(self) -> dict:
        return {
            "corpus": str(self.corpus_path),
            "intents": len(self.intents),
            "questions": len(self.records),
            "vectorizer": self.vectorizer.name,
            "threshold": self.threshold,
            "build_ms": round(self.build_ms, 2),
        }

    # ---------------------------------------------------------- 推荐问题（v6）
    def suggest_questions(self, n: int | None = None) -> list[str]:
        """给前端用的示例问题（首次打开时展示，降低提问门槛）。

        三级降级，保证任何情况下都能给出合理的推荐：
          1. **真实日志** —— 从 logs/qa.log 统计各意图被问次数，取最热的。
             这是最贴近真实使用的信号（学生实际在问什么）。
          2. **语料热度** —— 按每个意图挂了多少条问法排序。
             问法写得多的意图，通常是当初认为重要的。日志不足时补位。
          3. **手工兜底** —— config.MANUAL_SUGGESTED_QUESTIONS。
             新部署、零日志时也不会开天窗。

        :param n: 返回条数，默认取 config.SUGGEST_COUNT
        """
        n = n or getattr(config, "SUGGEST_COUNT", 7)

        if getattr(config, "SUGGEST_MODE", "auto") == "manual":
            return config.MANUAL_SUGGESTED_QUESTIONS[:n]

        picked: list[str] = []
        used_tags: set[str] = set()

        # ---- 第 1 级：真实查询日志 ----
        for tag in self._hot_tags_from_log():
            q = self._representative_question(tag)
            if q and tag not in used_tags:
                picked.append(q)
                used_tags.add(tag)
            if len(picked) >= n:
                return picked[:n]

        # ---- 第 2 级：语料问法数 ----
        for it in sorted(self.intents, key=lambda x: -len(x["questions"])):
            tag = it["tag"]
            if tag in used_tags:
                continue
            if it["questions"]:
                picked.append(it["questions"][0])
                used_tags.add(tag)
            if len(picked) >= n:
                return picked[:n]

        # ---- 第 3 级：手工兜底 ----
        for q in config.MANUAL_SUGGESTED_QUESTIONS:
            if q not in picked:
                picked.append(q)
            if len(picked) >= n:
                break

        return picked[:n]

    def _hot_tags_from_log(self) -> list[str]:
        """从日志统计各意图被命中的次数，返回按频次降序的 tag 列表。

        只读、容错：日志不存在或某行损坏都跳过，绝不影响主流程。
        """
        if not config.LOG_PATH.exists():
            return []

        counter: dict[str, int] = {}
        try:
            with open(config.LOG_PATH, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # 只统计真正命中的记录（未命中的问题不代表该意图被问到）
                    if not rec.get("matched"):
                        continue
                    tag = rec.get("tag")
                    if tag:
                        counter[tag] = counter.get(tag, 0) + 1
        except OSError:
            return []

        return [t for t, _ in sorted(counter.items(), key=lambda x: -x[1])]

    def _representative_question(self, tag: str) -> str | None:
        """取某个意图的代表性问法（第一条，通常是写得最规范的那条）。"""
        for it in self.intents:
            if it["tag"] == tag and it["questions"]:
                return it["questions"][0]
        return None


# ------------------------------------------------------------------ CLI
_HELP = """可用命令：
  直接输入问题      → 开始问答
  /top              → 显示上一条问题的 Top-3 候选及分数（调试用）
  /stats            → 查看当前索引状态
  /reload           → 重新加载语料（改完 qa_corpus.json 后执行）
  /help             → 显示本帮助
  /exit 或 /quit    → 退出
"""


def main() -> None:
    setup_stdio()

    try:
        bot = FaqBot()
    except (FileNotFoundError, ValueError) as exc:
        print(f"启动失败：{exc}")
        sys.exit(1)

    s = bot.stats()
    print("=" * 52)
    print(f"  校园 FAQ 问答机器人  (向量化方案：{s['vectorizer']})")
    print("=" * 52)
    print(f"语料：{s['intents']} 个意图 / {s['questions']} 条问法"
          f"   阈值：{s['threshold']}")
    print(f"索引构建耗时：{s['build_ms']:.1f} ms")
    print("输入 /help 查看命令，输入 /exit 退出。\n")

    last = None
    while True:
        try:
            q = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not q:
            continue
        if q.lower() in ("/exit", "/quit", "exit", "quit"):
            print("再见！")
            break
        if q == "/help":
            print(_HELP)
            continue
        if q == "/stats":
            print(bot.stats())
            continue
        if q == "/reload":
            n_int, n_q = bot.reload()
            print(f"已重新加载：{n_int} 个意图 / {n_q} 条问法\n")
            continue
        if q == "/top":
            if not last:
                print("还没有问过问题。\n")
                continue
            for i, c in enumerate(last["candidates"], 1):
                print(f"  {i}. [{c['score']:.4f}] ({c['tag']}) {c['question']}")
            print()
            continue

        r = bot.ask(q)
        last = r
        flag = "命中" if r["matched"] else "未命中"
        print(f"机器人：{r['answer']}")
        print(f"        └─ {flag} | score={r['score']:.4f} | "
              f"tag={r['tag']} | {r['latency_ms']:.1f} ms\n")


if __name__ == "__main__":
    main()
