# -*- coding: utf-8 -*-
# 生成兜底增强方案 Word 文档
#
# 用法（在 faq-bot 目录下）：
#     python scripts/generate_plan_docx.py
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor, Cm
from docx.oxml.ns import qn

OUT = Path(r"C:\Users\24830\Desktop\问答机器\兜底增强方案.docx")


def set_cell_text(cell, text, *, bold=False, size=10):
    cell.text = ""
    p = cell.paragraphs[0]
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.font.name = "Microsoft YaHei"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    if bold:
        run.bold = True


def add_h(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.name = "Microsoft YaHei"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        run.font.color.rgb = RGBColor(0x18, 0x5F, 0xA5)
    return h


def add_para(doc, text, *, bold=False, italic=False, size=11):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.font.name = "Microsoft YaHei"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    if bold:
        run.bold = True
    if italic:
        run.italic = True
    return p


def add_code(doc, text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.size = Pt(9)
    run.font.name = "Consolas"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    p.paragraph_format.left_indent = Cm(0.5)
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    return p


def add_table(doc, headers, rows, col_widths=None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Light Grid Accent 1"
    # 表头
    for i, h in enumerate(headers):
        set_cell_text(table.rows[0].cells[i], h, bold=True)
    # 数据
    for r_idx, row in enumerate(rows, start=1):
        for c_idx, cell_text in enumerate(row):
            set_cell_text(table.rows[r_idx].cells[c_idx], str(cell_text))
    if col_widths:
        for col_idx, w in enumerate(col_widths):
            for row in table.rows:
                row.cells[col_idx].width = Cm(w)
    return table


def main():
    doc = Document()

    # 全局字体（中文）
    style = doc.styles["Normal"]
    style.font.name = "Microsoft YaHei"
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    style.font.size = Pt(11)

    # ============ 封面 ============
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("校园 FAQ 机器人 v4 兜底增强方案")
    run.font.size = Pt(24)
    run.bold = True
    run.font.name = "Microsoft YaHei"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    run.font.color.rgb = RGBColor(0x18, 0x5F, 0xA5)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run("从「硬拒答」到「诚实的兜底」")
    r.font.size = Pt(14)
    r.italic = True
    r.font.name = "Microsoft YaHei"
    r._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

    doc.add_paragraph()
    info = doc.add_paragraph()
    info.alignment = WD_ALIGN_PARAGRAPH.CENTER
    info.add_run("项目：faq-bot（南京工业职业技术大学）\n方案作者：WorkBuddy\n日期：2026-09-07\n版本：v1.0")

    doc.add_page_break()

    # ============ 一、背景 ============
    add_h(doc, "一、为什么需要兜底增强", 1)
    add_para(doc, "当前 FAQ 机器人（v3）的兜底逻辑只有一句固定话术：")
    add_code(doc, 'FALLBACK_TEXT = "抱歉，这个问题我还没学会。\\n可以换个问法…"')

    add_para(doc, "这种「硬拒答」暴露了两个问题：")
    add_para(doc, "1. 用户问「今天天气怎么样」明明有合理答案，却被拒答 —— 体验差。")
    add_para(doc, "2. 但如果让 LLM 自由发挥，又可能编造校务政策 —— 这是底线。")
    add_para(
        doc,
        "v4 的目标：在「诚实的兜底」原则下，让范围外的问题给出有用回答；同时严格守住校园事务不准 LLM 发言的安全边界。",
    )

    # ============ 二、方案对比 ============
    add_h(doc, "二、三种候选方案", 1)

    add_h(doc, "2.1 方案 A：纯 LLM 兜底", 2)
    add_para(doc, "未命中 → 直接调通用 LLM → 返回答案。")
    add_para(doc, "优点：一行代码改完。")
    add_para(
        doc,
        "缺点：天气这种实时问题 LLM 会编；校园事务被拒答后再让 LLM 兜底 = 给幻觉开口子；FAQ 模板化与 LLM 自由发挥风格不一致。",
        bold=True,
    )

    add_h(doc, "2.2 方案 B：LLM + 实时 API 协同  ★ 推荐", 2)
    add_para(doc, "未命中 → 路由器分类 → 四路分流：")
    add_para(doc, "  1) 闲聊 → 固定话术，不调 LLM，节省 token")
    add_para(doc, "  2) 实时查询 → 调对应 API（天气/课表/校历），真数据")
    add_para(doc, "  3) 校园事务未命中 → 固定话术，绝不调 LLM")
    add_para(doc, "  4) 通识问答 → LLM 兜底，系统提示钉死边界")
    add_para(doc, "优点：可解释、可控、覆盖全。", bold=True)

    add_h(doc, "2.3 方案 C：RAG 模式", 2)
    add_para(doc, "把 FAQ 语料喂给 LLM，让 LLM 在知识库内作答。检索只做 Top-K 召回。")
    add_para(doc, "优点：兜底时也能借用校园知识。")
    add_para(doc, "缺点：成本高、可能改写原文、与 FAQ 措辞不一致。")

    # ============ 三、推荐架构 ============
    add_h(doc, "三、推荐架构（方案 B）", 1)
    add_para(doc, "路由顺序：闲聊 → 实时 → 校园 → 通识 → 固定兜底。")

    flow_table_rows = [
        ["用户提问", "—", "—"],
        ["BGE 检索器", "余弦相似度 ≥ 0.60", "命中 → FAQ 主路径"],
        ["闲聊", "匹配 CHAT_KEYWORDS", "固定话术"],
        ["实时", "匹配 REALTIME_KEYWORDS", "天气 → 和风天气 API"],
        ["校园事务", "匹配 CAMPUS_KEYWORDS", "固定话术（不进 LLM）"],
        ["通识", "默认", "DeepSeek → 固定兜底"],
        ["任何层失败", "—", "FALLBACK_TEXT"],
    ]
    add_table(doc, ["阶段", "触发条件", "结果"], flow_table_rows, col_widths=[3, 5, 6])

    # ============ 四、文件清单 ============
    add_h(doc, "四、文件改动清单", 1)
    file_rows = [
        ["src/config.py", "改", "+约 90 行"],
        ["src/agent.py", "改", "fallback() 重写，ask() 加 fallback 字段，约 +30 行"],
        ["src/fallback/__init__.py", "新建", "5 行"],
        ["src/fallback/router.py", "新建", "约 160 行"],
        ["src/fallback/llm_client.py", "新建", "约 100 行"],
        ["src/fallback/weather.py", "新建", "约 130 行"],
        ["tests/test_fallback.py", "新建", "约 220 行"],
        ["README.md", "改", "+约 70 行"],
    ]
    add_table(doc, ["文件", "动作", "行数变化"], file_rows, col_widths=[6, 3, 5])

    # ============ 五、配置项 ============
    add_h(doc, "五、配置项说明", 1)

    add_h(doc, "5.1 主开关", 2)
    config_rows = [
        ["FALLBACK_TEXT", "固定话术", "兜底的兜底"],
        ["ROUTER_LOG_ENABLED", "True", "路由器决策日志"],
    ]
    add_table(doc, ["配置项", "默认值", "作用"], config_rows, col_widths=[5, 3, 8])

    add_h(doc, "5.2 DeepSeek", 2)
    tongyi_rows = [
        ["DEEPSEEK_ENABLED", "True", "总开关"],
        ["DEEPSEEK_API_KEY", "环境变量优先", "申请：https://platform.deepseek.com/"],
        ["DEEPSEEK_BASE_URL", "api.deepseek.com", "OpenAI 兼容协议"],
        ["DEEPSEEK_MODEL", "deepseek-chat", "备选 deepseek-reasoner（R1，更慢但更强）"],
        ["DEEPSEEK_TIMEOUT", "8 秒", "超时降级到固定话术"],
        ["DEEPSEEK_TEMPERATURE", "0.3", "低温度 → 更确定、更少幻觉"],
        ["DEEPSEEK_MAX_TOKENS", "256", "单次回答上限"],
    ]
    add_table(doc, ["配置项", "默认值", "说明"], tongyi_rows, col_widths=[5, 4, 7])

    add_h(doc, "5.3 和风天气", 2)
    hf_rows = [
        ["HEFENG_ENABLED", "True", "总开关"],
        ["HEFENG_API_KEY", "环境变量优先", "申请：https://dev.qweather.com/"],
        ["HEFENG_BASE_URL", "devapi.qweather.com", "调试域名；上线换成 api.qweather.com"],
        ["HEFENG_GEO_URL", "geoapi.qweather.com", "城市查询"],
        ["HEFENG_CITY", "南京", "默认城市"],
        ["HEFENG_TIMEOUT", "6 秒", "超时降级"],
    ]
    add_table(doc, ["配置项", "默认值", "说明"], hf_rows, col_widths=[5, 4, 7])

    add_h(doc, "5.4 路由关键词", 2)
    add_para(doc, "路由器按以下四类关键词匹配，命中即短路返回。匹配顺序：闲聊 → 实时 → 校园 → 通识。")
    add_para(doc, "REALTIME_KEYWORDS（实时）")
    add_code(
        doc,
        "天气 / 气温 / 下雨 / 下雪 / 几度 / 校历 / 开学 / 放假 / 期末\n"
        "我的课表 / 今天有什么课 / 成绩查询 / 查成绩 / 绩点多少",
    )
    add_para(doc, "CAMPUS_KEYWORDS（校园事务 - 安全栏）")
    add_code(
        doc,
        "选课 / 退课 / 补考 / 重修 / 绩点 / 学分 / 挂科 / 缓考\n"
        "转专业 / 休学 / 复学 / 毕业 / 答辩\n"
        "校园卡 / 一卡通 / 挂失 / 补卡 / 充值 / 圈存\n"
        "奖学金 / 助学金 / 勤工助学 / 贫困生 / 助学贷款 / 辅导员\n"
        "宿舍 / 寝室 / 门禁 / 熄灯 / 晚归 / 报修\n"
        "借书 / 还书 / 续借 / 图书馆 / 自习室 / 占座 / 闭馆\n"
        "校园网 / 宽带 / 网费 / wifi\n"
        "学校 / 学院 / 系 / 专业 / 教务处 / 学工处 / 后勤 / 校医院 / 医保",
    )
    add_para(doc, "CHAT_KEYWORDS（闲聊）")
    add_code(
        doc,
        "你好 / 您好 / hi / hello / 嗨 / hey\n谢谢 / 感谢 / 辛苦了\n你是谁 / 你叫什么 / 你能做什么\n再见 / 拜拜 / bye",
    )

    # ============ 六、安全边界 ============
    add_h(doc, "六、安全边界与降级", 1)
    safety_rows = [
        ["LLM 编造校务", "系统提示钉死 + 校园关键词拦截在 LLM 之前"],
        ["LLM 编造天气", "天气永远走 API，不进 LLM"],
        ["成本失控", "DEEPSEEK_TIMEOUT=8s 超时降级；HEFENG_TIMEOUT=6s"],
        ["API 密钥泄露", "环境变量优先，配置项留空"],
        ["LLM 异常", "任何异常都降级到 FALLBACK_TEXT，不裸抛"],
        ["风格不一致", "LLM 回答前自动加「DeepSeek 生成」标签"],
    ]
    add_table(doc, ["风险", "缓解手段"], safety_rows, col_widths=[4, 11])

    # ============ 七、系统提示词 ============
    add_h(doc, "七、DeepSeek 系统提示词（防幻觉第一道防线）", 1)
    add_para(doc, "下面这段话决定了 LLM 会不会编校务。写得越宽，LLM 越容易跑偏。")
    add_code(
        doc,
        '你是南京工业职业技术大学的智能助手"小南"。\n'
        "\n"
        "【你的职责】\n"
        "1. 回答通识类问题（学习方法、生活常识、概念解释），简洁友好。\n"
        '2. 实时类问题（天气、成绩、课表）请回复"需要查询实时数据"。\n'
        "\n"
        "【严禁事项】\n"
        "1. 严禁编造学校的政策、流程、日期、联系方式。\n"
        "2. 严禁在不确定时猜测校园事务。\n"
        "3. 严禁超过 100 字。\n"
        '4. 不知道的事情请老实说"不太清楚"。',
    )

    # ============ 八、测试 ============
    add_h(doc, "八、测试覆盖", 1)
    add_para(doc, "测试脚本：tests/test_fallback.py")
    add_para(doc, "覆盖四类：")
    test_rows = [
        ["1. 路由器分类", "15 条", "闲聊/实时/校园/通识 全部正确分流"],
        ["2. 安全栏检查", "4 条", "校园事务不进 LLM / 降级路径不抛异常"],
        ["3. 边界输入", "3 条", "空串/全空格/None 都优雅处理"],
        ["4. 端到端", "5 条", "FaqBot.ask() 返回 fallback 字段完整"],
    ]
    add_table(doc, ["测试组", "用例数", "校验点"], test_rows, col_widths=[4, 3, 8])

    add_para(doc, "运行：")
    add_code(doc, "python tests/test_fallback.py")

    # ============ 九、扩展路线 ============
    add_h(doc, "九、扩展方向", 1)
    ext_rows = [
        ["课表查询", "对接教务系统 API", "在 _answer_realtime() 加分支"],
        ["成绩查询", "对接教务系统 API（学号认证）", "需先解决身份认证"],
        ["校历日期", "维护一张学期日期表", "rule-based 即可"],
        ["多轮对话", "保留最近 N 轮 + LLM 总结", "需引入会话状态"],
        ["RAG 模式", "把 FAQ 语料喂给 LLM", "效果更好但成本高"],
    ]
    add_table(doc, ["扩展项", "思路", "接入位置"], ext_rows, col_widths=[3, 6, 5])

    # ============ 十、上线 checklist ============
    add_h(doc, "十、上线 Checklist", 1)
    add_para(doc, "□ 申请 DeepSeek API Key 并充值")
    add_para(doc, "□ 申请和风天气 API Key（个人开发者免费 1000 次/天）")
    add_para(doc, "□ 用环境变量注入密钥，不进 git")
    add_para(doc, "□ 把 HEFENG_BASE_URL 从 devapi 切到 api（生产域名）")
    add_para(doc, "□ 在 DEEPSEEK_SYSTEM_PROMPT 里加本校具体信息")
    add_para(doc, "□ 配置 IP/用户级 rate limit（防 LLM 滥用）")
    add_para(doc, "□ 添加「AI 生成，仅供参考」标签已被自动加上，UI 验证是否显眼")
    add_para(doc, "□ 跑 tests/test_fallback.py 全绿")
    add_para(doc, "□ 跑 evaluate.py 验证 FAQ 主路径未回归")

    # ============ 附录 ============
    add_h(doc, "附录 A：日志样例", 1)
    add_para(doc, "所有问答都会写到 logs/qa.log，未命中单独写到 logs/unmatched.jsonl。")
    add_para(doc, "v4 还新增了：")
    add_code(
        doc,
        "fallback_dispatch  → 路由决策日志\n"
        "llm_call_ok        → LLM 调用成功 + 耗时 + token 用量\n"
        "llm_api_error      → LLM 调用失败（带错误信息）\n"
        "weather_api_error  → 天气 API 调用失败",
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUT))
    print(f"✓ 已生成：{OUT}")
    print(f"  大小：{OUT.stat().st_size} bytes")


if __name__ == "__main__":
    main()
