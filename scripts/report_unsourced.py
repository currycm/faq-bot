"""生成「无溯源意图清单」：docs/unsourced_intents.md

背景：`data/qa_corpus.json` 里有一半意图没有 `_meta`，即既没有官方通知原文可摘，
也没有显式标注为「引导型」。这类条目在演示/面试时被追问来源会答不上来，
需要一份可核对的清单。

风险分级用可重算的规则，而不是手填：
    P0  答案里出现具体校方事实（日期/时刻/金额/数量/电话/网址/地点）**且**没有兜底措辞
        → 一旦与实际不符就是"明确答错"
    P1  同样有具体事实，但带了「以…为准」这类自我限定 → 至少不构成断言
    P2  没有具体事实，属泛化/引导型描述
豁免   答案描述的是本项目自身界面（可在代码里自证），不涉及校方政策

用法：python scripts/report_unsourced.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "qa_corpus.json"
OUT = ROOT / "docs" / "unsourced_intents.md"

# 答案描述本页界面、可在代码中自证，不需要外部溯源
SELF_EVIDENT = {
    "campus_map_guide": "答案描述本页「校园地图」标签页的下拉框与缩放按钮，属平台自身功能说明，在 `src/campus_map.py` 中可自证",
}

# 硬事实信号：(名称, 正则)
HARD_FACTS = [
    ("日期", r"\d{1,2}\s*月\s*\d{1,2}\s*日|\d{4}\s*年|第\s*\d+\s*[-~—至]?\s*\d*\s*周|每学期|每学年"),
    ("时刻", r"\d{1,2}\s*[:：]\s*\d{2}"),
    ("金额", r"\d+(?:\.\d+)?\s*元"),
    ("数量", r"\d+\s*(?:册|天|次|份|个|人|小时|分钟|G|学分|%)"),
    ("电话", r"0\d{2,3}-\d{7,8}|1\d{10}|400-\d{3}-\d{4}"),
    ("网址", r"https?://|[\w.-]+\.(?:edu\.cn|com\.cn|cn)\b"),
    ("地点", r"[A-Z]\s*座|行政楼|学生服务中心|事务大厅|圈存机|号窗口|号宿舍楼|图书馆\s*\d+\s*楼|信息中心"),
]

# 兜底措辞：出现即说明作者没有把话说死。
# 只收「指向权威来源」或「明确自我限定」的表述 ——
# 「约 2 个工作日」「一般为」这类对数值的粗略修饰不算兜底，
# 否则会把 transcript（写明 行政楼 302 / 每天限 3 份免费）误判成低风险。
HEDGE = re.compile(
    r"以[^。；，]{0,16}为准|具体(?:以|见|详见)|详见原文|详情见|见\s*[a-z_]+|请以"
)


def scan_hard_facts(answer: str) -> list[str]:
    """返回命中的硬事实类别（去重、保持声明顺序）。"""
    hit = []
    for name, pat in HARD_FACTS:
        if re.search(pat, answer):
            hit.append(name)
    return hit


START_PAD = 16
DELIM = "。；，、（(：:"


def _frag(answer: str, start: int, end: int, tail: int = 10) -> str:
    """截取上下文片段，并尽量从句读边界起头。

    不修的话片段会从半个词中间开始（如「舍楼），门诊时间工作日 8:00」），
    读的人得自己拼回去。
    """
    lo = max(0, start - START_PAD)
    seg = answer[lo:start]
    cut = max((seg.rfind(d) for d in DELIM), default=-1)
    if cut != -1:
        lo += cut + 1
    return answer[lo:min(len(answer), end + tail)].strip().replace("\n", " ")


def extract_samples(answer: str) -> list[str]:
    """每个硬事实类别取**第一个**命中，抽成便于核对的片段。

    按类别只取一次，而不是把所有命中都列出来 —— 否则
    「8:00-11:30、14:00-17:30」会被切成四段互相重叠的碎片，清单反而看不清。
    """
    out = []
    for _, pat in HARD_FACTS:
        m = re.search(pat, answer)
        if m:
            out.append(_frag(answer, m.start(), m.end()))
    return out[:4]


def grade(has_facts: bool, has_hedge: bool) -> tuple[str, str]:
    if not has_facts:
        return "P2", "泛化/引导型描述，无具体校方事实"
    if has_hedge:
        return "P1", "含具体事实但带兜底措辞"
    return "P0", "含具体校方事实且**无兜底**，与实际不符即为明确答错"


def load() -> dict:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def build() -> str:
    doc = load()
    intents = doc["intents"]
    meta = doc["meta"]
    total_q = sum(len(i["questions"]) for i in intents)

    noticed = [i for i in intents if (i.get("_meta") or {}).get("type") == "real_notice_v3"]
    official_doc = [i for i in intents if (i.get("_meta") or {}).get("type") == "official_doc"]
    guidance = [i for i in intents if (i.get("_meta") or {}).get("type") == "guidance"]
    # v1.8.0 新增：人工线下/电话核实。没有 URL 可引，但有明确的核实对象和日期，
    # 可信度介于「有原文可核」与「作者推测」之间 —— 单列一档，不要混进 official_doc。
    manual = [i for i in intents if (i.get("_meta") or {}).get("type") == "manual_verified"]
    unsourced = [i for i in intents if not i.get("_meta")]

    # 顶层 `source` 字段是"死字段"——app.py / agent.py 都不读取，
    # UI 上的来源标签来自兜底信息而非它；它只是作者手填的文本声明，
    # 部分部门名经核对并不存在（见下 KNOWN_WRONG_DEPT）。
    KNOWN_WRONG_DEPT = {"后勤保障部", "学生处心理咨询中心", "学生处", "学生工作处"}
    rows = []
    for it in unsourced:
        ans = it["answer"]
        facts = scan_hard_facts(ans)
        hedge = bool(HEDGE.search(ans))
        level, why = grade(bool(facts), hedge)
        if it["tag"] in SELF_EVIDENT:
            level, why = "豁免", "属平台自身功能说明"
        top_src = it.get("source")
        src_flag = ""
        if top_src:
            if top_src in KNOWN_WRONG_DEPT:
                src_flag = f"顶层 source={top_src}（⚠️ 经核对该部门名不存在，应改为真实部门）"
            else:
                src_flag = f"顶层 source={top_src}（仅文本声明，无 url 可核，不计入溯源）"
        rows.append({
            "tag": it["tag"],
            "nq": len(it["questions"]),
            "facts": facts,
            "hedge": hedge,
            "level": level,
            "why": why,
            "samples": extract_samples(ans) if level in ("P0", "P1") else [],
            "first_q": it["questions"][0],
            "top_src": top_src,
            "src_flag": src_flag,
        })

    order = {"P0": 0, "P1": 1, "P2": 2, "豁免": 3}
    rows.sort(key=lambda r: (order[r["level"]], -r["nq"], r["tag"]))

    L: list[str] = []
    L.append("# 无溯源意图清单（unsourced intents）")
    L.append("")
    L.append(f"- **语料快照**：`data/qa_corpus.json` {meta['version']}，{len(intents)} 意图 / {total_q} 问法")
    L.append("- **口径**：`_meta` 缺失 —— 既没有官方通知原文可摘，也没有显式标注为「引导型」")
    L.append("- **生成方式**：`python scripts/report_unsourced.py`（规则可重算，非手填）")
    L.append(f"- **结论**：**{len(unsourced)} / {len(intents)} 个意图无溯源**")
    L.append("")
    L.append("> 风险分级由两条信号自动判定：答案里是否出现**具体校方事实**（日期/时刻/金额/数量/电话/网址/地点），")
    L.append("> 以及是否带**兜底措辞**（「以…为准」这类自我限定）。")
    L.append("")
    L.append("## 一、总览")
    L.append("")
    L.append("| 类别 | 意图数 | 溯源状态 | 说明 |")
    L.append("|---|---|---|---|")
    L.append(f"| `real_notice_v3` | {len(noticed)} | ✅ 有官方通知原文 | 全部是部门前缀 `jwc_` / `xsc_` / `xxh_`，含 `url` + `title` + `date` |")
    L.append(f"| `official_doc` | {len(official_doc)} | ✅ 有官方文档/页面 | {', '.join('`%s`' % i['tag'] for i in official_doc) or '—'}，含 `url` + `title`，来源为官方 PDF/网页（v1.6.0 新增）|")
    L.append(f"| `guidance` | {len(guidance)} | ⚠️ 有标注、无原文 | {', '.join('`%s`' % i['tag'] for i in guidance)}，正文已声明以官方为准 |")
    L.append(f"| `manual_verified` | {len(manual)} | 🟡 **人工核实，无原文** | "
             f"无 url 可引，但有核实对象与核实日期（见第三节）；可信度高于"
             f"「作者推测」、低于「有原文可核」 |")
    L.append(
        f"| **无 `_meta`** | **{len(unsourced)}** | ❌ **无溯源** | "
        + (", ".join("`%s`" % i["tag"] for i in unsourced) or "—")
        + " |"
    )
    L.append("")
    L.append(f"> ⚠️ **关于顶层 `source` 字段**：本清单里标「无 `_meta`」的意图中，"
             f"有 {sum(1 for r in rows if r['top_src'])} 条带顶层 `source`")
    L.append("> （" + ("、".join("「%s」" % r["top_src"] for r in rows if r["top_src"]) or "无")
             + "），但那只是作者手填的文本声明，**没有 url 可核**，")
    L.append("> 且代码（`app.py` / `agent.py`）**根本不读取该字段**——UI 来源标签来自兜底信息。")
    L.append("> 经核对，其中「后勤保障部」「学生处心理咨询中心」这两个部门名**在学校机构设置里并不存在**")
    L.append("> （真实应为「学工处·学生公寓管理科」「学工处·心理健康教育教研室」，`dorm_repair` / `psych_counseling`")
    L.append("> 已在 v1.6.0 改为 `official_doc` 并修正）。**因此顶层 `source` 一律不计入「有溯源」。**")
    L.append("")
    if unsourced:
        L.append(f"**当前规律**：从官方通知/文档生成的意图（部门前缀）都带溯源；"
                 f"仍未溯源的 {len(unsourced)} 条见第二节风险分级。")
    else:
        L.append("**当前状态：全部意图都已标注来源类型**（通知原文 / 官方文档 / 人工核实 / 引导型），")
        L.append("本清单转为审计留档。⚠️ 其中 `manual_verified` 一档**没有原文可引、会随政策变化过期**，")
        L.append("凡涉及时间、金额、地点、数量的数字，每学年至少复核一次。")
    L.append("")

    L.append("## 二、风险分级")
    L.append("")
    L.append("| 等级 | 含义 | 数量 | 意图 |")
    L.append("|---|---|---|---|")
    for lvl, desc in (
        ("P0", "含具体校方事实且无兜底 —— 与实际不符即为明确答错"),
        ("P1", "含具体事实但带兜底措辞 —— 不构成断言"),
        ("P2", "泛化/引导型描述，无具体事实"),
        ("豁免", "属平台自身功能说明，无需外部溯源"),
    ):
        tags = [r["tag"] for r in rows if r["level"] == lvl]
        if not tags:
            continue
        L.append(f"| **{lvl}** | {desc} | {len(tags)} | {', '.join('`%s`' % t for t in tags)} |")
    L.append("")

    L.append("## 三、逐条明细")
    L.append("")
    p0 = [x for x in rows if x["level"] == "P0"]
    if p0:      # 没有 P0 时不要留下空标题（v1.8.0 之后就出现过一次）
        L.append("### P0 —— 优先补齐（按问法数排序）")
        L.append("")
        for r in p0:
            L.append(f"#### `{r['tag']}`（{r['nq']} 问法）")
            L.append("")
            L.append(f"- 示例问句：{r['first_q']}")
            L.append(f"- 硬事实类别：{' / '.join(r['facts'])}")
            L.append(f"- 待核对的片段：{'；'.join('`%s`' % s for s in r['samples'])}")
            if r["src_flag"]:
                L.append(f"- 来源声明：{r['src_flag']}")
            L.append("")

    for lvl, title in (("P1", "P1 —— 有兜底，但事实仍应核对"), ("P2", "P2 —— 泛化描述"), ("豁免", "豁免 —— 无需外部溯源")):
        sub = [x for x in rows if x["level"] == lvl]
        if not sub:
            continue
        L.append(f"### {title}")
        L.append("")
        L.append("| 意图 | 问法数 | 硬事实 | 兜底措辞 | 示例问句 |")
        L.append("|---|---|---|---|---|")
        for r in sub:
            L.append(
                "| `%s` | %d | %s | %s | %s |"
                % (
                    r["tag"],
                    r["nq"],
                    " / ".join(r["facts"]) if r["facts"] else "—",
                    "有" if r["hedge"] else "—",
                    r["first_q"],
                )
            )
        L.append("")

    L.append("## 四、⚠️ 顺带扫出的疑似占位数据")
    L.append("")
    L.append("规则扫描时命中的电话/网址值得单独确认（`example.*` 这类占位符已在 v1.5.1 修掉一处）：")
    L.append("")
    L.append("| 意图 | 片段 | 疑点 |")
    L.append("|---|---|---|")
    for r in rows:
        if "电话" not in r["facts"]:
            continue
        ans = next(i["answer"] for i in unsourced if i["tag"] == r["tag"])
        for m in re.finditer(r"0\d{2,3}-\d{7,8}|400-\d{3}-\d{4}|1\d{10}", ans):
            num = m.group(0)
            frag = _frag(ans, m.start(), m.end(), tail=6)
            note = "号码为递增序列 `87654321`，且区号 `010` 是北京 —— 本校在南京" if num == "010-87654321" else "需核实是否为官方号码"
            L.append(f"| `{r['tag']}` | `{frag}` | {note} |")
    L.append("")
    L.append("## 五、建议的补齐路线")
    L.append("")
    L.append("1. **先补 P0**：这些是「具体到数字」的断言，被追问一句就见底，优先挑问法多的。")
    L.append("   （v1.8.0 已把 `course_selection` / `library_borrow` / `transcript` / `medical` 等")
    L.append("   原 P0 条目通过人工核实补齐，现为 `manual_verified` —— 可作后续补条的参照格式。）")
    L.append("2. **补的方式三选一**：")
    L.append("   - 拿到官方通知原文 → 改写为「通知摘录型」，补 `_meta{source, category, url, title, date, type: real_notice_v3}`；")
    L.append("   - 拿到官方文档/网页（PDF、办事指南页等）→ 补 `_meta{...type: official_doc}`，正文保留可核实事实（如 `dorm_repair` / `psych_counseling` 在 v1.6.0 的做法）；")
    L.append("   - 拿不到原文 → 改为「引导型」，删掉所有具体数字，只留指引 + 官方渠道，")
    L.append("     补 `_meta.type = \"guidance\"`（照 `jwc_major_change` 的样子写）。")
    L.append("   - **顺手核一遍顶层 `source`**：凡带该字段的，确认部门名在学校机构设置里真实存在，否则修正或删除（死字段，不读也要保证别误导人）。")
    L.append("3. **原则不变**：宁可引导，不可编造。库里凡是「学校具体政策」的答案，编一条就把整个项目的可信度搭进去了。")
    L.append("4. 每补一条，把 `meta.changelog` 记一笔，并重跑本脚本把清单刷新。")
    L.append("")
    L.append("## 附录：有溯源意图对照（补 `_meta` 时照这个格式写）")
    L.append("")
    L.append("| 意图 | 类型 | 来源 | 通知/文档标题 | 日期 |")
    L.append("|---|---|---|---|---|")
    for it in sorted(noticed + official_doc, key=lambda x: (x["_meta"]["source"], x["tag"])):
        m = it["_meta"]
        L.append(f"| `{it['tag']}` | `{m['type']}` | {m['source']} | [{m['title']}]({m['url']}) | {m['date']} |")
    if manual:
        L.append("")
        L.append("### `manual_verified` 型明细（人工核实，v1.8.0 新增）")
        L.append("")
        L.append("| 意图 | 核实来源 | 核实日期 |")
        L.append("|---|---|---|")
        for it in sorted(manual, key=lambda x: x["tag"]):
            m = it["_meta"]
            L.append(f"| `{it['tag']}` | {m['source']} | {m['date']} |")
        L.append("")
        L.append("> 这一档**没有 url 可引**，是人工问询/现场确认得来的。它比「作者推测」可靠，")
        L.append("> 但仍会随政策变化过期 —— 正文里凡涉及时间、金额、地点、数量的数字，")
        L.append("> 每个学年至少复核一次。")
    L.append("")
    for it in guidance:
        m = it["_meta"]
        L.append(f"`{it['tag']}` 是 `guidance` 型（无原文可摘）：`source={m['source']}`、`title={m['title']}`、`date={m['date']}`。")
        L.append("")
        L.append(f"> {m['note']}")
        L.append("")
    L.append("### 无 `_meta` 但带顶层 `source` 文本声明的意图（不计入溯源）")
    L.append("")
    L.append("| 意图 | 顶层 source（仅文本声明）| 风险等级 |")
    L.append("|---|---|---|")
    for r in sorted(rows, key=lambda x: (x["level"] != "P0", x["tag"])):
        if not r["top_src"]:
            continue
        flag = "⚠️ 部门名不存在" if "不存在" in r["src_flag"] else "未核实"
        L.append(f"| `{r['tag']}` | {r['top_src']} | {r['level']}（{flag}）|")
    L.append("")
    return "\n".join(L).rstrip("\n") + "\n"


if __name__ == "__main__":
    text = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"[ok] 已生成 {OUT.relative_to(ROOT)}（{len(text.splitlines())} 行）")
