# 无溯源意图清单（unsourced intents）

- **语料快照**：`data/qa_corpus.json` 1.8.0，50 意图 / 417 问法
- **口径**：`_meta` 缺失 —— 既没有官方通知原文可摘，也没有显式标注为「引导型」
- **生成方式**：`python scripts/report_unsourced.py`（规则可重算，非手填）
- **结论**：**1 / 50 个意图无溯源**

> 风险分级由两条信号自动判定：答案里是否出现**具体校方事实**（日期/时刻/金额/数量/电话/网址/地点），
> 以及是否带**兜底措辞**（「以…为准」这类自我限定）。

## 一、总览

| 类别 | 意图数 | 溯源状态 | 说明 |
|---|---|---|---|
| `real_notice_v3` | 24 | ✅ 有官方通知原文 | 全部是部门前缀 `jwc_` / `xsc_` / `xxh_`，含 `url` + `title` + `date` |
| `official_doc` | 2 | ✅ 有官方文档/页面 | `dorm_repair`, `psych_counseling`，含 `url` + `title`，来源为官方 PDF/网页（v1.6.0 新增）|
| `guidance` | 2 | ⚠️ 有标注、无原文 | `jwc_major_change`, `off_campus_info`，正文已声明以官方为准 |
| `manual_verified` | 21 | 🟡 **人工核实，无原文** | 无 url 可引，但有核实对象与核实日期（见第三节）；可信度高于「作者推测」、低于「有原文可核」 |
| **无 `_meta`** | **1** | ❌ **无溯源** | `campus_map_guide` |

> ⚠️ **关于顶层 `source` 字段**：本清单里标「无 `_meta`」的意图中，有 1 条带顶层 `source`
> （「校园问答平台」），但那只是作者手填的文本声明，**没有 url 可核**，
> 且代码（`app.py` / `agent.py`）**根本不读取该字段**——UI 来源标签来自兜底信息。
> 经核对，其中「后勤保障部」「学生处心理咨询中心」这两个部门名**在学校机构设置里并不存在**
> （真实应为「学工处·学生公寓管理科」「学工处·心理健康教育教研室」，`dorm_repair` / `psych_counseling`
> 已在 v1.6.0 改为 `official_doc` 并修正）。**因此顶层 `source` 一律不计入「有溯源」。**

**当前规律**：从官方通知/文档生成的意图（部门前缀）都带溯源；仍未溯源的 1 条见第二节风险分级。

## 二、风险分级

| 等级 | 含义 | 数量 | 意图 |
|---|---|---|---|
| **豁免** | 属平台自身功能说明，无需外部溯源 | 1 | `campus_map_guide` |

## 三、逐条明细

### 豁免 —— 无需外部溯源

| 意图 | 问法数 | 硬事实 | 兜底措辞 | 示例问句 |
|---|---|---|---|---|
| `campus_map_guide` | 8 | — | 有 | 地图在哪看 |

## 四、⚠️ 顺带扫出的疑似占位数据

规则扫描时命中的电话/网址值得单独确认（`example.*` 这类占位符已在 v1.5.1 修掉一处）：

| 意图 | 片段 | 疑点 |
|---|---|---|

## 五、建议的补齐路线

1. **先补 P0**：这些是「具体到数字」的断言，被追问一句就见底，优先挑问法多的。
   （v1.8.0 已把 `course_selection` / `library_borrow` / `transcript` / `medical` 等
   原 P0 条目通过人工核实补齐，现为 `manual_verified` —— 可作后续补条的参照格式。）
2. **补的方式三选一**：
   - 拿到官方通知原文 → 改写为「通知摘录型」，补 `_meta{source, category, url, title, date, type: real_notice_v3}`；
   - 拿到官方文档/网页（PDF、办事指南页等）→ 补 `_meta{...type: official_doc}`，正文保留可核实事实（如 `dorm_repair` / `psych_counseling` 在 v1.6.0 的做法）；
   - 拿不到原文 → 改为「引导型」，删掉所有具体数字，只留指引 + 官方渠道，
     补 `_meta.type = "guidance"`（照 `jwc_major_change` 的样子写）。
   - **顺手核一遍顶层 `source`**：凡带该字段的，确认部门名在学校机构设置里真实存在，否则修正或删除（死字段，不读也要保证别误导人）。
3. **原则不变**：宁可引导，不可编造。库里凡是「学校具体政策」的答案，编一条就把整个项目的可信度搭进去了。
4. 每补一条，把 `meta.changelog` 记一笔，并重跑本脚本把清单刷新。

## 附录：有溯源意图对照（补 `_meta` 时照这个格式写）

| 意图 | 类型 | 来源 | 通知/文档标题 | 日期 |
|---|---|---|---|---|
| `dorm_repair` | `official_doc` | 学工处 | [宿舍报修线上操作指南（企业微信 → 工作台 → 学工应用 → 宿舍报修）](https://xsc.niit.edu.cn/_upload/article/files/3c/c5/53850e734f1cbf1164e3f61cc23e/0b03ebba-dc97-40ed-99d7-6129251acd04.pdf) | 2026-09-14 |
| `psych_counseling` | `official_doc` | 学工处 | [心理中心心理咨询安排与预约方式（微信公众号「心海导航」）](https://xsc.niit.edu.cn/b8/8d/c3816a47245/page.htm) | 2021-03-01 |
| `xsc_academic_scholarship` | `real_notice_v3` | 学工处 | [南京工业职业技术大学优秀学生学业奖学金](https://xsc.niit.edu.cn/16/48/c3818a71240/page.htm) | 2025-11-17 |
| `xsc_commute_apply` | `real_notice_v3` | 学工处 | [南京工业职业技术大学学生走读管理办法](https://xsc.niit.edu.cn/f0/25/c8239a61477/page.htm) | 2023-09-01 |
| `xsc_dorm_6s` | `real_notice_v3` | 学工处 | [南京工业职业技术大学学生公寓6S管理细则](https://xsc.niit.edu.cn/f0/24/c8239a61476/page.htm) | 2023-09-01 |
| `xsc_excellent_graduate` | `real_notice_v3` | 学工处 | [关于开展2026届优秀毕业生评选工作的通知](https://xsc.niit.edu.cn/28/96/c3793a75926/page.htm) | 2026-04-15 |
| `xsc_impoverish_certify` | `real_notice_v3` | 学工处 | [家庭经济困难学生认定](https://xsc.niit.edu.cn/13/0a/c3818a70410/page.htm) | 2025-10-14 |
| `xsc_national_scholarship` | `real_notice_v3` | 学工处 | [关于开展2025年国家奖学金评选工作的通知](https://xsc.niit.edu.cn/13/96/c3793a70550/page.htm) | 2025-10-10 |
| `xsc_veteran_aid` | `real_notice_v3` | 学工处 | [退役士兵国家助学金](https://xsc.niit.edu.cn/1f/1d/c3818a73501/page.htm) | 2026-04-15 |
| `jwc_bachelor_degree` | `real_notice_v3` | 教务处 | [南京工业职业技术大学关于2026年8月授予本科毕业生学士学位的公示](https://jwc.niit.edu.cn/29/2e/c2370a76078/page.htm) | 2026-08-28 |
| `jwc_cet_signup` | `real_notice_v3` | 教务处 | [关于做好2026年上半年全国大学英语四六级考试报名工作的通知](https://jwc.niit.edu.cn/1c/1d/c2370a72733/page.htm) | 2026-03-10 |
| `jwc_classroom_closed` | `real_notice_v3` | 教务处 | [关于仙林校区及天堂校区教学楼限时封闭的通知](https://jwc.niit.edu.cn/23/7e/c2370a74622/page.htm) | 2026-06-05 |
| `jwc_english_ab` | `real_notice_v3` | 教务处 | [2026年上半年大学英语应用能力考试报名通知（AB级）](https://jwc.niit.edu.cn/1d/69/c2370a73065/page.htm) | 2026-03-25 |
| `jwc_major_elective_select` | `real_notice_v3` | 教务处 | [2026-2027-1学期专业选修课选课通知](https://jwc.niit.edu.cn/28/85/c2370a75909/page.htm) | 2026-07-24 |
| `jwc_pe_select` | `real_notice_v3` | 教务处 | [2026-2027-1学期体育俱乐部选课通知](https://jwc.niit.edu.cn/29/39/c2370a76089/page.htm) | 2026-08-30 |
| `jwc_public_select` | `real_notice_v3` | 教务处 | [2025-2026-2学期本科公共选修课程选课通知](https://jwc.niit.edu.cn/1d/4e/c2370a73038/page.htm) | 2026-03-24 |
| `jwc_quality_select` | `real_notice_v3` | 教务处 | [2026-2027-1学期本科素质拓展选修课选课通知](https://jwc.niit.edu.cn/28/86/c2370a75910/page.htm) | 2026-07-24 |
| `jwc_retake_signup` | `real_notice_v3` | 教务处 | [2025-2026学年第二学期重修报名通知](https://jwc.niit.edu.cn/1d/79/c2370a73081/page.htm) | 2026-03-26 |
| `jwc_textbook_pickup` | `real_notice_v3` | 教务处 | [关于2026-2027-1学期教材征订结果的公示](https://jwc.niit.edu.cn/28/c8/c2370a75976/page.htm) | 2026-08-01 |
| `jwc_veteran_transfer` | `real_notice_v3` | 教务处 | [关于做好我校2026年江苏省三年制高职（专科）退役大学生士兵'专转本'网上报名工作的通知](https://jwc.niit.edu.cn/1e/f0/c2370a73456/page.htm) | 2026-04-13 |
| `xxh_cloud_disk` | `real_notice_v3` | 数智化处 | [关于启用校园云盘的通知](https://xxh.niit.edu.cn/13/62/c2265a70498/page.htm) | 2025-10-16 |
| `xxh_net_auth` | `real_notice_v3` | 数智化处 | [关于优化校园网认证服务的通知](https://xxh.niit.edu.cn/18/d9/c2265a71897/page.htm) | 2025-12-11 |
| `xxh_openclaw_ban` | `real_notice_v3` | 数智化处 | [关于严禁在校内使用OpenClaw软件的通知](https://xxh.niit.edu.cn/1c/af/c2265a72879/page.htm) | 2026-03-16 |
| `xxh_smart_bot` | `real_notice_v3` | 数智化处 | [关于学校启用智能机器人服务的通知](https://xxh.niit.edu.cn/12/10/c2265a70160/page.htm) | 2025-09-19 |
| `xxh_student_email` | `real_notice_v3` | 数智化处 | [关于在校学生开通校园邮箱的通知](https://xxh.niit.edu.cn/0f/09/c2265a69385/page.htm) | 2025-07-03 |
| `xxh_wifi_drop` | `real_notice_v3` | 数智化处 | [校园无线网终端频繁掉线问题的参考处理方案](https://xxh.niit.edu.cn/02/54/c2265a66132/page.htm) | 2025-03-20 |

### `manual_verified` 型明细（人工核实，v1.8.0 新增）

| 意图 | 核实来源 | 核实日期 |
|---|---|---|
| `campus_wifi` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `canteen_info` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `card_recharge` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `career_center` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `club_recruit` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `course_selection` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `dorm_curfew` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `enrollment_report` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `express_pickup` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `grade_query` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `leave_apply` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `library_borrow` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `library_hours` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `library_seat` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `lost_card` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `lost_found` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `medical` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `printing_service` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `scholarship` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `transcript` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `venue_booking` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |

> 这一档**没有 url 可引**，是人工问询/现场确认得来的。它比「作者推测」可靠，
> 但仍会随政策变化过期 —— 正文里凡涉及时间、金额、地点、数量的数字，
> 每个学年至少复核一次。

`jwc_major_change` 是 `guidance` 型（无原文可摘）：`source=教务处`、`title=校内转专业办理指引（流程引导型，非通知摘录）`、`date=2026-09-11`。

> 本地未采集到学校转专业通知原文，本答案只写通用流程与国家标准层面的框架，不含任何校方具体日期 / 比例 / 门槛。取得官方原文后应替换为「通知摘录型」答案。

`off_campus_info` 是 `guidance` 型（无原文可摘）：`source=项目服务边界说明`、`title=服务范围说明`、`date=None`。

> 这是刻意的产品边界，不是校方政策，没有官方原文可引。此前「学校附近哪家火锅好吃」会被 canteen_info 以 0.6563 的余弦分抢走，答成校内食堂营业时间（答非所问）—— 新增本意图后由它承接。若日后接入周边生活服务数据，应改为 official_doc / real_notice_v3。

### 无 `_meta` 但带顶层 `source` 文本声明的意图（不计入溯源）

| 意图 | 顶层 source（仅文本声明）| 风险等级 |
|---|---|---|
| `campus_map_guide` | 校园问答平台 | 豁免（未核实）|
