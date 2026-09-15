# 前端技术方案评估与迁移计划

> **文档状态**：方案稿（2026-09-14）。**本文不改动任何代码**，所有结论均来自对现有代码的逐行核对。
> **已确认的前提**（2026-09-14 与作者确认）：
> ① 首要痛点是**多人并发撑不住**；② 技术栈选 **Vue 3 + Vite**（有基础 HTML/JS，未做过前端工程化）；
> ③ 部署以**自建 Docker + Nginx 为主，同时保留 HF Spaces Demo**；④ **先出方案，代码暂不动**。

---

## 0. 决策摘要（一页看懂）

| 项目 | 结论 |
|---|---|
| 现状 | Streamlit 单进程：`app.py` 494 行 + `src/ui_style.py` 358 行 + `src/campus_map.py` 321 行 |
| 核心痛点 | Streamlit 单进程 + **每次交互重跑整个脚本**，多人同时用前端会先于后端成为瓶颈 |
| 选型 | **Vue 3 + Vite**，构建为**静态产物**，由 Nginx 托管；FastAPI 退回纯 API |
| 后端改动 | **只增不改**：新增 `POST /feedback`；`/health` `/suggest` `/ask` 契约保持原样 |
| 迁移节奏 | 5 个阶段（P0 契约 → P1 骨架 → P2 补齐 → P3 容器化 → P4 切流下线），P4 前新旧并存 |
| HF Spaces | Space SDK 由 `streamlit` 改为 **`docker`**；FastAPI 同时 serve 静态产物与 API（仍是单进程） |
| 回滚 | Nginx 改一条 `location` 即可切回 Streamlit :8501；Streamlit 代码 P4 前一行不动 |

**一句话理由**：痛点在"前端是个 Python 进程"，而不在"UI 好不好看"。把前端变成**浏览器里的静态资源**，
并发瓶颈就交还给后端（后端本来就能用 gunicorn 多 worker 横向扩），而 Vue 3 + Vite 是"会基础 HTML/JS"
这个前提下，能真正拿到工程化能力（组件、构建、单测、HMR）且学习曲线最平缓的路径。

---

## 1. 现状盘点

### 1.1 技术栈与代码分布

| 文件 | 行数 | 职责 |
|---|---|---|
| `app.py` | 494 | Streamlit 入口：健康检查、对话渲染、提问、候选、反馈、建议 chip、自动滚动 JS |
| `src/ui_style.py` | 358 | 注入全局 CSS（IM 式左右分栏气泡、滚动容器 `st-key-qa_history`、chip 按钮） |
| `src/campus_map.py` | 321 | 校园地图：Python 拼自包含 HTML（base64 底图 + 原生 JS 缩放拖拽）+ POI 数据 |
| `api.py` | 250 | FastAPI 生产入口：`/health` `/suggest` `/ask` |
| `nginx/nginx.conf` | 94 | 反代配置（**当前未接入 compose**，注释里已预留 `location /static/`） |
| `docker-compose.yml` | 84 | **只有 `api` 一个服务**，无前端、无 nginx 服务 |
| `Dockerfile` | 155 | 多阶段构建，**只跑 API**；构建时用 `grep -vE 'streamlit'` 把 streamlit 过滤掉 |

### 1.2 运行时架构（现状）

```
本地调试（当前唯一跑通的形态）
  浏览器 ──WebSocket──> Streamlit :8501 ──HTTP──> FastAPI :8000 ──> FaqBot
                          (Python 进程)              (gunicorn 2 worker)

Docker 部署（docker-compose.yml 现状）
  浏览器 ──> Streamlit（宿主机手启，不在 compose 里）──HTTP──> faq-bot-api 容器 :8000

HF Spaces（docs/deploy_hf_spaces.md）
  浏览器 ──> Streamlit Space（SDK=streamlit，进程内直调 FaqBot，无 HTTP 一跳）
```

注意三形态里**没有一个形态是"前端被容器托管"的**：Docker 部署时前端是宿主机手启的 Streamlit。
这也意味着"自建 Nginx"目前**还没有落地**，是本次要一并补的缺口。

### 1.3 前端今天承担的隐性职责（迁移的真实成本，最容易被低估）

换 UI 框架的成本不在"画界面"，而在这些**藏在 Python 里的业务逻辑**。列全了才能估准工作量：

| # | 职责 | 现在在哪 | 迁移去向 | 备注 |
|---|---|---|---|---|
| 1 | 来源文案映射 `source_of()` | `app.py:48` | 前端纯函数 `web/src/lib/source.ts` | 7 个分支（kb/api/llm/chat/none/error），**文案属对外承诺，逐字照搬** |
| 2 | 输入 200 字截断 | `app.py:244` | 前端 `ask()` 入口 | **必须保留**：后端 `AskRequest(max_length=200)`，超了返回 422，用户会看到"服务不可用" |
| 3 | 限流身份 `user_id` | `app.py:483`（`st.session_state` + uuid4） | 浏览器 `localStorage` | 见风险 R4 |
| 4 | 候选问题（未命中时"你可能还想问"） | `app.py:391` | 前端组件 | 取 `candidates[:3]` |
| 5 | 反馈埋点 | `app.py:435/440` → `logger.log_feedback()` | **必须改成 HTTP 接口**（见 §5.2） | ⚠️ 现在是断的，见下 |
| 6 | 健康检查闸门 | `app.py:335`（`health.ready` 为假则 `st.stop()`） | 前端 `/health` 轮询 + 错误条 | |
| 7 | 调试面板（trace_id/耗时/相似度/阈值） | `app.py:403`，`FAQ_DEBUG=1` | 前端 `import.meta.env.DEV` 或构建期注入标志 | **线上绝对不能出现**，见 §5.4 |
| 8 | 反馈统计（好评率） | `app.py:459`，`FAQ_DEBUG=1` | 同上（或删除） | |
| 9 | 高频问题 chip | `app.py:290`，`/suggest` 缓存 60s | 前端组件 + `sessionStorage` 缓存 | |
| 10 | 对话区自动滚动 / 防跳顶 | `app.py:105-177`（78 行 JS） | **直接删掉** | Vue 里是 3 行 `nextTick + scrollTo`，这 78 行是纯 Streamlit 的产物 |
| 11 | 校园地图交互 | `src/campus_map.py:190-295`（105 行 JS） | 搬进 `CampusMap.vue`，逻辑几乎不改 | 见 §7 |
| 12 | 深浅主题适配 | 靠 `st.caption` 自动适配 | CSS 变量（`prefers-color-scheme`） | 现在"免费"拿到的，迁移后要自己写 |
| 13 | 无后端进程内模式 `_USE_LOCAL_BOT` | `app.py:195` | 由 FastAPI serve 静态页替代 | 见 §4.3 |

### 1.4 局限逐条（带证据）

| ID | 局限 | 证据 | 实际影响 |
|---|---|---|---|
| **L1** | **单进程 + 每次交互重跑整个脚本** | `app.py` 是单文件脚本，`main()` 从 `set_page_config` 到 `chat_input` 全量重放；`for i, (q, r) in enumerate(history)` 每次把所有历史容器重建 | 20 条历史 = 每次点击重建 40+ 容器。**这是本次要解决的核心问题** |
| **L2** | 会话状态在服务端进程内存 | `st.session_state` | 重启即丢（README 已记）；**无法多副本水平扩展**——两个 Streamlit 实例会话不共享 |
| **L3** | CSS 依赖 Streamlit 私有 DOM | `ui_style.py` 大量 `.st-key-*` / `[data-testid=...]` 选择器 | Streamlit 小版本升级可能静默错位。已踩过 3 个坑（滚动条伪元素只作用于最后一个选择器、按钮获焦导致容器跳顶、`st.container(horizontal=True)` 需要 ≥1.42） |
| **L4** | **反馈链路在 HTTP 模式下是断的** | `app.py:435` 调 `logger.log_feedback()` → 直接写**前端进程所在文件系统**的 `config.FEEDBACK_PATH`；而 `docker-compose.yml` 只把 `./logs` 挂给了 **api 容器** | 生产部署下，前端写的 `logs/feedback.jsonl` 与后端挂载的**不是同一个文件**，好评率永远统计不到。静态前端跑在浏览器里更没有文件系统 → **必须新增 HTTP 接口** |
| **L5** | 浏览器直连 API 会跨域全被拦 | `src/config.py:467` 注释已预言："一旦改成 HTML/JS 前端直连就会全部跨域被拦"；`CORS_ORIGINS` 默认只放行 `localhost:8501` | 新方案若走同源 Nginx 反代则**不需要 CORS**（更安全）；但本地 Vite dev server 需要 proxy |
| **L6** | 首屏要等 Python 运行时 + 脚本执行 | Streamlit 启动 + `main()` 首跑 | 冷启动明显；HF Spaces 上更慢（还要加载 BGE 模型） |
| **L7** | 前端逻辑无法单测 | `tests/test_ui.py` 18 个用例走 AppTest（跑脚本，不跑浏览器）；后端没起时 skip（`skip ≠ 通过`） | 那 78 行滚动 JS、地图 fit 逻辑**实际上没有任何自动化覆盖**，全靠人肉点 |
| **L8** | 移动端体验受限 | Streamlit 布局系统（columns/tabs）非响应式优先 | 手机端可优化空间有限；也无法做 PWA / 离线缓存 |

**不在本次范围内**（明确划界，避免范围蔓延）：后端检索/安全层/语料/评测链路一律不动；
不加用户账号体系；不做 SSR/SEO（这是内部问答页，无搜索流量诉求）；不做小程序/App 壳。

---

## 2. 替换动机与可量化目标

**动机**（按优先级，来自确认结果）：

1. **并发**（P0）：前端不再是瓶颈，并发上限只由后端决定。
2. **首屏与移动端**（P1）：静态资源 + 浏览器缓存，首屏从"等 Python"变成"等 CDN/磁盘"。
3. **可测试/可维护**（P1）：纯函数能单测，UI 能 E2E，不再依赖 Streamlit 私有 DOM。
4. **简历工程含金量**（P2）：前后端分离、构建流水线、组件化——面试里能讲的东西更多。

**验收指标**（迁移完成时对照，用现有脚本测）：

| 指标 | 现状 | 目标 | 怎么测 |
|---|---|---|---|
| 前端并发承载 | Streamlit 单进程，N 人串行重放脚本 | 静态资源，**前端 CPU/内存占用与并发数无关** | `scripts/benchmark_throughput.py` 前后对比；`docker stats` 看前端容器是否恒为 0 |
| 首屏可交互 | 需等 Streamlit 运行时握手 + `main()` 首跑 | 静态资源 < 1s（本地/局域网） | 浏览器 DevTools Performance；Playwright 记录 `load`→`visible` |
| 前端逻辑单测覆盖 | 0（78 行滚动 JS + 105 行地图 JS 无覆盖） | 纯函数（来源映射/截断/状态机）100%，vitest | `web/` 下 `npm test` |
| 回归可发现性 | 靠 AppTest（后端没起则 skip） | Playwright E2E 覆盖 6 条主路径 | `web/e2e/`，见 §9 |
| 后端契约变化 | — | **0 破坏性变更**（3 个端点字段不变，只加 `/feedback`） | `tests/test_api.py` 27 个用例不改一行 |

---

## 3. 候选方案对比与选型

| 维度 | A. 继续用 Streamlit（只优化） | B. 原生 HTML+JS 单页（零构建） | **C. Vue 3 + Vite（★推荐）** | D. React + Vite | E. FastAPI + Jinja2 模板 | F. Gradio |
|---|---|---|---|---|---|---|
| 解决 L1 并发 | ❌ 单进程模型不变 | ✅ | ✅ | ✅ | ❌ 仍在 Python 进程里渲染 | ❌ 同 Streamlit |
| 上手成本 | 0 | 低（但要手写 DOM） | **中**（模板语法≈HTML，SFC 一个文件一个组件） | 高（JSX + Hooks 心智） | 低 | 低 |
| 工程化 / 组件化 | ❌ | ❌ 手写 | ✅ | ✅ | 弱（模板宏） | ❌ |
| 单测 / E2E 友好 | 差（AppTest） | 一般 | ✅ vitest + Playwright 生态成熟 | ✅ | 一般 | 差 |
| 与现有后端兼容 | 无需改动 | 只需加 `/feedback` | 只需加 `/feedback` | 同 C | 同 C | 需包一层 |
| 长期维护 | 绑死 Streamlit 私有 DOM | 无依赖但代码会散 | 依赖 Node 工具链（风险 R6） | 同 C，学习成本更高 | 无 Node | 绑死 Gradio |
| 简历含金量 | 低 | 低 | **中高** | 高 | 低 | 低 |
| HF Spaces 适配 | 现状即可 | 需 Docker SDK | 需 Docker SDK（构建一次即可） | 同 C | **最省事**（纯 Python） | 原生 |

**选型：C（Vue 3 + Vite）**，四条理由：

1. **直击痛点**：构建产物是纯静态文件，浏览器自持会话 → L1/L2 一次性消失，这正是"并发撑不住"的根因。
2. **学习曲线匹配**：`.vue` 单文件组件的模板部分就是 HTML + `{{ }}`，对你（会基础 HTML/JS）来说比 JSX 友好；
   Vite 的 `npm create vue@latest` 一条命令出脚手架，不用先学 webpack/配置。
3. **能学到真东西**：组件拆分、构建产物 hash 缓存、`Proxy` 响应式、Pinia 状态——面试能讲的点比"我写了个 HTML"多得多。
4. **生态与中文资料**：Vue 3 + Vite 的中文文档与社区案例充足，踩坑能搜到答案。

**为什么否掉其它**：
- **A**：治不了根因，L1 是 Streamlit 的执行模型决定的，不是参数能调的。
- **B**：能解决并发，但 1170 行 UI 逻辑会退化成手写 DOM 操作，等于把刚从 Streamlit 私有 DOM 里爬出来又跳进自己造的 DOM 坑，**且零工程化 = 简历上不好看**。
- **D**：能力最强，但你没做过前端工程化，同时学 JSX + Hooks + TS 三件事的翻车概率高；本项目 UI 只有 2 个 tab，用不上 React 的生态优势。
- **E**：纯 Python 很香（无 Node、HF 最省事），但模板渲染仍在 Python 进程里，**并发问题和 Streamlit 同源**，不符合首要动机。可作为**降级预案**（见风险 R6）。
- **F**：换汤不换药，且 `gr.Chatbot` 的定制自由度比 Streamlit 还低。

---

## 4. 目标架构

### 4.1 目录结构（新增 `web/`，与 Python 侧完全解耦）

```
faq-bot/
├── api.py                  # 不变 + 新增 /feedback
├── src/                    # 不变（除 campus_map.py 处置见 §7）
├── web/                    # ★ 新增
│   ├── index.html
│   ├── vite.config.ts      # dev proxy: /api -> http://127.0.0.1:8000
│   ├── package.json
│   ├── public/campus_maps/ # 手绘地图（原 assets/campus_maps 拷贝）
│   ├── src/
│   │   ├── main.ts  App.vue
│   │   ├── api/client.ts       # /health /suggest /ask /feedback 封装
│   │   ├── types.ts            # AskResponse 等 TS 类型（对齐 Pydantic）
│   │   ├── lib/source.ts       # 从 app.py source_of() 逐字迁移
│   │   ├── stores/chat.ts      # Pinia：history / user_id / pending
│   │   └── components/
│   │       ├── ChatView.vue  Bubble.vue  SuggestChips.vue
│   │       ├── FeedbackBar.vue  CandidateList.vue
│   │       └── CampusMap.vue    # 105 行 JS 整体搬入
│   └── e2e/                 # Playwright
└── nginx/nginx.conf         # 改为：静态托管 + /api 反代
```

### 4.2 生产部署（自建 Docker + Nginx，主目标）

```
浏览器 ──HTTPS──> Nginx
                   ├── /            → 静态文件（web/dist，含 hash 缓存）
                   ├── /api/*       → 反代 FastAPI（剥掉 /api 前缀）
                   └── /health      → 反代（现有 location = /health 保留）
                              └──> faq-bot-api（gunicorn 2 worker）
```

**关键决策：API 路径前缀在 Nginx 层做，不动 FastAPI。**
即 `location /api/ { proxy_pass http://faq_api/; }`（末尾带 `/` 会自动剥掉 `/api/`）。
理由：现有 `tests/test_api.py` 的 27 个用例、`.env.example`、README 示例、以及任何外部调用方
都在打 `/ask` `/health` `/suggest`。**在 FastAPI 里加 `prefix="/api"` 会一次性破坏这些契约**，
属于"为了前端顺手改后端"的典型越界。Nginx 层剥离对后端完全透明。

> ⚠️ 前置缺口：`docker-compose.yml` 现在**只有 api 服务，没有 nginx 服务**，
> `nginx/nginx.conf` 也没被任何 compose 引用。P3 需要新增 `nginx` 服务 + 证书挂载，
> 并把 api 的 `ports: 8000:8000` 改成 `expose: ["8000"]`（文件注释里已写明这一步）。

### 4.3 HF Spaces（保留 Demo）

现状是 `sdk: streamlit`（Space 自动 `streamlit run app.py`，进程内直调 `FaqBot`）。
去掉 Streamlit 后必须换形态，两个选项：

| 方案 | 做法 | 优劣 |
|---|---|---|
| **★ Docker SDK 单 Space** | `README.md` 头部 `sdk: docker` + `app_port: 7860`；Dockerfile 多阶段（node 构建 dist → python runtime）；`api.py` 加 `StaticFiles(directory="dist", html=True)` + SPA fallback | 仍是**一个 Space、一个进程**，保留"进程内直调 FaqBot"的无后端优势；构建期多花 1~2 分钟 |
| Static Space + API Space | 静态 Space 放 dist，API 单独起 Space | 两个 Space；跨域要开 `FAQ_CORS_ORIGINS` 白名单，**扩大了 API 暴露面**（任何人可直调烧 LLM 预算） |

推荐前者。注意 HF Docker Space 要求监听 **7860**（不是 8000），且 `StaticFiles` 的 SPA fallback
必须只对**非 `/ask` `/health` `/suggest` `/feedback`** 的路径生效，否则 `/health` 会被 fallback 成 `index.html`
——**这会让健康检查永远返回 200 但内容不对**，进而让前端"服务不可用"判断失效（对应 L4 类问题）。

---

## 5. 接口与数据适配点

### 5.1 现有契约（**保持不变**）

| 端点 | 方法 | 请求 | 响应关键字段 |
|---|---|---|---|
| `/health` | GET | — | `status` `ready` `intents` `questions` `vectorizer` `cache` |
| `/suggest` | GET | — | `questions: string[]` |
| `/ask` | POST | `{query(1-200), user_id?, top_k?}` | `answer` `matched` `tag` `score` `fallback` `candidates` `latency_ms` `trace_id` `vectorizer` `security` `cache_hit` |

前端 `types.ts` 按这张表建 TS 类型，**逐字段对齐**（尤其 `fallback: {type, source, rule} | null`）。

### 5.2 必须新增：`POST /feedback`（否则反馈功能直接消失）

```python
class FeedbackRequest(BaseModel):
    vote: str                      # "up" | "down"
    query: str = Field(max_length=200)
    matched: bool = False
    tag: str | None = None
    trace_id: str = Field("", max_length=64)
    comment: str = Field("", max_length=500)
```

后端实现 = 把 `logger.log_feedback(result, vote, comment)` 包一层：
**复用现有字段结构**（`timestamp/query/matched/tag/...`），保证 `summarize_feedback()` 与
`tests/test_ui.py:338` 的统计逻辑**不用改**。

安全约束（照抄 W2 的既有做法，别在这里开新口子）：
- 该端点同样经过**限流**；
- 入参走 `logger.redact()`（`write_jsonl` 内部已强制 redact，但 `query` 是用户原文，落盘前再脱敏一次更稳）；
- **`vote` 必须白名单校验**（只允许 `up`/`down`），否则能往 jsonl 里写任意字符串；
- `FEEDBACK_ENABLED=False` 时返回 204，前端照常显示"已反馈"（不因埋点失败打断交互）。

### 5.3 前端侧适配清单

| 适配点 | 做法 | 不做会怎样 |
|---|---|---|
| 200 字截断 | `ask()` 内 `q.trim().slice(0, 200)` | 后端 422，用户看到"服务暂时不可用"（输入错误被误报成宕机——`app.py:240` 注释里踩过） |
| `user_id` | `localStorage` 存 uuid，随 `/ask` 上报 | 全部用户共用一个限流桶（`app.py:480` 修复过的老问题会复现） |
| 来源文案 | `source_of()` 逐字迁移为纯函数 | 7 个分支任一写错 = 对外承诺错了（如把"服务不可用"说成"知识库未收录"） |
| 错误处理 | 区分 网络失败 / 422 / 429 / 5xx → 统一"服务暂时不可用，稍后再试" | 重演"把 422 报成宕机" |
| 兜底话术 | **保持"只说我答不上，不说我为什么答不上"**（`tests/test_fallback.py` 有禁用词断言） | 泄露 API key / 预算 / 网络细节 |
| 建议缓存 | `/suggest` 结果 `sessionStorage` 缓存 60s（对齐 `app.py:222` 的 `ttl=60`） | 每次刷新打一次后端 |
| 健康检查 | 进入时 `/health`，`ready=false` 显示错误条且不渲染输入框 | 用户能输入但提交必失败 |

### 5.4 调试信息（安全红线）

`app.py:79` 的 `FAQ_DEBUG` 现在是**服务端环境变量**，前端拿不到也无所谓——这是对的。
迁移到浏览器后**绝不能**把 `trace_id` / 相似度 / 阈值 / 候选分数编进静态产物：
静态文件任何人都能下载。做法：调试面板只在 `import.meta.env.DEV`（Vite dev server）下编译进包，
生产构建时整段被 tree-shake 掉。这条要写进 Code Review 清单。

---

## 6. 分阶段迁移路径

| 阶段 | 交付物 | 验收标准 | 回滚点 |
|---|---|---|---|
| **P0 契约冻结** | `POST /feedback` + 测试；`docs/api_contract.md`（3+1 端点字段表）；`web/types.ts` 初稿 | `tests/` 全绿（新增 feedback 用例）；`ruff` clean | 纯新增，删掉即可 |
| **P1 骨架联调** | `npm create vue` 脚手架 + `ChatView` + `api/client.ts` + Vite dev proxy；跑通"提问→回答→来源" | 本地 :5173 能完整问答；Streamlit :8501 **同时保持可用** | 关掉 dev server，世界无变化 |
| **P2 功能补齐** | 候选、反馈、建议 chip、清空、健康闸门、移动端、`CampusMap.vue` | 与 Streamlit 版**逐条功能对齐**（按 §1.3 的 13 项清单打勾）；vitest 覆盖纯函数；Playwright 跑通 6 条 E2E | 同上 |
| **P3 容器化** | `web/Dockerfile` 多阶段（node build → dist）；compose 加 `nginx` 服务；Nginx 静态托管 + `/api` 剥离；证书挂载 | `docker compose up` 起 3 个服务；浏览器访问域名拿到静态页且能问答；**Streamlit 仍在 8501 可用** | Nginx 改一条 `location /` 回 `proxy_pass http://streamlit:8501` |
| **P4 切流下线** | 观察 1 周后删除 `app.py` / `ui_style.py` / `campus_map.py` 及 `test_ui.py`；`requirements.txt` 移除 streamlit；README 更新 | 无用户反馈异常；后端指标（命中率/延迟）无回归 | `git revert`；Streamlit 代码在 git 历史里永久可查 |

**P4 前新旧并存**是硬要求：任何阶段出问题，流量都能在 1 分钟内切回 Streamlit。

**HF Spaces 排在 P3 之后**（依赖 dist 构建产物稳定），且它是独立 Space，出问题不影响自建部署。

---

## 7. 需改动的核心模块与目录

| 现状 | 处置 | 说明 |
|---|---|---|
| `app.py` | **P4 删除**（git 保留历史） | 494 行，全部由 `web/` 取代 |
| `src/ui_style.py` | **P4 删除** | 358 行 CSS 全部针对 Streamlit 私有 DOM；新样式写在 `web/src/styles/`（约 150 行即可，因为没有 Streamlit 的默认样式要覆盖） |
| `src/campus_map.py` | **拆分迁移** | ① `CAMPUSES`（66 条 POI）→ `data/campus_pois.json`（数据留在 Python 侧，便于以后 POI 渲染和脚本校验）；② 105 行 JS → `CampusMap.vue`，`document.getElementById` 换成 Vue `ref`，**fit / zoomAt / 拖拽逻辑原样保留**；③ base64 内嵌改为 `public/campus_maps/*.jpg`（Vite 原样拷贝，浏览器可缓存，比 base64 省 37% 体积且能缓存） |
| `campus_map.py` 的 `_jpeg_size()` / `_rel_to_latlon()` | **删除** | 已核实**无任何调用者**（Folium 时代遗留的死代码）。迁移时顺手清掉 |
| `api.py` | **只增 `/feedback`** | 3 个现有端点字段一字不改 |
| `src/logger.py` | 不动 | `log_feedback` 由新端点调用 |
| `src/config.py` | 小改 | `CORS_ORIGINS` 默认加 `http://localhost:5173`（Vite dev）；注释里"一旦改成 HTML/JS 前端直连就会全部跨域被拦"这句预言可以更新了 |
| `tests/test_ui.py`（18 用例） | **P4 删除**，能力迁到 `web/e2e/` | AppTest 测的是 Streamlit 脚本；新前端用 Playwright 测真实浏览器 |
| `tests/test_campus_map.py`（1 用例） | **保留**，改测 `data/campus_pois.json` | 数据层校验仍然有价值 |
| `requirements.txt` | P4 移除 `streamlit` | 镜像构建里的 `grep -v streamlit` 过滤逻辑同时删除 |
| `Dockerfile` | P3 改造 | 新增 node 构建阶段；`COPY app.py` 那行在 P4 后删除 |
| `docker-compose.yml` | P3 加 `nginx` 服务 | 见 §4.2 前置缺口 |
| `nginx/nginx.conf` | P3 改造 | 启用已注释的静态目录；新增 `/api/` 剥离 |
| `docs/deploy_hf_spaces.md` | P3 后重写 | SDK streamlit → docker，端口 7860 |

---

## 8. 风险与回滚预案

| ID | 风险 | 触发信号 | 预案 |
|---|---|---|---|
| **R1** | 迁移期两套 UI 行为不一致（来源文案、截断、限流身份） | 同一问题两版答案/来源标注不同 | P1 阶段就按 §1.3 的 13 项逐条对齐打勾；`source_of` 用**同一份真值表**写 vitest |
| **R2** | 反馈数据断裂（历史 `feedback.jsonl` 在前端机器上） | 迁移后好评率归零/翻倍 | P0 先上线 `/feedback` 并让**现有 Streamlit 也改走它**（一行替换），保证数据源唯一；历史文件手工合并并标注来源 |
| **R3** | HF Docker Space 构建慢/失败（node + torch + BGE 三层） | Space 构建超时 | 把 `dist/` 直接**提交进 Space 仓库**（跳过 node 构建阶段）；或降级为 E 方案（Jinja2 模板，纯 Python）只用于 HF |
| **R4** | `user_id` 移到客户端可被清除/伪造 | 限流形同虚设 | 接受该风险：限流是**软限流**，且服务端仍有 `client_ip` 桶（`TRUST_PROXY_HEADERS=1` 时取 nginx 给的 `$remote_addr`，不可伪造），双维度兜底。如需收紧，后续加 IP+UA 复合指纹 |
| **R5** | 静态前端把 API 暴露给公网 | 预算异常消耗 | 必须走**同源 Nginx 反代**（`/api`），**不开 CORS**；HF 场景单进程同源，天然无跨域。Nginx 5r/s + burst 20 的现有限流继续生效 |
| **R6** | Node 工具链引入维护负担（安全更新、版本升级） | 依赖告警 | `web/` 与 Python 侧解耦，最坏情况是"dist 不再重新构建"，已上线的静态产物不受影响；真扛不住可降级到方案 E（Jinja2），UI 逻辑已在 Vue 组件里结构化，搬迁成本可控 |
| **R7** | 校园地图回归（fit/缩放/切 tab） | 切到地图 tab 图不显示/缩成 1px | 这 105 行 JS 经历过 3 轮修复（见文件头注释），**整体搬运、不做重构**；E2E 加一条"切地图 tab → 图片可见且宽高 > 100px" |
| **R8** | 时间成本挤占主线（语料/开放集评测） | — | 按 §6 分阶段，P0~P2 可随时停下且不留技术债（Streamlit 一直活着）；**建议先做完 P0**（`POST /feedback`），它单独就有价值——修的是真实缺陷，不依赖后续是否迁移 |

**统一回滚动作**：`nginx.conf` 里把 `location /` 从静态托管改回 `proxy_pass http://streamlit:8501;`，
`nginx -s reload`。Streamlit 在 P4 前始终保留在 compose 里（哪怕平时不接流量）。

---

## 9. 验证与回归清单

**前端单测（vitest）** — 纯函数，不依赖浏览器：
- `sourceOf()` 7 个分支 × 边界（`fallback` 为 null / `type=="error"` / `fsrc=="llm"`）→ 与 `app.py` 现状逐条对照
- 200 字截断：`199/200/201` 三种长度
- `user_id` 生成与持久化（mock localStorage）
- `/ask` 失败四种分支 → 统一文案，且**不含禁用词**（对齐 `tests/test_fallback.py` 的 ANSWER_CASES）

**E2E（Playwright，6 条主路径）**：
1. 首屏：健康 → 输入框可见 → 建议 chip 渲染
2. 提问命中：气泡出现、来源显示"来自知识库"
3. 提问未命中：来源显示"知识库暂未收录" + 候选按钮可点
4. 反馈：点"有用" → toast → 按钮变"已反馈" → **后端 `feedback.jsonl` 多一行**（这条直接验证 R2）
5. 地图 tab：切过去图片可见、可缩放（对应 R7）
6. 移动端视口（375×812）：布局不破、输入框可用

> 验证必须用**有头浏览器**：本项目已踩过两次"headless 掩盖真实行为"（滚动条 gutter 恒为 0、按钮焦点跳顶）。

**后端回归**：`tests/` 现有 174 个用例**一个都不改**（P0 新增 feedback 用例）。
**性能对比**：迁移前后各跑一次 `scripts/benchmark_throughput.py`，
并用 `docker stats` 确认前端容器在高并发下 CPU/内存**不再随并发线性上涨**（这才是 L1 被解决的证据）。

---

## 10. 待确认（动手前需要你拍板）

1. **P0 要不要先做？** 新增 `POST /feedback` 是修真实缺陷（L4），独立于迁移本身。
   建议先做——做完就算后面不迁移也不亏。需你确认是否接受这个插队。
2. **域名与 TLS**：Nginx 接入需要证书（`nginx.conf` 里 `server_name` 还是 `_`）。
   是走 Let's Encrypt 自动签发，还是先用自签/HTTP 内网跑通？
3. **HF Space 形态**：确认接受 §4.3 的 Docker SDK（构建慢一点）还是更想要"两个 Space"？
4. **P4 是否真删 Streamlit**：删掉后本地调试就没有 UI 了（要起 Vite dev server）。
   也可以选择**永久保留**为"调试用 UI"，代价是 `requirements.txt` 继续带 streamlit、镜像构建继续过滤它。
5. **Node 版本**：Vite 需要 Node ≥ 20.19。本机托管有 22.12.0 / 22.22.2 可用（系统还有一个 20.20.2 的 Anaconda 版）。
   建议统一用 22.22.2，并在 `web/package.json` 里加 `"engines": {"node": ">=20.19"}` 钉住。
