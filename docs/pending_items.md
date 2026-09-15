# 待补充说明 / 待人工搜集审核 清单

> 生成于 2026-09-14，只读排查得出，**未改动任何代码**。
> 配合 `docs/fact_audit.md`（v1.6.0 事实审计）一起看。
> 口径：**第一部分 = 代码/文档内部不一致或覆盖缺口**（可直接改）；
> **第二部分 = 沙箱查不到、只能由人到线下/后台去核** 的内容。

---

## 0. 当前 git 状态（先对齐事实）

| 项 | 状态 |
|---|---|
| `32f97a5`（第一轮审查修复 8 项） | 已 commit，**未 push**（ahead 1） |
| 本轮 10 个文件改动 | **未 commit、未 add** |
| `docs/fact_audit.md` | 未跟踪（未 commit） |
| 工作树 | 有改动，线上服务应为旧行为 |

---

## 一、需要补充说明 / 内部不一致的问题

### 1.1 本轮改动"改了 A 没改 B"的残留（**2026-09-14 已收掉**）

| # | 位置 | 问题 | 处理 |
|---|---|---|---|
| 1 | `README.md` 表格行 | 仍写「反馈统计挪到页面底部，仅 **`?debug=1`** 显示」——与同文件调试模式段已改的 `FAQ_DEBUG` **自相矛盾** | ✅ 改为 `FAQ_DEBUG=1` |
| 2 | `tests/test_ui.py` docstring | 仍写「加 **?debug=1** 才该显示」，与实现不符 | ✅ 改为「设 FAQ_DEBUG=1 才该显示」 |
| 3 | `tests/test_ui.py` 调试用例 | **只有负向断言**（默认不出现调试字段）→ `_DEBUG_ENABLED` 逻辑写反/永远 False 也测不出来 | ✅ 新增 `test_debug_shown_when_enabled`（设 `FAQ_DEBUG=1` 断言 `trace_id` 出现）。已实测 `at.main.caption` **能**抓到 expander 内嵌 caption，故该断言有效 |
| 4 | `tests/test_rate_limit_budget.py` | `stats()["is_open"]` 只断言了 False，本批新加的 **成本分支**无正向断言 | ✅ 新增 `test_stats_is_open_on_cost`（成本触顶）/ `test_stats_is_open_on_calls`（次数触顶） |
| 5 | `src/campus_map.py` | 用了 `st.components.v1.html(...)` 穿透写法 | ✅ 改为显式 `import streamlit.components.v1 as components` + `components.html(...)` |
| 6 | `.env.example` 等 | 多个文件缺末尾换行（无害） | ⏸ 未动（纯风格，无收益） |

> **⚠️ 第 5 条的原始判断已更正（重要）**：我此前写「当前 1.58.0、替代品 `st.iframe`」——**两处都错**。实测本机是 **streamlit 1.51.0**，且：
> - `st.iframe`（顶层）在该版本**不存在**（`hasattr(st,'iframe') is False`）；只有 `streamlit.components.v1.iframe`。
> - `st.components.v1.html` 在 1.51.0 **不产生任何运行时告警**——"deprecated" 只写在 docstring 里；
>   `streamlit/__init__.py:306` 还专门 `import streamlit.components.v1` 以便调用它。
> - 那条 deprecated 指的是**调用路径**（"直接 `st.components.v1.html` 而非 import 其模块"），
>   **不是**"`html` 函数要被 `iframe` 取代"。
> - 结论：本次只做**零风险**的写法对齐（显式 import 模块），未改任何 HTML/JS 逻辑，地图行为不变。


### 1.2 需要"补一句解释"的地方（给排障者 / 面试官看的）

| # | 主题 | 需要补的说明 |
|---|---|---|
| 7 | `app.py` `_DEBUG_ENABLED` | 只在**进程启动时**读一次 → 改了 `FAQ_DEBUG` 必须重启前端。README 已暗示但没把"不热生效"写明 |
| 8 | `docker-compose.yml` 和风域名改 env 后 | 部署时必须确保 `.env` 真填了 `HEFENG_BASE_URL` / `HEFENG_GEO_URL`，否则回退官方 devapi。建议在 README 部署节加一行"检查清单" |
| 9 | `_meta.type` 三档边界 | `real_notice_v3`（通知原文）/ `official_doc`（官方文档·网页）/ `guidance`（无原文·引导型）三者的**判定边界**目前只散落在注释里，建议在 `docs/` 统一一句话定义 |
| 10 | 顶层 `source` 死字段 | 已知"代码不读、仅文本声明"。**是否要保留**需拍板：留着=审计时可见但可能误导；删掉=更干净但丢作者意图。当前 v1.6.0 只修了 2 条，其余 22 条未动 |
| 11 | README 测试数 | ✅ 已实测核对：**151 passed + 6 skipped = 157**，与 README「157 个单元+集成测试」一致（6 skip = `tests/test_ui.py` 的 `@requires_backend`，需 :8000 后端） |

### 1.3 已核对、确认**没问题**的（免疑）

- `X-Trace-Id` 已在 `api.py:123/170`、`nginx.conf:78`、`tests/test_api.py` 全部对齐 ✓
- `injection.py` 删去重守卫后，`_PATTERNS` 6 条规则名唯一，不产生重复条目 ✓
- `weather.py` 南京仍在（第 44 行江苏组），删的是重复键 ✓
- `app.py` 的 `_error` 字段确有生产（`:210`/`:232`）与消费（`:361`）✓

---

## 二、需要人工进一步搜集并审核的内容

### 2.1 语料里的事实（**必须拿官方原文核对**）

| # | 内容 | 去哪核 | 优先级 |
|---|---|---|---|
| A1 | 上面这 12 个 P0 意图的 `_meta` **已在 v1.8.0 补齐，但仍全是 `manual_verified`（无 url 可引）**；需继续找官方原文，升级为 `official_doc` / `real_notice_v3`：`course_selection` `medical` `campus_wifi` `card_recharge` `dorm_curfew` `grade_query` `leave_apply` `library_borrow` `library_seat` `lost_card` `scholarship` `transcript` | 各部门站群 + 办事大厅 | 🔴 高 |
| A2 | `psych_counseling` 的 5 个房间名 + 地点「大学生创新发展中心一楼西侧」 | 心理健康教育教研室页面 / 实地 | 🔴 高 |
| A3 | 公众号「**心海导航**」是否仍为官方号、菜单是否仍是「心理咨询 → 预约咨询」 | 微信实搜 | 🔴 高 |
| A4 | `dorm_repair` 引用《学生公寓管理规定》的**具体条款**（赔偿/疏通费/责任分担） | 学工处原文 | 🟡 中 |
| A5 | 心理中心伦理守则**版本号**（是否含"第二版"） | 中国心理学会 | 🟡 中 |
| A6 | 顶层 `source` 6 条待核部门名：`dorm_curfew`(学生宿舍管理中心) `scholarship`(学生资助管理中心) `canteen_info`/`express_pickup`(后勤管理处) `career_center`(就业指导中心) `lost_found`(分团委/学生事务大厅) | 机构设置页 | 🟡 中 |
| ~~A8~~ ✅ | ~~`library_borrow` 借阅册数与借期口径冲突~~ **2026-09-15 已电话核实定案**：图书馆流通部确认「本科生 10 册/30 天、研究生 15 册/60 天，每本可续借 1 次 30 天，超期罚金 0.1 元/册/天，欠费超 5 元暂停借书、缴清恢复」——**语料原本就是对的，官网《借书规则》与《常见问题》是旧口径**。答案未改，只在 `_meta.note` 记录核实渠道并警示勿据官网纠正 | — | ✅ 已解决 |
| A7 | 2 条可**立刻改**的：`campus_wifi` 信息网络中心 → **数智化处**；`leave_apply` 学生工作处 → **学工处** | 已在 2026-09-11 核实 | 🟢 低 |

### 2.2 电话（动态信息，需人工试打）

| # | 内容 | 备注 |
|---|---|---|
| B1 | 85864025（公寓管理科）/ 85864040（心理教研室）**当前学年是否仍有人接听** | 页面上有 ≠ 电话通 |
| B2 | 85864098 / 85864122 / 85864358 等报修电话是否仍有效 | 数智化处页面 |
| ~~B4~~ ✅ | ~~025-85864109 是否有人接听~~ **2026-09-15 已打通**，A8 的两个问题（册数/借期、超期罚金）一次问清，结论见 A8 | 已完成 |
| B3 | 12356 政策复核 | 每 6 个月 curl `gov.cn/.../content_6994462.htm` |

### 2.3 部署 / 上线（沙箱无法验证）

| # | 内容 | 备注 |
|---|---|---|
| C1 | **Hugging Face Spaces 在线 Demo** | `docs/deploy_hf_spaces.md` 写好了但**从未实操**；working memory 里的"待补" |
| C2 | Docker + Nginx 真实上线 | 需实测 `FAQ_CORS_ORIGINS` / `FAQ_TRUST_PROXY_HEADERS` 的实际取值是否正确（走 nginx 必须设 `1`，否则全校共用一个 IP 桶） |
| C3 | 和风专属域名 | 部署 `.env` 是否真填 `HEFENG_BASE_URL` / `HEFENG_GEO_URL` |
| C4 | `docker-compose.yml` 的 build 能否跑通 | 本次改成 `${VAR:-}` 语法后需实测 |

### 2.4 评估 / 性能（需人工跑数据）

| # | 内容 | 备注 |
|---|---|---|
| D1 | README 宣称「召回率@1 从 57% → 100%」 | 需确认**测试集规模 + 是否封闭**，否则简历数字站不住 |
| ~~D2~~ ✅ | ~~rerank 实测对比~~ **2026-09-15 完成**：结论是**净负** —— 召回@1 99.5%→93.1%、排序层延迟 ×13.2；204 条里可救集仅 1 条，精排却改动了 33 条排序、弄坏 14 条。成因：**句式压过话题**。阈值已标定为 0.20（最优区间 0.20~0.35）。详见 `docs/rerank_report.md` |
| D3 | 测试总数（见 1.2-11） | 跑一次 `pytest -q` 对数 |

### 2.5 出处 / 合规 / 地图

| # | 内容 | 备注 |
|---|---|---|
| E1 | 语料引用的官方页面链接**是否会长效** | xsc / xxh 页面结构可能变 |
| E2 | 校园地图**校区中心坐标仍是估算值**（"待校准"） | POI 真实坐标已入库但**未渲染** |
| E3 | POI 数据（天堂 18 / 仙林 48）是否要恢复渲染 | 取决于产品决策 |

---

## 三、建议的推进顺序

1. **先收尾本轮 10 文件**：补 1.1 的 #1–#4（都是几行的事），然后 commit（建议拆 2 个：`fix(security)` 注入+熔断+脱敏 / `chore(deploy)` 调试开关+依赖+compose）。
2. **补 1.2 的 #7 #8**（文档一行注释级），避免部署踩坑。
3. **再攻 A1/A2/A3**（语料 P0 与心理中心事实）——这是"被追问会露怯"的部分。
4. **C1（HF Spaces）**——最可能是简历/面试要展示的在线 Demo，优先级其实不低。
5. D1/D2 放最后。

---

## 附：如何复用本清单

- 每次改 `data/qa_corpus.json` → 回来看 **A 表**划掉对应项。
- 每次改部署相关文件 → 回来看 **C 表**。
- 本文件**不自动生成**，是人工维护的 checklist。
