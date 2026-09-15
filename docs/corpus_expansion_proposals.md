# 官网语料扩充提案：去重后的新增意图清单

> 抓取日期：2026-09-15 ｜ 基线：`data/qa_corpus.json` **v1.8.0（50 意图 / 417 问法）**
>
> **落地进度**：本文档最初是提案，现已**三批全部执行完** ——
> **批次 A**（v1.9.0，10 个意图）、**批次 B**（v1.10.0，8 个意图）、**批次 C**（v1.11.0，4 个意图）。
> 语料现为 **72 意图 / 549 问法**；召回@1 99.5%（200/201）、误触发 0%、pytest 184 passed。
> 执行中的调整（`library_training` 并入 `library_service`、`library_locker` 剔除、`library_service` 不写借阅册数、
> 学费写入金额并标注文号、暑期留校只写跨年稳定部分）均已记入语料 `changelog` 与 `_meta.note`。
> **§5 的三项待核实仍未处理**（借阅册数口径冲突、通知书改址页正文、lost_card 里的学生证问法归属）。
>
> ⚠️ **一处事实更正**：§5 风险 2 原写「收费公示牌无正文、金额摘不到」——**这是错的**。
> 该页面挂着一份 2 页 PDF 收费表，`pypdf` 可完整提取（学费 5800/5200/6800、住宿费 1500/1200、含批准文号）。
> 教训：「页面没正文」不等于「数据取不到」，**要再往下翻一层找附件**。

---

## 1. 本次抓取范围与可达性

| 站点 | URL | 状态 |
|---|---|---|
| 学校主站（站群） | https://www.niit.edu.cn | ✅ 200 |
| 招生信息网 | https://zs.niit.edu.cn | ✅ 200 |
| 教务处 | https://jwc.niit.edu.cn | ✅ 200 |
| 学生工作部（处） | https://xsc.niit.edu.cn | ✅ 200 |
| 图书馆 | https://tsg.niit.edu.cn | ✅ 200 |
| 信息公开 | https://xxgk.niit.edu.cn | ✅ 200 |
| 后勤管理服务中心 | https://hqglc.niit.edu.cn | ✅ 200 |
| 计划财务处 | https://cwc.niit.edu.cn | ✅ 200 |
| 信息化（数智化）处 | https://xxh.niit.edu.cn | ✅ 200 |
| 就业创业信息网 | http://niit.91job.org.cn | ✅（官网「招生就业」栏目给出的入口） |
| ~~job.niit.edu.cn~~ | — | ❌ **不可达**（不存在该子站，别再试） |

**方法说明**：走系统代理出网；校站证书链不被信任 → 关闭证书校验；编码不统一（UTF-8 / GBK 混用）→ 自动嗅探 `charset` 后再解码；可见文本提取前先剥掉 `<script>`/`<style>`，否则会把 JS 代码当成正文。**抓到的每条 URL 都已在 §4 标注，未抓取验证过的一律不入清单。**

---

## 2. 去重基线：现有 50 个意图按业务分类盘点

| 业务分类 | 现有意图 | 缺口 |
|---|---|---|
| 图书馆 | `library_hours` `library_borrow` `library_seat` | ❌ **服务范围 / 丢书赔偿 / 存包柜 / 荐购 / 培训 / 联系方式** |
| 一卡通·缴费 | `lost_card` `card_recharge` | ❌ **冻结解冻 / 实名认证·虚拟卡 / 宿舍电费充值** |
| 学籍·教务 | `jwc_major_change` `transcript` `jwc_veteran_transfer` `jwc_bachelor_degree` | ❌ **学生证补办 / 学历证明 / 毕业证明书 / 休复学 / 缓考 / 申诉** |
| 考试考务 | `jwc_cet_signup` `jwc_english_ab` `jwc_retake_signup` `jwc_classroom_closed` | ⚠️ 缺缓考、作弊申诉（重修已有） |
| 奖助勤贷 | `scholarship` `xsc_national_scholarship` `xsc_academic_scholarship` `xsc_impoverish_certify` `xsc_veteran_aid` `xsc_excellent_graduate` | ⚠️ 助学贷款、勤工助学**官网未见独立栏目**（见 §5） |
| 宿舍后勤 | `dorm_repair` `dorm_curfew` `xsc_dorm_6s` `xsc_commute_apply` | ❌ **电费充值 / 暑期留校 / 宿舍空调热水** |
| 招生录取 | `enrollment_report`（仅限新生报到） | 🔴 **几乎全空**：录取查询、分数线、学费、专业目录、咨询方式 |
| 就业实习 | `career_center` | ⚠️ 顶岗实习/毕业设计属**教学环节**，与就业服务不同源 |
| 校园生活 | `canteen_info` `express_pickup` `printing_service` `venue_booking` `club_recruit` `psych_counseling` `medical` `lost_found` `campus_map_guide` `off_campus_info` | ❌ **校历 / 班车 / 访客入校** |

---

## 3. 新增意图提案（去重后共 **22 个**）

标记说明：🔴 = **信息随年份/学年变化**（答案须写成引导指向当年度原文，或 `_meta.date` 逐年复核）；
`type` 列是建议的 `_meta.type`（写入前二次确认）。

### 3.1 招生录取（考生 / 家长）

| # | 建议 tag | 真实问法示例 | 来源 URL | 🔴 | 建议 type |
|---|---|---|---|---|---|
| 1 | `zs_admission_query` | 录取结果什么时候能查 / 我被南工录取了吗 / 通知书什么时候寄 / 通知书快递单号在哪查 / 录取查询入口在哪 | https://zs.niit.edu.cn/0e/5b/c2896a69211/page.htm | 🔴 | `real_notice_v3` |
| 2 | `zs_notice_addr_change` | 录取通知书寄到哪 / 收件地址填错了能改吗 / 想换一个收货地址怎么申请 / 通知书邮寄信息在哪改 | https://zs.niit.edu.cn/lqtzssjxxxgsq/list.htm | | `real_notice_v3` |
| 3 | `zs_score_line` | 南工往年录取分数线多少 / 职教高考要考多少分 / 专转本分数线是多少 / 去年最低分是多少 | https://zs.niit.edu.cn/2936/list.htm ・ https://zs.niit.edu.cn/zzbzsfs/list.htm | 🔴 | `real_notice_v3` |
| 4 | `zs_contact` | 招生办电话多少 / 怎么联系招生办 / 招生咨询的 QQ 群是多少 / 招办公众号叫什么 / 学校地址和邮编 | https://zs.niit.edu.cn/zxfs/list.htm | | `official_doc` |
| 5 | `major_intro` | 学校有哪些学院 / 都有什么专业 / 机械工程学院有什么专业 / 本科专业有哪些 | https://zs.niit.edu.cn/2899/list.htm ・ https://zs.niit.edu.cn/xyjzysz/list.htm | 🔴 | `official_doc` |
| 6 | `tuition_fee` | 学费一年多少钱 / 住宿费是多少钱 / 收费标准在哪看 / 除了学费还有别的费用吗 | https://cwc.niit.edu.cn/f5/64/c2340a62820/page.htm ・ https://xxgk.niit.edu.cn/2431/list.htm | 🔴 | `guidance`（见 §5 说明） |
| 7 | `zs_registry_copy` | 录取名册怎么复印 / 需要当年的录取名册去哪申请 / 档案馆能复印录取名册吗 | https://zs.niit.edu.cn/lqmcsq/list.htm | | `official_doc` |

### 3.2 学籍教务（在校生）

| # | 建议 tag | 真实问法示例 | 来源 URL | 🔴 | 建议 type |
|---|---|---|---|---|---|
| 8 | `jwc_student_id_reissue` | 学生证丢了怎么补办 / 补办学生证要多少钱 / 补学生证要带照片吗 / 补办的学生证什么时候能拿 | https://jwc.niit.edu.cn/b2/bf/c2538a45759/page.htm | ⚠️ 工本费 | `official_doc` |
| 9 | `jwc_certificate_issue` | 怎么开在读证明 / 学历证明去哪开 / 要开学历证明寄送哪些材料 / 学历证明办下来要多久 | https://jwc.niit.edu.cn/b2/c2/c2538a45762/page.htm | | `official_doc` |
| 10 | `jwc_certificate_correction` | 学历信息填错了能改吗 / 学历勘误怎么办理 | https://jwc.niit.edu.cn/b2/c1/c2538a45761/page.htm | | `official_doc` |
| 11 | `jwc_diploma_reissue` | 毕业证丢了能补吗 / 毕业证明书怎么办理 / 毕业证不能补办那能开什么证明 | https://jwc.niit.edu.cn/b2/c0/c2538a45760/page.htm | | `official_doc` |
| 12 | `jwc_suspend_resume` | 怎么申请休学 / 休学之后怎么复学 / 休学最长多久 / 休学流程找谁签字 | 教务处办事指南「休复学流程」PDF：https://jwc.niit.edu.cn/2365/list.htm （PDF 直链随栏目更新，建议以栏目页为来源） | | `official_doc` |
| 13 | `jwc_exam_defer` | 考试去不了能申请缓考吗 / 缓考怎么办手续 / 生病了能延后考试吗 / 缓考申请找谁签字 | 教务处办事指南「缓考流程」PDF：https://jwc.niit.edu.cn/2365/list.htm | | `official_doc` |
| 14 | `jwc_graduation_project` | 顶岗实习什么时候开始 / 毕业设计怎么选题 / 顶岗实习要交什么材料 / 毕业实习和毕业设计是一回事吗 | https://jwc.niit.edu.cn/2374/list.htm | | `official_doc` |
| 15 | `jwc_appeal` | 考试作弊会怎么处理 / 对处分不服可以申诉吗 / 申诉找哪个部门 / 学生申诉有没有时间限制 | https://xxgk.niit.edu.cn/2449/list.htm ・ https://xxgk.niit.edu.cn/2446/list.htm（学籍管理办法） | | `guidance`（见 §5 说明） |

> ⚠️ **13 与既有 `jwc_retake_signup` 的边界**：`retake` 是「重修/补考**报名**」，13 是「不能参加考试 → 申请**缓考**」。
> 问法必须带限定词「缓考 / 延期考试」，否则会互相抢。
> ⚠️ **14 与既有 `career_center` 的边界**：`career_center` 讲招聘会/就业手续（学工口径），14 是**教学环节**（教务处口径），问法统一带「顶岗实习 / 毕业设计」。

### 3.3 图书馆

| # | 建议 tag | 真实问法示例 | 来源 URL | 🔴 | 建议 type |
|---|---|---|---|---|---|
| 16 | `library_service` | 图书馆能借多少本书 / 图书馆除了借书还能干嘛 / 有没有电子阅览室 / 怎么荐购新书 | https://tsg.niit.edu.cn/cjwt/list.htm | 🔴 册数待复核 | `official_doc` |
| 17 | `library_book_lost` | 书丢了要赔多少钱 / 借阅的书弄丢了怎么办 / 书弄脏了会不会罚款 | https://tsg.niit.edu.cn/cjwt/list.htm ・ https://tsg.niit.edu.cn/b3/74/c5899a45940/page.htm（违章处罚条例） | | `official_doc` |
| 18 | `library_locker` | 图书馆有存包柜吗 / 存包柜怎么申请 / 临时存放处的东西会被清走吗 | https://tsg.niit.edu.cn/0e/63/c5923a69219/page.htm ・ 存包柜申请通知：https://mp.weixin.qq.com/s/c4rf9rBqH9QjD2hPbhy_Zg | | `guidance` |
| 19 | `library_purchase` | 想看的书图书馆没有怎么办 / 怎么推荐图书馆买书 / 荐购之后多久能上架 | https://tsg.niit.edu.cn/zyjg/list.htm | | `official_doc` |
| 20 | `library_training` | 图书馆有使用培训吗 / 怎么预约图书馆讲座 / 电子资源培训能班级集体报名吗 | https://tsg.niit.edu.cn/yypx/list.htm | | `official_doc` |
| 21 | `library_contact` | 图书馆电话多少 / 借还书有问题找谁 / 图书馆各个部门怎么联系 | https://tsg.niit.edu.cn/bgdh/list.htm ・ https://tsg.niit.edu.cn/zxzt/list.htm | | `official_doc` |

### 3.4 一卡通 / 宿舍后勤 / 财务

| # | 建议 tag | 真实问法示例 | 来源 URL | 🔴 | 建议 type |
|---|---|---|---|---|---|
| 22 | `card_freeze` | 校园卡被冻结了怎么办 / 卡刷不出来是什么原因 / 账户冻结怎么解冻 | https://mp.weixin.qq.com/s/eEj-uFOr7iHLOXXweOnbLA （计财处【答疑】校园卡账户冻结怎么办） | | `official_doc` |
| 23 | `card_realname` | 校园卡怎么实名认证 / 虚拟卡怎么申请 / 手机上的校园卡怎么用 | https://mp.weixin.qq.com/s/yrEMuihvalj1r9I7XNdibg ・ https://mp.weixin.qq.com/s/njWlO6zxxb9yg7d75LB-xA | | `official_doc` |
| 24 | `dorm_electricity` | 宿舍电费在哪交 / 宿舍没电了怎么充值 / 电控怎么用 / 电费充值了还是不来电怎么办 | https://mp.weixin.qq.com/s/pU6_I_4MMeo4-L9gViwqrA （学生公寓电控充值使用说明） | | `official_doc` |
| 25 | `dorm_summer_stay` | 暑假能留校住宿吗 / 暑假留校住宿怎么申请 / 寒假留校要办手续吗 | https://xsc.niit.edu.cn/f0/26/c8239a61478/page.htm | 🔴 | `guidance` |

> ⚠️ **24 与既有 `card_recharge` 的边界**：`card_recharge` 是给**校园卡充值**（吃饭洗澡），24 是**宿舍电费**（空调/照明电控）。
> 问法必须带「电费 / 电控 / 宿舍用电」，否则会被充值类意图抢走。

### 3.5 校园生活 / 访客

| # | 建议 tag | 真实问法示例 | 来源 URL | 🔴 | 建议 type |
|---|---|---|---|---|---|
| 26 | `academic_calendar` | 今年校历在哪看 / 寒假什么时候开始 / 暑假放多久 / 什么时候开学 | https://www.niit.edu.cn/calendar/list.htm | 🔴 | `official_doc` |
| 27 | `campus_shuttle` | 校区之间有班车吗 / 班车几点发车 / 班车时间表在哪看 | https://www.niit.edu.cn/4093/list.htm | 🔴 | ⚠️ **暂缓**，见 §5 |

**合计：26 个候选，其中 25 个建议入库，1 个（`campus_shuttle`）建议先人工复核。**

---

## 4. 不建议新增 / 已从候选中剔除

| 候选 | 结论 | 理由 |
|---|---|---|
| 就业信息网「招聘信息在哪看」 | **不新增**，改补进 `career_center` 答案 | 与既有 `career_center` 语义重叠。但**建议把 http://niit.91job.org.cn 补进其答案和 `_meta.url`**（现有答案是 `manual_verified`，没有可引用 URL） |
| 「助学贷款怎么申请」「勤工助学岗位」 | **不入库** | 本次在 xsc / xxgk 均未找到官方一手页面（只有零散评选通知）。**要么人工核实后走 `manual_verified`，要么不写**，不能照网上的通用流程编 |
| 2020-2021 年度收费情况公示 | **剔除（过期）** | https://xxgk.niit.edu.cn/a8/39/c2431a43065/page.htm 已被 2024 版取代，且金额类信息过期即等于答错 |
| 图书馆「电子资源访问」直链 | **剔除（失效）** | https://tsg.niit.edu.cn/f1/73/c5880a61811/page.htm 本次访问返回 **HTTP 410**。入口应从图书馆首页「电子资源」栏目进入，不要引用该直链 |
| 后勤「服务指南」里的用印单/住房申请表/内部请假单 | **剔除（与学校答疑无关）** | 面向后勤内部员工，不是学生高频问题 |
| 访客「怎么预约进校 / 校外车辆能不能进」 | **暂不入库** | 官网本次未查到公开的来访管理办法。**没有官方来源就不写** —— 这是本项目的红线 |

---

## 5. 三个必须你拍板的冲突与风险

### 🔴 风险 1：图书馆借书册数，官网与现有语料**直接打架**

| 来源 | 说法 |
|---|---|
| 图书馆官网《借书规则》（发布 2022-03-03）<br>https://tsg.niit.edu.cn/b3/71/c5899a45937/page.htm | **每位学生 30 册，借期 60 天，续借 30 天**（教师 50 册 / 365 天） |
| 现有语料 `library_borrow`（v1.8.0，`manual_verified` 人工核实） | 本科生 10 册 / 30 天，研究生 15 册 / 60 天，续借 1 次 30 天 |

两条路都不好看：**要么 v1.8.0 的人工核实数字错了（那就整个 tracability 存疑），要么官网 2022 年的规则已经改了没更新。**
建议：把这个作为 `docs/pending_items.md` 的 🔴 P0 项，打电话或现场找流通部（105 室）确认；确认前不要改 `library_borrow` 的答案。

### ⚠️ 风险 2：学费金额**摘不到**，只能做引导型

`收费公示牌（2024）` 页面**没有正文**，内容在图片/附件里，机器读不到；`xxgk` 的收费公示止于 2020-2021 年度，已过期。
结论：**`tuition_fee` 不要写任何具体数字**，答案写成「学费按省物价部门核定标准执行、见计财处当年度收费公示牌」+ 两个来源 URL，`_meta.type` 用 `guidance`。宁可引导，不可编造。

### ⚠️ 风险 3：`campus_shuttle`（班车）要不要复活

v1.2.1 曾**删除** `shuttle_bus`，理由是"班车时刻为占位事实、需按本校实际核实"。现在官网上确实存在该栏目：
`https://www.niit.edu.cn/4093/list.htm`。**栏目存在 ≠ 内容可用**，本次未取到时刻表正文。
建议：先人工打开看一下有没有时刻表；有 → 复活并带 URL；没有 → 保持删除状态。

### ⚠️ 尺度提醒（和上面无关，但入库前想清楚）

`jwc_appeal`（作弊处理 / 处分申诉）虽然信息价值高，但把「考试作弊怎么处理」做成 Demo 里的问答，面试演示时被问到会觉得画风偏灰。
建议写**流程引导型**（"以《学生违纪处分管理办法》为准，申诉向 xx 部门提出"），**不列具体处分档次**。这条请你决定要不要入。

---

## 6. 入库执行顺序建议

按「确定性 × 价值」排序，**先做不依赖任何猜谜的**：

1. **批次 A（有官方原文，可直接落成 `real_notice_v3` / `official_doc`）**：
   `jwc_student_id_reissue` `jwc_certificate_issue` `jwc_certificate_correction` `jwc_diploma_reissue`
   `zs_contact` `zs_notice_addr_change` `card_freeze` `card_realname` `dorm_electricity` `library_contact`
   —— 这 10 个都有逐字范围内的官方原文，不用猜任何事实，属于"低成本高确定性"。

2. **批次 B（有来源但内容要组织）**：`library_service` `library_book_lost` `library_purchase` `library_training`
   `library_locker` `jwc_suspend_resume` `jwc_exam_defer` `jwc_graduation_project` `academic_calendar` `major_intro`

3. **批次 C（🔴 年度敏感，必须做成引导型）**：`zs_admission_query` `zs_score_line` `tuition_fee` `dorm_summer_stay`

4. **先别动**：`jwc_appeal`（待你定）、`campus_shuttle`（待核实）、`zs_registry_copy`（低频）

**每批入库都要过的流程**（详见技能 `faq-corpus-extend-sync`）：
升 `meta.version` + 写 `changelog` → `tests/test_set.json` 补 2-3 条**不与语料重合**的改写问句 →
`python scripts/render_answerable_samples.py`（先跑 `--check`）→ 更新 README 计数 →
**重启后端**（改 json 不触发热重载）→ `python evaluate.py --show-error` → `pytest -q` → `ruff check .`。

定向探测别忘了：每次加完，把**新意图本身 + 邻居意图**的问句一起跑一遍，确认没互相抢
（历史教训：`canteen_info` 曾以余弦 0.6563 抢走「附近哪家火锅好吃」）。

---

## 7. 本次产出的留存说明

- 抓取工具在 `niit_crawl/niit.py`（工作区临时目录，未入库），带磁盘缓存，可重跑复核。
- **本清单建议仿照 `docs/unsourced_intents.md` 的处理方式**：它是**内部改进行动资产**，但白纸黑字写明了本项目还有哪些问题没弄清楚。要不要 git 提交，建议你自己决定（仓库是求职作品的话，这是一个暴露面）。
