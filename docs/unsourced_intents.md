# 无溯源意图清单（unsourced intents）

- **语料快照**：`data/qa_corpus.json` 1.15.1，83 意图 / 643 问法
- **口径**：`_meta` 缺失 —— 既没有官方通知原文可摘，也没有显式标注为「引导型」
- **生成方式**：`python scripts/report_unsourced.py`（规则可重算，非手填）
- **结论**：**1 / 83 个意图无溯源**

> 风险分级由两条信号自动判定：答案里是否出现**具体校方事实**（日期/时刻/金额/数量/电话/网址/地点），
> 以及是否带**兜底措辞**（「以…为准」这类自我限定）。

## 一、总览

| 类别 | 意图数 | 溯源状态 | 说明 |
|---|---|---|---|
| `real_notice_v3` | 24 | ✅ 有官方通知原文 | 全部是部门前缀 `jwc_` / `xsc_` / `xxh_`，含 `url` + `title` + `date` |
| `official_doc` | 30 | ✅ 有官方文档/页面 | `dorm_repair`, `enrollment_report`, `psych_counseling`, `jwc_student_id_reissue`, `jwc_certificate_issue`, `jwc_certificate_correction`, `jwc_diploma_reissue`, `zs_contact`, `library_contact`, `library_service`, `library_book_lost`, `library_purchase`, `jwc_suspend_resume`, `jwc_exam_defer`, `jwc_graduation_project`, `major_intro`, `zs_admission_query`, `tuition_fee`, `dorm_summer_stay`, `zs_registry_copy`, `enrollment_checkin`, `archive_transfer`, `party_org_transfer`, `household_migration`, `freshman_military_service`, `campus_transport_route`, `tuition_payment`, `student_loan`, `department_phone`, `campus_building_location`，含 `url` + `title`，来源为官方 PDF/网页（v1.6.0 新增）|
| `guidance` | 8 | ⚠️ 有标注、无原文 | `jwc_major_change`, `off_campus_info`, `zs_notice_addr_change`, `card_freeze`, `card_realname`, `dorm_electricity`, `academic_calendar`, `zs_score_line`，正文已声明以官方为准 |
| `manual_verified` | 20 | 🟡 **人工核实，无原文** | 无 url 可引，但有核实对象与核实日期（见第三节）；可信度高于「作者推测」、低于「有原文可核」 |
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
| `department_phone` | `official_doc` | 《学生手册》学生常用电话表 + 招生信息网《新生入学须知》附表 | [学校行政、学院办公电话（含办公室位置）](https://zs.niit.edu.cn/_upload/article/files/12/fc/e73dc3ed4e8da59f2e8187d79edb/3aa1181c-66bc-40f3-abe6-2b2b9af0a258.pdf) | 2026-09-17 |
| `campus_building_location` | `official_doc` | 《学生手册》校区平面示意图（用户提供扫描件） | [校园楼宇与设施位置（仙林 / 天堂校区）](None) | 2026-09-17 |
| `library_book_lost` | `official_doc` | 图书馆官网 | [违章处罚条例](https://tsg.niit.edu.cn/b3/74/c5899a45940/page.htm) | 2022-03-03 |
| `library_contact` | `official_doc` | 图书馆官网 | [本馆电话](https://tsg.niit.edu.cn/bgdh/list.htm) | 2026-09-15 |
| `library_purchase` | `official_doc` | 图书馆官网 | [资源荐购](https://tsg.niit.edu.cn/zyjg/list.htm) | 2026-09-15 |
| `library_service` | `official_doc` | 图书馆官网 | [常见问题](https://tsg.niit.edu.cn/cjwt/list.htm) | 2026-09-15 |
| `dorm_repair` | `official_doc` | 学工处 | [宿舍报修线上操作指南（企业微信 → 工作台 → 学工应用 → 宿舍报修）](https://xsc.niit.edu.cn/_upload/article/files/3c/c5/53850e734f1cbf1164e3f61cc23e/0b03ebba-dc97-40ed-99d7-6129251acd04.pdf) | 2026-09-14 |
| `psych_counseling` | `official_doc` | 学工处 | [心理中心心理咨询安排与预约方式（微信公众号「心海导航」）](https://xsc.niit.edu.cn/b8/8d/c3816a47245/page.htm) | 2021-03-01 |
| `xsc_academic_scholarship` | `real_notice_v3` | 学工处 | [南京工业职业技术大学优秀学生学业奖学金](https://xsc.niit.edu.cn/16/48/c3818a71240/page.htm) | 2025-11-17 |
| `xsc_commute_apply` | `real_notice_v3` | 学工处 | [南京工业职业技术大学学生走读管理办法](https://xsc.niit.edu.cn/f0/25/c8239a61477/page.htm) | 2023-09-01 |
| `xsc_dorm_6s` | `real_notice_v3` | 学工处 | [南京工业职业技术大学学生公寓6S管理细则](https://xsc.niit.edu.cn/f0/24/c8239a61476/page.htm) | 2023-09-01 |
| `xsc_excellent_graduate` | `real_notice_v3` | 学工处 | [关于开展2026届优秀毕业生评选工作的通知](https://xsc.niit.edu.cn/28/96/c3793a75926/page.htm) | 2026-04-15 |
| `xsc_impoverish_certify` | `real_notice_v3` | 学工处 | [家庭经济困难学生认定](https://xsc.niit.edu.cn/13/0a/c3818a70410/page.htm) | 2025-10-14 |
| `xsc_national_scholarship` | `real_notice_v3` | 学工处 | [关于开展2025年国家奖学金评选工作的通知](https://xsc.niit.edu.cn/13/96/c3793a70550/page.htm) | 2025-10-10 |
| `xsc_veteran_aid` | `real_notice_v3` | 学工处 | [退役士兵国家助学金](https://xsc.niit.edu.cn/1f/1d/c3818a73501/page.htm) | 2026-04-15 |
| `dorm_summer_stay` | `official_doc` | 学生工作部（处）官网 | [关于做好2024年暑期学生留校住宿工作的通知](https://xsc.niit.edu.cn/f0/26/c8239a61478/page.htm) | 2024-06-18 |
| `major_intro` | `official_doc` | 招生信息网 | [学院及本科专业设置](https://zs.niit.edu.cn/xyjzysz/list.htm) | 2026-09-15 |
| `zs_admission_query` | `official_doc` | 招生信息网 | [2026年高考招生（录取结果、通知书寄发情况查询）](https://zs.niit.edu.cn/0e/5b/c2896a69211/page.htm) | 2026-07-22 |
| `zs_contact` | `official_doc` | 招生信息网 | [咨询方式](https://zs.niit.edu.cn/zxfs/list.htm) | 2026-09-15 |
| `zs_registry_copy` | `official_doc` | 招生信息网 | [录取名册复印申请](https://zs.niit.edu.cn/lqmcsq/list.htm) | 2026-09-15 |
| `archive_transfer` | `official_doc` | 招生信息网《新生入学须知》（zs.niit.edu.cn/rxxz 栏目内嵌 PDF） | [需办理的有关手续 · 档案转接](https://zs.niit.edu.cn/_upload/article/files/12/fc/e73dc3ed4e8da59f2e8187d79edb/3aa1181c-66bc-40f3-abe6-2b2b9af0a258.pdf) | 2023-07 |
| `campus_transport_route` | `official_doc` | 招生信息网《新生入学须知》（zs.niit.edu.cn/rxxz 栏目内嵌 PDF） | [乘车路线（仙林校区 / 天堂校区）](https://zs.niit.edu.cn/_upload/article/files/12/fc/e73dc3ed4e8da59f2e8187d79edb/3aa1181c-66bc-40f3-abe6-2b2b9af0a258.pdf) | 2023-07 |
| `enrollment_checkin` | `official_doc` | 招生信息网《新生入学须知》（zs.niit.edu.cn/rxxz 栏目内嵌 PDF） | [报到流程（网上预报到 + 现场报到）](https://zs.niit.edu.cn/_upload/article/files/12/fc/e73dc3ed4e8da59f2e8187d79edb/3aa1181c-66bc-40f3-abe6-2b2b9af0a258.pdf) | 2023-07 |
| `enrollment_report` | `official_doc` | 招生信息网《新生入学须知》（zs.niit.edu.cn/rxxz 栏目内嵌 PDF） | [新生报到（时间 / 材料 / 流程）](https://zs.niit.edu.cn/_upload/article/files/12/fc/e73dc3ed4e8da59f2e8187d79edb/3aa1181c-66bc-40f3-abe6-2b2b9af0a258.pdf) | 2023-07 |
| `freshman_military_service` | `official_doc` | 招生信息网《新生入学须知》（zs.niit.edu.cn/rxxz 栏目内嵌 PDF） | [新生应征入伍保留入学资格手续办理](https://zs.niit.edu.cn/_upload/article/files/12/fc/e73dc3ed4e8da59f2e8187d79edb/3aa1181c-66bc-40f3-abe6-2b2b9af0a258.pdf) | 2023-07 |
| `household_migration` | `official_doc` | 招生信息网《新生入学须知》（zs.niit.edu.cn/rxxz 栏目内嵌 PDF） | [需办理的有关手续 · 户口迁移](https://zs.niit.edu.cn/_upload/article/files/12/fc/e73dc3ed4e8da59f2e8187d79edb/3aa1181c-66bc-40f3-abe6-2b2b9af0a258.pdf) | 2023-07 |
| `party_org_transfer` | `official_doc` | 招生信息网《新生入学须知》（zs.niit.edu.cn/rxxz 栏目内嵌 PDF） | [需办理的有关手续 · 党团组织关系转接](https://zs.niit.edu.cn/_upload/article/files/12/fc/e73dc3ed4e8da59f2e8187d79edb/3aa1181c-66bc-40f3-abe6-2b2b9af0a258.pdf) | 2023-07 |
| `student_loan` | `official_doc` | 招生信息网《新生入学须知》（zs.niit.edu.cn/rxxz 栏目内嵌 PDF） | [家庭经济困难学生助学办法 · 生源地信用助学贷款](https://zs.niit.edu.cn/_upload/article/files/12/fc/e73dc3ed4e8da59f2e8187d79edb/3aa1181c-66bc-40f3-abe6-2b2b9af0a258.pdf) | 2023-07 |
| `tuition_payment` | `official_doc` | 招生信息网《新生入学须知》（zs.niit.edu.cn/rxxz 栏目内嵌 PDF） | [学杂费缴费方式（网上缴费入口）](https://zs.niit.edu.cn/_upload/article/files/12/fc/e73dc3ed4e8da59f2e8187d79edb/3aa1181c-66bc-40f3-abe6-2b2b9af0a258.pdf) | 2023-07 |
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
| `jwc_certificate_correction` | `official_doc` | 教务处办事指南 | [学历勘误办理](https://jwc.niit.edu.cn/b2/c1/c2538a45761/page.htm) | 2022-02-21 |
| `jwc_certificate_issue` | `official_doc` | 教务处办事指南 | [学历证明开具](https://jwc.niit.edu.cn/b2/c2/c2538a45762/page.htm) | 2022-02-21 |
| `jwc_diploma_reissue` | `official_doc` | 教务处办事指南 | [毕业证明书办理流程](https://jwc.niit.edu.cn/b2/c0/c2538a45760/page.htm) | 2022-02-21 |
| `jwc_exam_defer` | `official_doc` | 教务处办事指南 | [缓考流程（流程图附件）](https://jwc.niit.edu.cn/_upload/article/files/fe/b2/bbc2247d486abb11cb7832584634/ea90932d-b196-4a3c-9f41-86b01e4f7e3a.pdf) | 2026-09-15 |
| `jwc_student_id_reissue` | `official_doc` | 教务处办事指南 | [学生证补办流程](https://jwc.niit.edu.cn/b2/bf/c2538a45759/page.htm) | 2022-02-21 |
| `jwc_suspend_resume` | `official_doc` | 教务处办事指南 | [休复学流程（流程图附件）](https://jwc.niit.edu.cn/_upload/article/files/9d/9a/e2dc9cbe469db86eda1cde23441c/3ec226ea-89af-451b-8cc6-c4956a3cbfdc.pdf) | 2026-09-15 |
| `jwc_graduation_project` | `official_doc` | 教务处官网 | [顶岗实习与毕业设计](https://jwc.niit.edu.cn/2374/list.htm) | 2026-09-15 |
| `xxh_cloud_disk` | `real_notice_v3` | 数智化处 | [关于启用校园云盘的通知](https://xxh.niit.edu.cn/13/62/c2265a70498/page.htm) | 2025-10-16 |
| `xxh_net_auth` | `real_notice_v3` | 数智化处 | [关于优化校园网认证服务的通知](https://xxh.niit.edu.cn/18/d9/c2265a71897/page.htm) | 2025-12-11 |
| `xxh_openclaw_ban` | `real_notice_v3` | 数智化处 | [关于严禁在校内使用OpenClaw软件的通知](https://xxh.niit.edu.cn/1c/af/c2265a72879/page.htm) | 2026-03-16 |
| `xxh_smart_bot` | `real_notice_v3` | 数智化处 | [关于学校启用智能机器人服务的通知](https://xxh.niit.edu.cn/12/10/c2265a70160/page.htm) | 2025-09-19 |
| `xxh_student_email` | `real_notice_v3` | 数智化处 | [关于在校学生开通校园邮箱的通知](https://xxh.niit.edu.cn/0f/09/c2265a69385/page.htm) | 2025-07-03 |
| `xxh_wifi_drop` | `real_notice_v3` | 数智化处 | [校园无线网终端频繁掉线问题的参考处理方案](https://xxh.niit.edu.cn/02/54/c2265a66132/page.htm) | 2025-03-20 |
| `tuition_fee` | `official_doc` | 计划财务处官网 | [收费公示牌（2024）](https://cwc.niit.edu.cn/f5/64/c2340a62820/page.htm) | 2024-10-11 |

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
| `express_pickup` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `grade_query` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `leave_apply` | 人工核实（职能部门 / 现场问询，2026-09-14） | 2026-09-14 |
| `library_borrow` | 人工核实（图书馆流通部电话确认，2026-09-15） | 2026-09-15 |
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

`zs_notice_addr_change` 是 `guidance` 型（无原文可摘）：`source=招生信息网`、`title=录取通知书收件信息修改申请`、`date=2026-09-15`。

> 该栏目页经核实**当前无任何正文**（原始 HTML：0 个 form、0 个 iframe、0 个正文容器），并非渲染或抓取问题，因此不再列为「待人工回填」。答案改为可操作兜底：未寄出联系招生办、已寄出凭 EMS 单号走邮政渠道。

`card_freeze` 是 `guidance` 型（无原文可摘）：`source=计划财务处官方微信公众号`、`title=【答疑】校园卡账户冻结怎么办？`、`date=2026-09-15`。

> 微信图文正文无法被程序抓取（服务端返回「请在微信客户端打开」墙），因此只给入口不摘步骤。需人工打开原文回填后可升级为 official_doc。

`card_realname` 是 `guidance` 型（无原文可摘）：`source=计划财务处官方微信公众号`、`title=校园虚拟卡申请及实名认证操作流程`、`date=2026-09-15`。

> 与既有 card_recharge（充值）、lost_card（挂失补办）区分：本条专指实名认证与虚拟卡。微信正文无法程序抓取，仅给入口。

`dorm_electricity` 是 `guidance` 型（无原文可摘）：`source=计划财务处官方微信公众号`、`title=学生公寓电控充值使用说明`、`date=2026-09-15`。

> 与既有 card_recharge 边界：本条是宿舍电费（空调/照明电控），不是校园卡余额充值。微信正文无法程序抓取，仅给入口。

`academic_calendar` 是 `guidance` 型（无原文可摘）：`source=学校官网`、`title=学校校历`、`date=2026-09-15`。

> 校历内容为图片，正文无法提取，故只给查询入口不给日期 —— 学年敏感信息固化在语料里必然过期。

`zs_score_line` 是 `guidance` 型（无原文可摘）：`source=招生信息网`、`title=职教高考分数 / 专转本招生分数`、`date=2026-09-15`。

> 栏目内每条记录都是某一年的分数线（2020-2026 共 11 条 / 15 条），任何单年数据都会过期，故只给栏目入口。

### 无 `_meta` 但带顶层 `source` 文本声明的意图（不计入溯源）

| 意图 | 顶层 source（仅文本声明）| 风险等级 |
|---|---|---|
| `campus_map_guide` | 校园问答平台 | 豁免（未核实）|
