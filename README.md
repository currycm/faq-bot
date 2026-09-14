# 智答校园 · 校园 FAQ 智能问答机器人（faq-bot）

> **一句话看懂**：一个能回答新生常见问题（选课、宿舍、转专业、奖助学金…）的校园智能助手。
> 基于 RAG 检索 + 大模型兜底，含防隐私泄露 / 防恶意提问的安全层，可 Docker 一键部署。

> 🔗 **在线体验**：`（部署后把链接放这里，例如 Hugging Face Spaces / Railway 地址）`
> 📄 **接口文档**：本地起服务后访问 `http://127.0.0.1:8000/docs`

> 📸 **效果截图**：
> | 问常见问题 | 问天气 | 被安全拦截 |
> |---|---|---|
> | ![问常见问题](docs/screenshots/screenshot-faq.png) | ![问天气](docs/screenshots/screenshot-weather.png) | ![被安全拦截](docs/screenshots/screenshot-safety.png) |

**当前版本**：v8 ｜ **语料**：v1.6.0（49 个意图 / 411 条问法）｜ **测试**：173 个用例全绿

---

## 📑 目录

- [一、项目简介](#一项目简介)
- [二、功能说明](#二功能说明)
- [三、快速开始](#三快速开始)（环境要求 / 安装 / 配置 / 运行）
- [四、使用示例](#四使用示例)
- [五、实测效果](#五实测效果)
- [六、项目结构](#六项目结构)
- [七、技术架构](#七技术架构)
- [八、配置项与环境变量](#八配置项与环境变量)
- [九、常见问题（FAQ）](#九常见问题faq)
- [十、已知限制](#十已知限制)
- [十一、开发与运维](#十一开发与运维)
- [十二、文档索引](#十二文档索引)
- [十三、版本历史](#十三版本历史)

---

## 一、项目简介

一个面向 NLP 初学者的**检索式 FAQ 问答机器人**。语料来自学校各部门的真实通知，检索用中文语义向量（BGE），
未命中时按问题性质分流到「闲聊 / 实时数据 / 校园事务 / 通识」四条兜底通道——**校园事务绝不交给大模型编造**。

### 🎯 关键成果（简历可直接用）

- **召回@1 99.2%**：把检索方案从 TF-IDF 升级为中文语义向量（BGE-small-zh）后，同一测试集上
  召回@1 从 **57% → 99.2%**、未识别率从 **37.6% → 0%**——证明"换语义向量"比"堆同义词"有效得多
- **4 道安全防线**：PII 脱敏 / Prompt 注入拦截 / 令牌桶限流 / 成本熔断，拦截"忽略指令"类越狱攻击
- **173 个单元 + 集成测试**接入 GitHub Actions，并把**召回率做成 CI 门禁**（低于基线直接红）
- **抗并发改造**：答案缓存 + 慢路径隔离，实测吞吐 **105 → 960 req/s**（并发 32），
  慢请求导致的延迟劣化从 **19× 降到 1.3×**
- **Docker 多阶段部署**（CPU torch + BGE 预下载 + secret 注入）+ Nginx 反代 + `gunicorn --preload` 共享模型内存

### 🛠️ 我做了什么（非技术版）

1. 从零搭建校园问答系统，覆盖 **49 类校务场景 / 411 条问法**，能回答新生 90% 以上的常见问题
2. 设计安全机制，自动屏蔽隐私信息和恶意诱导提问，并给大模型调用做了成本上限
3. 写自动化测试与 CI 流程（含效果指标门禁），保证改动不会悄悄把召回率做坏
4. 用数据驱动迭代：收集未命中问题 → 补语料 → 复测指标，并为每条答案建立**可核来源台账**
5. 做交互式校园地图：双校区手绘地图叠加 + 地点查询，新生一眼找到教学楼、食堂、宿舍

---

## 二、功能说明

| 功能 | 说明 | 对应代码 |
|---|---|---|
| **语义检索问答** | 用户问题 vs 411 条问法算余弦相似度，≥ 0.60 直接返回语料答案（不消耗任何 LLM 额度） | `src/retriever.py` |
| **意图路由兜底** | 未命中时按性质分流：闲聊→固定话术 / 实时→和风天气 API / 校园事务→固定话术（**绝不进 LLM**）/ 通识→DeepSeek | `src/fallback/router.py` |
| **W2 安全层** | 四道防线按序生效：PII 脱敏 · Prompt 注入拦截 · 令牌桶限流 · 滑动窗口成本熔断 | `src/security/` |
| **答案缓存** | 归一化 query → 结果（LRU + TTL），热问法命中即返回；**查找在安全层之后**，不绕过限流 | `src/cache.py` |
| **慢路径隔离** | 兜底链路（1.4~8s）与检索（~10ms）共用线程池，用信号量限并发，超限立刻降级固定话术 | `src/agent.py` |
| **校园地图** | 双校区手绘底图 + 自包含查看器（base64 内嵌 + 原生 JS 缩放拖拽，零外部依赖） | `src/campus_map.py` |
| **语料溯源审计** | 每条答案标注来源类型（通知原文 / 官方文档 / 引导型），并附无溯源清单与事实审计 | `docs/*.md` |
| **可观测性** | JSONL 问答日志 + 未命中采集（`logs/unmatched.jsonl`）+ `/health` 暴露缓存命中率 | `src/logger.py` |
| **前端去 AI 味** | 高频问题常驻 chip、来源一行灰字、调试信息默认隐藏（改环境变量才显示） | `app.py` / `src/ui_style.py` |

支持的提问示例（都能答）：`图书馆几点开门`、`宿舍灯坏了找谁修`、`怎么预约心理咨询`、
`校园卡丢了怎么办`、`今天天气怎么样`、`什么是机器学习`。

---

## 三、快速开始

### 3.1 环境要求

| 项 | 要求 |
|---|---|
| Python | **3.11+**（Docker 镜像用 `python:3.11-slim`；本机实测 3.13 亦可） |
| 内存 | ≥ 2GB（BGE-small 模型约 400MB/进程） |
| 可选 | Docker + Docker Compose（生产部署）；Redis（多 worker 精确限流） |
| 网络 | 首次运行需联网下载 BGE 模型（约 93MB）；国内建议配 `HF_HOME` 镜像 |

### 3.2 安装

```bash
git clone https://github.com/currycm/faq-bot.git
cd faq-bot

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt

# torch 不写在 requirements.txt 里（Docker 单独装 CPU 版避免拉 CUDA 版）：
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

> 依赖版本策略（为什么用 `>=` 而不是 `==`）见 `requirements.txt` 顶部注释。

### 3.3 配置

**最小可用配置**：只配 DeepSeek key 就够了；不配也能跑（检索问答完全离线可用，只是通识问题会降级为固定话术）。

```bash
# 方式一（推荐）：环境变量
export DEEPSEEK_API_KEY=sk-xxx        # Windows PowerShell: $env:DEEPSEEK_API_KEY="sk-xxx"
export HEFENG_API_KEY=xxx             # 天气功能可选

# 方式二：写进 .env（已在 .gitignore 里，不会进仓库）
cp .env.example .env && vim .env
```

> ⚠️ **`.env` 是进程启动时读的**：改完必须**重启进程**，否则内存里还是旧值。
> 这一条坑过很多人（表现为"配置明明改了却怎么问都联系不上服务"）。

密钥优先级：`直接环境变量` > `secrets/<name>_key.txt`（Docker secret）> 空。
所有密钥统一走 `src/config.py` 的 `_load_secret()`，**不允许在业务模块里直接读环境变量**。

### 3.4 运行

后端 API（FastAPI）：

```bash
uvicorn api:app --host 127.0.0.1 --port 8000
# 或生产：gunicorn api:app -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 --preload
```

前端（Streamlit，默认 8501）：

```bash
streamlit run app.py
# 指向远程后端：export FAQ_API_BASE=http://127.0.0.1:8000
# 不设 FAQ_API_BASE 时前端直接进程内调用 FaqBot（单进程部署用）
```

命令行问答（不依赖网络）：

```bash
python -m src.agent
# 交互命令：/help 帮助 · /stats 状态 · /reload 热更新语料 · /top 查看上一条 Top-3 · /exit 退出
```

### 3.5 验证

```bash
# 单测（起后端后 173 个用例全部执行；不起后端时 7 个前端集成用例会 skip）
python -m pytest -q

# 效果评估
python evaluate.py                  # 按当前阈值评估
python evaluate.py --show-error     # 打印答错样本与改进方向
python evaluate.py --min-recall 0.95  # CI 回归门禁：低于基线非零退出
python evaluate.py --scan           # 扫描阈值找最优平衡点
python evaluate.py --backend tfidf  # 临时切 TF-IDF 对比

# 三方案实测对比（TF-IDF / BGE / 精排）
python scripts/benchmark_retrieval.py

# 健康检查
curl http://127.0.0.1:8000/health
```

---

## 四、使用示例

### 4.1 HTTP API

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"query":"图书馆几点开门","user_id":"u-001"}'
```

响应（命中语料）：

```json
{
  "answer": "图书馆周一至周日 8:00-22:00 开放…",
  "matched": true,
  "tag": "library_hours",
  "score": 1.0,
  "cache_hit": false,
  "trace_id": "...",
  "vectorizer": "bge",
  "security": {"reason": "", "pii_hits": [], "injection_rules": []}
}
```

未命中时 `matched=false`，`fallback` 会说明走了哪条通道：

```json
{"matched": false, "fallback": {"type": "weather", "source": "weather", "rule": "realtime_weather"}}
```

`/ask` 还有一个派生接口 `/suggest`：返回首页那 7 个高频问题的 chip 文案。

### 4.2 Python 进程内调用

```python
from src.agent import FaqBot

bot = FaqBot()                                   # 默认 BGE；FaqBot(vectorizer_type="tfidf") 可切
r = bot.ask("宿舍灯坏了找谁修", user_id="demo")
print(r["matched"], r["tag"], r["answer"])

bot.reload()                                     # 语料改动后热更新（会顺带清空答案缓存）
```

### 4.3 Docker

```bash
# 1. 准备密钥文件（不要带换行）
echo -n "sk-xxx"   > secrets/deepseek_key.txt
echo -n "your-key" > secrets/hefeng_key.txt

# 2. 构建（首次约 10 分钟，主要花在 torch 196MB + BGE 模型 93MB）
docker build -t faq-bot:v8 .

# 3. 启动
docker compose up -d

# 4. 验证
curl http://127.0.0.1:8000/health
```

镜像约 2.4GB，启动后约 20 秒完成 BGE 加载（healthcheck 的 `start_period` 给了 60 秒）。

---

## 五、实测效果

测试集 136 条（132 可答 + 4 应拒答），与语料**物理隔离、人工改写**（换同义词、改语序、加口语助词）。

| 方案 | 构建耗时 | 召回@1 | Top-3 命中 | 未识别率 | 误答率 | P50 延迟 |
|------|---------|--------|-----------|---------|-------|---------|
| TF-IDF | 15 ms | 57.0% | 95.7% | 37.6% | 5.4% | 1.1 ms |
| **BGE-small（默认）** | 4.96 s（含模型加载） | **99.2%** | **100%** | **0.0%** | 0.8% | 7.9 ms |
| BGE + 精排 | 未实测 | — | — | — | — | — |

当前指标（`python evaluate.py`，阈值 0.60）：

| 指标 | 实测 | 目标 | 判定 |
|------|------|------|------|
| 召回率@1 | 99.2% | ≥ 80% | ✅ |
| Top-3 命中率 | 100.0% | ≥ 95% | ✅ |
| 未识别率 | 0.0% | ≤ 10% | ✅ |
| 误答率 | 0.8% | ≤ 5% | ✅ |
| **误触发率** | **25.0%** | ≤ 10% | ❌ **未达标** |
| 整体准确率 | 98.5% | — | — |

> **⚠️ 诚实说明（三点）**
> 1. **99.2% 是「封闭测试集」结果**。语料本身也是我写的，真实用户问法远比测试集发散，
>    上线后准确率必然下降。正确的做法不是死磕算法，而是靠运营闭环——定期导出
>    `logs/unmatched.jsonl` 里的未命中问题补进语料。
> 2. **误触发率 25% 未达标**：4 条应拒答样本里有 1 条被答了（分母太小，一条就占 25%）。
>    测试集应拒答样本偏少是主因，已列入待办（见 `docs/pending_items.md`）。
> 3. **精排（Cross-Encoder）管线已写通但默认关闭**（`ENABLE_RERANK=True` 启用，模型
>    `BAAI/bge-reranker-base`）。BGE 已在封闭集 99.2% 命中，精排在这里没有提升空间；
>    它的真实价值在易混淆/长尾意图，**需要更大的评测集才能验证**。
>    命中判定走独立的 `RERANK_THRESHOLD`（config 里 0.5 只是占位，启用后必须标定），
>    余弦分数保留不动——此前精排分直接覆盖余弦分、再拿余弦阈值判定，量纲错位。

---

## 六、项目结构

```
faq-bot/
├── api.py                    # FastAPI 生产入口（/health ｜ /suggest ｜ /ask）
├── app.py                    # Streamlit 网页入口（问答 + 校园地图两个 tab）
├── evaluate.py               # 效果评估脚本（含 --min-recall 回归门禁）
├── data/
│   ├── qa_corpus.json        # 问答语料（49 个意图 / 411 条问法，v1.6.0）
│   ├── stopwords.txt         # 停用词表
│   └── raw_notices/          # 手抓的真实通知原文，用于扩充语料
├── src/
│   ├── config.py             # 全局配置（路径 / 阈值 / 开关 / 模型 / 并发参数）
│   ├── preprocess.py         # L1 预处理（归一化 / 分词 / 去停用词）
│   ├── vectorizer.py         # L2 向量化（TF-IDF / BGE 双实现）
│   ├── retriever.py          # L3 召回（余弦相似度 Top-K）
│   ├── ranker.py             # L4 精排（Cross-Encoder，默认关；含降级直通）
│   ├── cache.py              # 答案缓存（LRU + TTL，线程安全）
│   ├── agent.py              # L5 主编排 + 命令行入口
│   ├── logger.py             # L7 问答日志、未命中采集、PII 强制脱敏
│   ├── campus_map.py         # 校园地图自包含查看器
│   ├── ui_style.py           # 前端去 AI 味：CSS 覆盖 + 主题常量
│   ├── security/             # W2 安全层（四道防线）
│   │   ├── __init__.py       #   enforce_security() 统一编排入口
│   │   ├── redact.py         #   PII 脱敏（手机号/身份证/邮箱/银行卡/IP/URL）
│   │   ├── injection.py      #   Prompt injection 检测（角色劫持/提示词泄露）
│   │   ├── rate_limit.py     #   令牌桶限流（IP + user_id 双维度）
│   │   ├── budget.py         #   滑动窗口成本熔断
│   │   └── redis_backend.py  #   可选的 Redis 共享计数（多 worker 精确限流）
│   └── fallback/             # 兜底增强层
│       ├── __init__.py
│       ├── router.py         #   路由器：闲聊/实时/校园/通识 四路分发
│       ├── llm_client.py     #   DeepSeek 客户端（标准库 urllib）
│       └── weather.py        #   和风天气 API（城市查询 + 实况 + 3 天预报）
├── tests/                    # 173 个用例（见下）
├── scripts/                  # 语料抓取 / 报告生成 / 效果对比等独立脚本
├── docs/                     # 架构图、审计文档、部署说明（见「文档索引」）
├── assets/campus_maps/       # 双校区手绘底图
├── nginx/                    # 反向代理配置 + 自签证书说明
├── logs/                     # 运行日志（自动生成，已 gitignore）
├── secrets/                  # Docker secret 文件（不进 git）
├── .streamlit/config.toml    # 前端主题 token
├── Dockerfile                # 多阶段构建（CPU torch + BGE 预下载）
├── docker-compose.yml
└── requirements.txt
```

测试文件与用例数：

| 文件 | 用例 | 覆盖 |
|---|---|---|
| `test_security.py` | 38 | PII 脱敏 + 注入检测 |
| `test_api.py` | 27 | API 层（health/suggest/ask/安全/错误处理） |
| `test_rate_limit_budget.py` | 22 | 限流 + 成本熔断 |
| `test_weather_city.py` | 19 | 天气城市抽取 |
| `test_security_integration.py` | 12 | 安全层端到端集成 |
| `test_cache.py` | 12 | 答案缓存 + 慢路径隔离 |
| `test_ui.py` | 10 | 前端渲染（去 AI 味 / 调试信息不外泄） |
| `test_secret_loading.py` | 8 | Docker secret（`*_FILE`）解析 |
| `test_redis_backend.py` | 8 | Redis 共享计数与降级 |
| `test_redact.py` | 7 | 密钥不落日志 |
| `test_ranker.py` | 5 | 精排：分数解耦 / 加载失败降级 |
| `test_fallback.py` | 4 | 兜底路由分类与安全边界 |
| `test_campus_map.py` | 1 | 地图渲染冒烟测试 |

---

## 七、技术架构

![系统架构图](docs/architecture.svg)

浏览器经 Nginx 反代访问 FastAPI；请求先过 **W2 安全层**四道防线，命中知识库直接返回，
未命中走**兜底路由器**（闲聊 / 实时 / 校园 / 通识），任何层失败都降级到固定话术、绝不裸抛。

两套向量化后端：

| 版本 | 向量化 | 模型大小 | CPU 延迟/句 | 中文语义匹配 | 适用场景 |
|------|--------|---------|------------|-------------|----------|
| v1 | TF-IDF | 0 | <1ms | 只认词面重叠 | 学习 NLP 流程、入门演示 |
| **v3（默认）** | BGE-small-zh-v1.5 | ~93MB | 5-15ms（编码后 0.5ms） | 强语义匹配 | 真实部署、问法发散场景 |

### 请求链路

```
用户提问
  ↓
1. injection 检测   ← 高风险直接拒答（如"忽略之前的指令"）
  ↓
2. 限流检查        ← IP / user_id 双维度令牌桶
  ↓
3. 答案缓存查找     ← ★ 必须在安全层之后，否则限流被绕过
  ↓（未命中缓存）
4. FAQ 检索
  ├─ 命中（≥ 0.60）→ 返回语料答案（不消耗任何 LLM 额度）
  └─ 未命中 → 5. 慢路径闸（并发上限，超限立刻降级固定话术）
                ↓
              6. 兜底路由器（闲聊/实时/校园/通识）
                ↓
              7. 预算熔断检查（1h 内不超 500 次 / 10 元）
                ↓
              8. PII 脱敏 → 把 sanitized 版本喂 LLM，原文返回给用户
```

### 抗并发设计（2026-09 实测）

| 机制 | 解决什么 | 效果 |
|---|---|---|
| 答案缓存 | 同一问法反复重算 BGE | 峰值吞吐 **105 → 960 req/s**（并发 32，24 核） |
| 慢路径隔离 | 兜底（1.4~8s）占满线程池拖垮检索（~10ms） | 劣化从 **19× → 1.3×** |
| `torch.set_num_threads(1)` | 线程池 × 每算子吃满核 = 过订阅 | 高并发 **+20%** 吞吐 |
| `gunicorn --preload` | 每 worker 各加载一份模型（~400MB） | 子进程 COW 共享同一份 |

---

## 八、配置项与环境变量

### 8.1 环境变量一览

| 变量 | 默认 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | （空） | DeepSeek 密钥。留空则通识问题降级为固定话术 |
| `HEFENG_API_KEY` | （空） | 和风天气密钥。留空则天气问题降级 |
| `HF_HOME` | （系统默认） | HuggingFace 模型缓存目录（国内可指向已有缓存） |
| `FAQ_REDIS_URL` | （空） | 设了则限流/预算改走 Redis 共享计数（多 worker 精确） |
| `FAQ_TRUST_PROXY_HEADERS` | `0` | 是否信任 `X-Real-IP` / `X-Forwarded-For`。**仅当 API 只暴露在可信反代后时开**，直连部署必须保持关闭（否则 IP 限流可被伪造头绕过） |
| `FAQ_CORS_ORIGINS` | 本地地址 | 允许的跨域来源，逗号分隔 |
| `FAQ_DEBUG` | `0` | 前端调试模式：显示 `trace_id` / 相似度 / 候选列表 |
| `FAQ_API_BASE` | （空） | 前端指向的后端地址；不设则前端进程内直调 `FaqBot` |
| `FAQ_ANSWER_CACHE` | `1` | 答案缓存开关 |
| `FAQ_SLOW_PATH_MAX` | `8` | 兜底链路最大并发（超限立刻降级） |
| `FAQ_TORCH_THREADS` | `1` | torch 推理线程数（CPU 推理靠多进程并行，不靠进程内多线程） |

### 8.2 安全层参数（`src/config.py`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `SECURITY_ENABLED` | True | 总开关（生产必须 True） |
| `REDACTION_ENABLED` | True | PII 脱敏开关 |
| `INJECTION_ENABLED` | True | Prompt injection 检测 |
| `RATE_LIMIT_IP_CAPACITY` / `_REFILL` | 30 / 0.5 | IP 桶容量（突发）/ 每秒补充（稳态） |
| `RATE_LIMIT_USER_CAPACITY` / `_REFILL` | 60 / 1.0 | user_id 桶同上 |
| `BUDGET_WINDOW_SEC` / `_MAX_CALLS` / `_MAX_COST_CNY` | 3600 / 500 / 10.0 | 滑动窗口长度 / 最多 LLM 次数 / 估算成本上限 |
| `DEEPSEEK_TIMEOUT` | 8s | 超时直接降级 |
| `HEFENG_TIMEOUT` | 6s | 同上 |

> **注意**：限流 / 预算在未配置 Redis 时是**进程内计数**，多 worker 时实际额度 ≈ worker 数 × 配置值。
> 需精确限流请设 `FAQ_REDIS_URL`（`docker-compose.yml` 里有注释掉的 redis 服务）；
> Redis 连不上会自动退回进程内实现，不会因此拒服务。

### 8.3 安全边界

| 风险 | 缓解 |
|---|---|
| LLM 编造校务 | 系统提示钉死 + 校园关键词拦截在 LLM 之前 |
| LLM 编造天气 | 天气永远走 API，不进 LLM |
| 成本失控 | `DEEPSEEK_TIMEOUT=8s` 超时降级 + 滑动窗口成本熔断 |
| API 密钥泄露 | `.env` 加载，不进 git；写入日志前 `redact()` 强制脱敏 |
| LLM 异常 | dispatch 外包 try/except 降级到 `FALLBACK_TEXT`，不裸抛 |
| 用户在 query 里贴手机号 / 身份证 | PII 脱敏，喂 LLM 前替换为 `[手机号]` 等占位符 |
| "忽略之前的指令"等攻击 | Prompt injection 检测（高风险直接拒答） |
| 单 IP / 用户刷接口 | 令牌桶限流（IP 30 突发，用户 60 突发） |
| 月底被刷爆账单 | 滑动窗口成本熔断（默认 1h / 500 次 / 10 元） |

---

## 九、常见问题（FAQ）

<details>
<summary><b>Q1. 为什么写的是 99.2% 而不是 100%？</b></summary>

早期版本确实到过 100%，但那是在 97 条测试集上的结果。后来把测试集扩到 **136 条**（新增更多
口语化、省略式问法）并放宽到 132 条可答样本后，暴露出 1 条真实未命中，所以现在是 **99.2%（131/132）**。

**数字下降不是因为变差了，而是因为测试集变难了**。指标数字必须跟着测试集一起说明，否则就是自欺欺人。
</details>

<details>
<summary><b>Q2. 指标里的「误触发率 25%」是怎么回事？</b></summary>

指 4 条「应拒答」样本里有 1 条被答了。**分母只有 4，一条就占 25%**，统计意义有限。

真正的问题是**应拒答样本太少**（正常应该几十条），已列入待办。
不过这条指标值得盯：它衡量的是"机器人会不会硬答它不知道的问题"，比召回率更能反映用户体验。
</details>

<details>
<summary><b>Q3. 为什么不做模型训练 / 微调？</b></summary>

因为**这个场景不需要**：语料是封闭的 FAQ（49 个意图），用预训练 BGE 做检索就能拿到 99%+ 的召回。
训练模型要标注数据、要算力、要调参，收益还不如"把问法补到 8 条覆盖不同说法"。

工程上先问"这个问题必须用模型解吗"，答案是"不必须"时，**不做模型才是最正确的选择**。
</details>

<details>
<summary><b>Q4. 模型下载不动 / 装不上 torch</b></summary>

```bash
# 用国内镜像（或在已有缓存时直接指过去）
export HF_ENDPOINT=https://hf-mirror.com
export HF_HOME=/path/to/your/hf_cache

# torch 必须装 CPU 版，否则会拉 1GB+ 的 CUDA 包
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

完全离线也可以：把 env 里 `FAQ_ANSWER_CACHE` 之外的方式都不用管，
把 `VECTORIZER_TYPE` 改成 `tfidf` 就能零模型依赖跑起来（代价是召回率掉到 57%）。
</details>

<details>
<summary><b>Q5. 改了语料 / 配置为什么不生效？</b></summary>

两个最常见原因：

1. **`.env` 和环境变量是进程启动时读的** —— 改完必须**重启进程**。症状是"配置明明对了，行为就是不变"。
2. **语料改了没热更新** —— 命令行里输入 `/reload`，或在代码里调 `bot.reload()`；
   重启服务也可以。注意 `reload()` 会同时清空答案缓存（这是有意的，避免返回上一版答案）。

另外 `src/ui_style.py` 里的 CSS 和 `.streamlit/config.toml` 里的主题都是**模块级常量 / 启动时读取**，
改完同样必须重启 Streamlit。
</details>

<details>
<summary><b>Q6. 前端报「服务暂时不可用」/ 问什么都连不上？</b></summary>

按顺序排查：

1. 后端起了吗？`curl http://127.0.0.1:8000/health` 应返回 `{"status":"ok","ready":true}`
2. 前端指向的后端地址对吗？设了 `FAQ_API_BASE` 就按它走，不设则进程内直调
3. 端口的旧进程没退干净？换端口起一个对比
4. `ready=false` 说明模型还没加载完（首次约 6~20 秒），稍等
</details>

<details>
<summary><b>Q7. 限流会不会误伤正常用户？</b></summary>

会，这是**设计上的已知问题**：IP 桶容量 30、稳态补充 0.5 次/秒，而**校园网普遍 NAT**——
一栋宿舍楼可能共用一个出口 IP，几百人共享 30 个令牌。

多 worker 时情况更宽松（每 worker 各有一套计数），但这只是掩盖问题。
正确做法是把 IP 桶只当"防刷上限"（高容量），业务限流交给 `user_id` 桶。已列入待办。
</details>

<details>
<summary><b>Q8. 为什么日志文件会越来越大？</b></summary>

当前是 **JSONL 追加写、无轮转**。`logs/` 已在 `.gitignore` 里，所以不会污染仓库，
但磁盘会涨、排障要手动 grep。规模上来后应加按天切分或异步写入队列。当前量级可接受，先记着这个边界。
</details>

<details>
<summary><b>Q9. 为什么要给大模型调用设"预算熔断"？</b></summary>

因为**没有上限的 LLM 调用 = 没有上限的账单**。设计上：

- 命中语料的问答**完全不消耗** LLM 额度（绝大多数请求走这条路）
- 只有通识类未命中才调 LLM，且 1 小时内不超过 500 次 / 估算 10 元
- 预算耗尽后只影响 LLM 通道，闲聊/天气/校园事务照常工作（不会"全站瘫痪"）

这条是踩过坑改出来的：早期版本在路由前就查预算，预算耗尽后连"你好"都被拒答。
</details>

<details>
<summary><b>Q10. 语料里的答案怎么保证不是编的？</b></summary>

建立了**溯源体系**：每条答案在 `_meta` 里标注来源类型——

- `real_notice_v3`：摘录自学校部门**通知原文**（带 url / title / date）
- `official_doc`：取自官方**文档 / 网页**
- `guidance`：未取得原文，只写通用办理流程并指向官方渠道（**不含具体日期/比例/门槛**）

目前仍有 22 个意图拿不到可核来源，已经整理成可执行的核查清单
（`docs/manual_collection.md`）：逐条写明"要搜集什么 / 为什么必须人工（实地调研 · 内部数据 · 口径判断）/
优先级 / 预期答案形式"。**宁可写引导型，也不编造。**

接手的同学建议先读 `docs/pending_items.md`。
</details>

---

## 十、已知限制

- **限流/预算默认仍是进程内计数**：未配置 Redis 时额度 ≈ worker 数 × 配置值
  （实测 80 并发放行 52 次 ≈ 2×30）。设 `FAQ_REDIS_URL` 即启用共享计数。
- **校园 NAT 场景下 IP 限流偏紧**：见 FAQ Q7。
- **误触发率 25% 未达标**：应拒答样本太少（仅 4 条），见 FAQ Q2。
- **天气支持实况 + 3 天预报**：问句带「明天/后天」走 `/v7/weather/3d`（免费额度内）；
  「周末」「下周」等更远的日期暂不支持，会回落到实况。
- **精排未实测**：封闭集上无提升空间，需更大评测集，见第五节说明。
- **前端不适合高并发**：Streamlit 单进程 + 每次交互重跑整个脚本，多人同时用会先于后端成为瓶颈。
- **镜像偏大（2.4GB）**：如需瘦身可考虑 `--no-compile` 装 torch、或把 BGE 换 TF-IDF。
- **22 个意图无溯源**：见 FAQ Q10 与 `docs/unsourced_intents.md`。

---

## 十一、开发与运维

### 11.1 测试与 CI

```bash
python -m pytest -q                      # 173 个用例
ruff check .                             # 静态检查
python evaluate.py --min-recall 0.95     # 效果回归门禁（CI 里跑的就是这条）
```

CI（`.github/workflows/ci.yml`）在 `ubuntu-latest` 上依次执行：ruff → 起 API 服务 →
`pytest -q` → **效果门禁**。最后一条是关键：**单测只保证"代码没坏"，不保证"效果没掉"**——
改了检索或语料后召回率可能悄悄下滑而 pytest 全绿，所以把召回率也做成了可断言的出口。

> CI 已用 `actions/cache` 缓存 HuggingFace 模型，避免每次重下 93MB。

### 11.2 加新问答

编辑 `data/qa_corpus.json`，往 `intents` 里加一个对象：

```json
{
  "tag": "print_service",
  "questions": ["哪里可以打印东西", "打印店在哪", "怎么打印文件", "学校打印贵不贵", "自助打印在哪里"],
  "answer": "打印店位于学生服务中心 2 楼，黑白 0.2 元/页，彩色 1 元/页。",
  "_meta": {"source": "学生服务中心", "category": "生活服务", "url": "...", "title": "...", "date": "2026-09-01", "type": "official_doc"}
}
```

要点：

- **`questions` 至少 5 条**，覆盖口语、书面、省略、倒装等不同问法。这一条对准确率的贡献大于换更强的算法。
- 改完 `/reload` 即可生效，无需重启。
- 专业名词被 jieba 切碎时（如"勤工助学"→"勤工/助学"），加进 `src/config.py` 的 `CUSTOM_WORDS`。
- **能给出 `_meta` 就给**：它是"这条答案有出处"的凭据，也是审计与后续核对的依据。

### 11.3 Docker 联调踩过的 4 个坑（2026-09-08 实测）

| # | 现象 | 根因 | 解法 |
|---|---|---|---|
| 1 | 装完 CPU 版 torch，装 `requirements.txt` 时又去拉 1GB 的 CUDA 包 | `pip install --prefix=/install` 装的包不在 `sys.path` 上，pip 认为 torch 没装，从主源重新解析（主源只有 CUDA 版） | 设 `ENV PYTHONPATH=/install/lib/python3.11/site-packages`，让 pip 看见已装的 `2.14.0+cpu` |
| 2 | `ResolutionImpossible` | 试过用 `-c constraints.txt` 钉死 `torch==2.14.0+cpu`，但主源里根本没有 `+cpu` 这种 local version 的候选 | 放弃 constraint，改用上面的 PYTHONPATH 方案 |
| 3 | `RUN python -c "..."` 换行续写报 `IndentationError` | Dockerfile 会保留行首空格 | 写成单行，或 COPY 一个 `.py` 进来跑 |
| 4 | 容器里 `/run/secrets/*` 挂载正常，却一直告警"KEY 未配置" | `config.py` 里 `_load_secret` 有**两处**定义（一处 `def` + 一处别名赋值），后面的 `def` 把带 `_FILE` 支持的版本覆盖掉了 | 只保留一处定义（见 `tests/test_secret_loading.py` 的防回归断言） |

### 11.4 和风天气 Host 配置（最容易搞错）

- 自定义域名前缀是**控制台分配**的（形如 `mc3byj5bbc`），**不是** API key 的前 8 位。
  填错时不会返回和风标准的 `problem+json`，而是「`Content-Length: 0` 的裸 403」，
  极易误判成网络问题。判断办法：**不带 key 直接请求**，若同样裸 403，就是 host 错了。
- 自定义域名下天气和城市查询**共用同一个 host**，只有 path 不同：
  - `weather` → `{BASE_URL}/v7/weather/now`
  - `geo` → `{BASE_URL}/geo/v2/city/lookup`
  代码里 geo 拼的是 `{HEFENG_GEO_URL}/v2/city/lookup`，所以 `HEFENG_GEO_URL`
  必须写成 `...re.qweatherapi.com/geo`（带 `/geo`）。只有用官方 devapi 的账号
  才写 `https://geoapi.qweather.com`。

### 11.5 前端：去 AI 味的三条原则

**核心判断：AI 味的本质不是配色，是「开发者信息」和「用户信息」混在一起。**
原来一条回答叠 5 层（emoji 标题 + 技术栈副标题 + 橙色警示色块 + 彩色徽章 + trace_id 详情），
其中至少 3 层学生根本不看。砍掉调试信息 + 改文案就能消掉约 70% 的 AI 味，比换配色有效得多。

| 位置 | 改前 | 改后 |
|---|---|---|
| 标题 | 🎓 校园 FAQ 问答助手 + "v7 (FastAPI 后端)" | 校园问答 + 学校名 |
| 来源 | 5 色 HTML 徽章 + 匹配度 87% | 一行灰字「来自知识库」 |
| AI 回答 | 橙色警示色块 + 徽章，说两遍 | 只留一行「AI 生成 · 非官方答复」 |
| 候选 | 3 条进度条 + `0.872` | 未命中时才出现的「你可能还想问」可点按钮 |
| 加载/反馈 | 「正在思考…」「已收到反馈，我们会改进」 | 「查询中」+ toast「谢谢」 |
| 侧边栏 | 左侧「运行状态 / 反馈统计」两面板常驻 | 整块删除；反馈统计挪到页面底部，仅 `FAQ_DEBUG=1` 显示 |
| 高频问题 | 只在首屏出现一次，问完即被对话顶走 | 常驻输入栏上方，7 个可点 chip |

### 11.6 调试模式

排查问题时在启动前端的终端里设 `FAQ_DEBUG=1`，才会显示 `trace_id`、相似度、候选题列表、向量化方式、API 地址。

**默认一律不显示**。2026-09 修复：调试开关从 URL 参数 `?debug=1` 改为环境变量——
URL 参数任何访客都能加，等于无鉴权泄露内部信息；`tests/test_ui.py` 里有断言钉死这点。

### 11.7 主题与样式

- 主题 token：`.streamlit/config.toml`（改完**必须重启** streamlit，不支持热更新）
- CSS 覆盖：`src/ui_style.py`（去掉顶部彩虹条、页脚、彩色气泡、过重描边）

> ⚠️ **主色写在两处，改色时必须同步**：`config.toml` 的 `primaryColor` 管 Streamlit 原生组件，
> `src/ui_style.py` 的 `PRIMARY` 管自定义 CSS。config.toml 读不到 Python 变量，只能手工保持一致。

样式代码放 `src/` 而不是项目根目录，是因为 Dockerfile 只 COPY `api.py / app.py / src/ / data/`，
根目录新建 `.py` 不会进镜像，容器里 import 会炸。

### 11.8 三个必踩的坑（已经替你趟过）

1. **索引与查询必须用同一套预处理**。早期版本索引用原始句子、查询用分词句子，两边词汇表对不上，
   相似度恒为 0 且**不报错**。现已把预处理内聚进 `Retriever`，从根上杜绝。
2. **通用疑问词会带偏匹配**。"怎么""哪里""多少钱"几乎每条问句都有，不去掉的话，
   "灯泡坏了找谁"会被"成绩单盖章找谁"抢走命中。它们已在 `stopwords.txt` 里过滤。
3. **TF-IDF 只认词面重叠**。"寝室灯泡坏了"和"宿舍灯坏了"这种同义词换用，TF-IDF 相似度就是 0。
   这是它的固有瓶颈，不是 bug——当语料已足够丰富、召回率仍卡在 70% 以下时，就该升级语义向量了。

---

## 十二、文档索引

| 文档 | 用途 |
|---|---|
| `docs/architecture.svg` | 系统架构图 |
| `docs/pending_items.md` | **接手新工作先读这份**：待补说明 / 待人工搜集审核清单 |
| `docs/manual_collection.md` | 22 条无溯源意图的可执行核查表（要搜集什么 / 为什么必须人工 / 优先级 / 答案形式） |
| `docs/unsourced_intents.md` | 无溯源意图的风险分级（P0/P1/P2） |
| `docs/fact_audit.md` | 语料事实审计报告 |
| `docs/contact_phones.md` | 学校各部门官方联系方式台账 |
| `docs/answerable_samples.md` | 可答样本盘点 |
| `docs/deploy_hf_spaces.md` | Hugging Face Spaces 在线 Demo 部署说明 |
| `docs/screenshots/` | 效果截图 |

---

## 十三、版本历史

| 阶段 | 内容 | 状态 |
|------|------|------|
| v1 | TF-IDF + 命令行 + 网页 | ✅ |
| v3 | BGE-small-zh 句向量 + 真实通知语料 | ✅ |
| v4 | 大模型兜底 + 实时 API（DeepSeek + 和风天气），兜底路由器分流 | ✅ |
| W2 | 安全层：PII 脱敏 / 注入检测 / 令牌桶限流 / 成本熔断 | ✅ |
| v7 | Docker 多阶段部署（CPU torch + BGE 预下载 + secret 注入） | ✅ |
| v7.1 | 前端去 AI 味：去侧边栏 / 高频问题 chip / 调试信息默认隐藏 | ✅ |
| v8 | Redis 共享限流/预算 · 天气 3d 预报 · 精排加固（独立阈值） | ✅ 当前 |
| v8.1 | 抗并发三件套（答案缓存 / 慢路径隔离 / torch 线程）· CI 召回率门禁 · `gunicorn --preload` | ✅ 当前 |
| 语料 v1.6.0 | 49 意图 / 411 问法；新增溯源审计、人工核查清单 | ✅ 当前 |

### 升级路线（待办）

| 方向 | 说明 |
|---|---|
| 扩测试集到 300+ | 现在 136 条、封闭集，统计意义有限；口径必须与语料物理隔离（人工改写） |
| 开放集评测 | 只有它才能验证「两级意图索引」和「精排」是否真的有用 |
| 慢路径进一步隔离 | 把 LLM/天气挪出请求线程（后台任务 + 轮询） |
| NAT 友好的限流策略 | IP 桶只做防刷上限，业务限流交给 user_id |
| 日志轮转 / 异步写入 | 当前 JSONL 追加写无轮转 |
| 前端替换 | Streamlit 不适合多人并发 |
