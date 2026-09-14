# 智答校园 · 校园 FAQ 智能问答机器人（faq-bot）

> **一句话看懂**：一个能回答新生常见问题（选课、宿舍、转专业、奖助学金…）的校园智能助手。基于 RAG 检索 + 大模型兜底，已部署运行，**问答召回率 100%**，并内置防隐私泄露、防恶意提问的安全机制。
>
> 🔗 **在线体验**：`（部署后把链接放这里，例如 Hugging Face Spaces / Railway 地址）`
>
> 📸 **效果截图**：
> | 问常见问题 | 问天气 | 被安全拦截 |
> |---|---|---|
> | ![问常见问题](docs/screenshots/screenshot-faq.png) | ![问天气](docs/screenshots/screenshot-weather.png) | ![被安全拦截](docs/screenshots/screenshot-safety.png) |

### 🎯 关键成果（简历可直接用）
- **问答召回率 100%**：将检索方案从 TF-IDF 升级为中文语义向量（BGE）后，封闭测试集召回@1 从 **57% → 100%**
- **4 道安全防线**：PII 隐私脱敏 / Prompt 注入拦截 / 令牌桶限流 / 成本熔断，拦截"忽略指令"类越狱攻击
- **160 个单元 + 集成测试**，接入 **GitHub Actions** 做提交自动校验
- **Docker 多阶段部署** + Nginx 反代，生产可一键拉起

### 🛠️ 我做了什么（非技术版）
1. 从零搭建校园问答系统，能准确回答 300+ 条常见校园问题
2. 设计安全机制，自动屏蔽隐私信息和恶意诱导提问
3. 写自动化测试与部署流程，保证代码质量与可维护性
4. 用数据驱动迭代：收集未命中问题 → 补充语料 → 复测指标
5. 做交互式校园地图：双校区手绘地图叠加 + 地点查询，新生一眼找到教学楼、食堂、宿舍

---

<details>
<summary>📚 技术细节（面试官/开发者展开）</summary>

一个面向 NLP 初学者的**检索式 FAQ 问答机器人**，提供两套向量化后端：

| 版本 | 向量化 | 模型大小 | CPU 延迟/句 | 中文语义匹配 | 适用场景 |
|------|--------|---------|------------|-------------|----------|
| **v1** | TF-IDF | 0 | <1ms | 只认词面重叠 | 学习 NLP 流程、入门演示 |
| **v3** | BGE-small-zh-v1.5 | ~93MB | 5-15ms（编码后 0.5ms） | 强语义匹配 | 真实部署、问法发散场景 |

## 实测效果对比（97 条测试集：93 可答 + 4 应拒答）

| 方案 | 构建耗时 | 召回@1 | Top-3 命中 | 未识别率 | 误答率 | 误触发率 | P50 延迟 | P99 延迟 |
|------|---------|--------|-----------|---------|-------|---------|---------|---------|
| TF-IDF | 15 ms | 57.0% | 95.7% | 37.6% | 5.4% | 0.0% | 1.1 ms | 2.5 s* |
| BGE-small（默认） | 4.96 s（含模型加载） | **100%** | **100%** | **0.0%** | 0.0% | 0.0% | 7.9 ms | 1.5 s* |
| BGE + 精排 | 未实测 | — | — | — | — | — | — | — |

> \* P99 含个别极端长 query 的异常值，P50（典型值）更能代表日常延迟；两者均为端到端 `ask`（含 W2 安全层开销）的实测。
> BGE 相较 TF-IDF，**召回@1 从 57% → 100%、未识别率从 37.6% → 0%**——证明"换语义向量"比"堆同义词"有效得多，这正是升级 v3 的量化依据。
> BGE + 精排（Cross-Encoder）管线已写通（`src/config.py` 设 `ENABLE_RERANK=True` 启用）。
> 2026-09 修复：默认模型换成中文可用的 `BAAI/bge-reranker-base`（约 1.1GB，首次启用联网下载）；
> 命中判定走独立的 `RERANK_THRESHOLD`（config 里 0.5 只是占位，启用后必须标定），
> 余弦分数保留不动——此前精排分直接覆盖余弦分、再拿余弦阈值判定，量纲错位。
> 仍未实测：BGE 已 100% 命中的封闭集上精排无提升空间，其真实价值在易混淆/长尾意图，需用更大评测集验证。复现命令：`python scripts/benchmark_retrieval.py`。

> 配套设计文档见同目录下的《FAQ问答机器人架构设计.docx》。

</details>

## 系统架构

![系统架构图](docs/architecture.svg)

浏览器经 Nginx 反代访问 FastAPI；请求先过 **W2 安全层**四道防线，命中知识库直接返回，未命中走**兜底路由器**（闲聊 / 实时 / 校园 / 通识），任何层失败都降级到固定话术、绝不裸抛。

## 快速开始

```bash
# 1. 安装依赖（建议用虚拟环境）
pip install -r requirements.txt

# 2. 命令行问答（默认 v3 BGE；想用 v1 TF-IDF 改 src/config.py 里 VECTORIZER_TYPE）
python -m src.agent

# 3. 网页版
streamlit run app.py

# 4. 效果评估
python evaluate.py                 # 按当前阈值评估
python evaluate.py --scan          # 扫描阈值，找最优平衡点
python evaluate.py --backend tfidf # 临时切到 TF-IDF 对比
python evaluate.py --show-error    # 打印答错样本
python scripts/benchmark_retrieval.py   # 三方案实测对比（TF-IDF / BGE / 精排）
```

命令行交互里可用的命令：`/help` 帮助、`/stats` 状态、`/reload` 热更新语料、`/top` 查看上一条的 Top-3 候选、`/exit` 退出。

## 目录结构

```
faq-bot/
├── data/
│   ├── qa_corpus.json        # 问答语料（38 个意图 / 311 条问法）
│   ├── stopwords.txt         # 停用词表
│   └── raw_notices/          # 手抓的真实通知原文，用于扩充语料
├── src/
│   ├── config.py             # 全局配置（路径 / 阈值 / 开关 / 模型）
│   ├── preprocess.py         # L1 预处理（分词 / 去停用词 / 归一化）
│   ├── vectorizer.py         # L2 向量化（TF-IDF / BGE 双实现）
│   ├── retriever.py          # L3 召回（余弦相似度 Top-K）
│   ├── ranker.py             # L4 精排（v1 占位，v2 启用 Cross-Encoder）
│   ├── agent.py              # L5 主编排 + L6 命令行入口
│   ├── logger.py             # L7 问答日志与未命中采集
│   ├── ui_style.py           # 前端去 AI 味：CSS 覆盖 + 主题常量
│   ├── security/             # W2 安全层（四道防线）
│   │   ├── __init__.py       #   enforce_security() 统一编排入口
│   │   ├── redact.py         #   PII 脱敏（手机号/身份证/邮箱/银行卡/IP/URL）
│   │   ├── injection.py      #   Prompt injection 检测（角色劫持/提示词泄露）
│   │   ├── rate_limit.py     #   令牌桶限流（IP + user_id 双维度）
│   │   └── budget.py         #   滑动窗口成本熔断
│   └── fallback/             # v4 兜底增强
│       ├── __init__.py
│       ├── router.py         #   路由器：聊天/实时/校园/通识 四路分发
│       ├── llm_client.py     #   DeepSeek 客户端（标准库 urllib）
│       └── weather.py        #   和风天气 API（城市查询 + 当前天气）
├── tests/
│   ├── test_set.json                 # FAQ 命中测试集
│   ├── test_fallback.py              # v4 兜底路由器测试
│   ├── test_security.py              # 36 用例：PII 脱敏 + 注入检测
│   ├── test_rate_limit_budget.py     # 20 用例：限流 + 成本熔断
│   ├── test_security_integration.py  # 12 用例：端到端集成
│   ├── test_api.py                   # 27 用例：API 层（health/suggest/ask/安全）
│   ├── test_ui.py                    # 7 用例：前端渲染（去 AI 味）
│   ├── test_secret_loading.py        # 8 用例：Docker secret（*_FILE）解析
│   └── test_weather_city.py          # 14 用例：天气城市抽取
├── logs/                     # 运行日志（自动生成）
├── app.py                    # Streamlit 网页入口
├── evaluate.py               # 效果评估脚本
├── docs/
│   └── architecture.svg     # 系统架构图（见「系统架构」一节）
├── .streamlit/
│   └── config.toml          # 前端主题 token（base/主色/隐藏工具栏与报错栈）
├── secrets/                 # Docker secret 文件（不进 git，见 Docker 部署）
└── requirements.txt
```

## 工作原理（一句话）

把"问题—答案"库里的每个问法切词后转成 TF-IDF 向量；用户提问也做同样处理，与库里所有问法算余弦相似度，取最像的一条返回对应答案。相似度低于阈值就兜底，不胡乱作答。

## 当前效果

在配套测试集（93 条可答 + 4 条应拒答，共 97 条，与语料物理隔离、人工改写）上：

| 指标 | 实测 | 目标 |
|------|------|------|
| 召回率@1 | 100% | ≥ 80% |
| Top-3 命中率 | 100% | ≥ 95% |
| 未识别率 | 0% | ≤ 10% |
| 误答率 | 0% | ≤ 5% |
| 误触发率 | 0% | ≤ 10% |

**⚠️ 诚实说明**：这个 100% 是「封闭测试集」的结果。真实用户问法远比测试集发散，上线后准确率必然下降。正确的做法不是死磕算法，而是靠运营闭环——定期导出 `logs/unmatched.jsonl` 里的未命中问题，补进语料。

## 怎么加新问答

编辑 `data/qa_corpus.json`，往 `intents` 里加一个对象：

```json
{
  "tag": "print_service",                 // 全局唯一，英文小写下划线
  "questions": [
    "哪里可以打印东西",
    "打印店在哪",
    "怎么打印文件",
    "学校打印贵不贵",
    "自助打印在哪里"
  ],
  "answer": "打印店位于学生服务中心 2 楼，黑白 0.2 元/页，彩色 1 元/页。",
  "source": "学生服务中心"
}
```

要点：

- **`questions` 至少 5 条**，覆盖口语、书面、省略、倒装等不同问法。这一条对准确率的贡献大于换更强的算法。
- 改完命令行里输入 `/reload` 即可生效，无需重启。
- 如果某个专业名词被 jieba 切碎了（例如"勤工助学"被切成"勤工/助学"），把它加进 `src/config.py` 的 `CUSTOM_WORDS`。

## 三个必踩的坑（已经替你趟过）

1. **索引与查询必须用同一套预处理**。早期版本索引用原始句子、查询用分词句子，两边词汇表对不上，相似度恒为 0 且不报错。现已把预处理内聚进 `Retriever`，从根上杜绝。
2. **通用疑问词会带偏匹配**。"怎么""哪里""多少钱"几乎每条问句都有，不去掉的话，"灯泡坏了找谁"会被"成绩单盖章找谁"抢走命中。它们已在 `stopwords.txt` 里过滤。
3. **TF-IDF 只认词面重叠**。"寝室灯泡坏了"和"宿舍灯坏了"这种同义词换用，TF-IDF 相似度就是 0。这是它的固有瓶颈，不是 bug——当语料已足够丰富、召回率仍卡在 70% 以下时，就该升级 BERT 向量化了（改 `config.VECTORIZER_TYPE`）。

## 升级路线

| 阶段 | 内容 | 状态 |
|------|------|------|
| v1 | TF-IDF + 命令行 + 网页 | ✅ |
| v3 | BGE-small-zh 句向量 + 真实通知语料（38 意图 / 311 问法） | ✅ |
| v4 | 大模型兜底 + 实时 API（DeepSeek + 和风天气） | ✅ |
| W2 | 安全层：PII 脱敏 / 注入检测 / 令牌桶限流 / 成本熔断 | ✅ |
| v7 | Docker 多阶段部署（CPU torch + BGE 预下载 + secret 注入） | ✅ |
| v7.1 | 前端去 AI 味：去侧边栏 / 高频问题 chip / 调试信息默认隐藏 | ✅ |
| v8 | Redis 共享限流/预算 · 天气 3d 预报 · 精排加固（bge-reranker-base + 独立阈值） | ✅ 当前 |

## v4 兜底增强：诚实的兜底 ≠ 硬拒答

之前 v3 的兜底只有一句固定话术。这有两个问题：
- 用户问"今天天气怎么样"明明有合理答案，却被硬拒答
- 但校园事务被拒答后让 LLM 自由发挥，又可能编造政策

v4 的解法是 **路由器分流**，按问题性质派给不同模块：

```
用户问题
   │
   ▼
BGE 检索 ──── 命中（≥ 0.60）───► FAQ 主路径
   │
   │ 未命中
   ▼
兜底路由器
   │
   ├─ 闲聊（你好/谢谢/你是谁） ──► 固定话术
   ├─ 实时（天气/校历/课表） ──► 和风天气 API / 固定兜底
   ├─ 校园事务（转专业/选课） ──► 固定话术（绝不让 LLM 编校务）
   └─ 通识（什么是/怎么学） ────► DeepSeek / 固定兜底
   │
   ▼
任何层失败 → 统一降级到 FALLBACK_TEXT
```

### 配置项（`src/config.py`）

```python
# 2026-09：FALLBACK_ROUTER_ENABLED / FALLBACK_MODE / FALLBACK_HUMAN_TEXT /
# SHOW_SUGGESTIONS 已随 _legacy_fallback 一起删除 —— 路由器是唯一的兜底入口，
# 不再有"副开关"。（原来的总开关写死 True、没有对应 env 变量，实际拨不动，
# 只是让旧分支常年不可达；旧分支里还有通义千问时代的死嗅探和假电话话术。）

# DeepSeek（兼容 OpenAI 协议，国内访问稳定、价格便宜）
DEEPSEEK_ENABLED = True
DEEPSEEK_API_KEY = ""                     # 留空走环境变量 DEEPSEEK_API_KEY
DEEPSEEK_MODEL = "deepseek-chat"          # 备选 deepseek-reasoner（R1，更慢但更强）
DEEPSEEK_SYSTEM_PROMPT = """...严守边界，严禁编造校务..."""

# 和风天气
HEFENG_ENABLED = True
HEFENG_API_KEY = ""                     # 留空走环境变量 HEFENG_API_KEY
HEFENG_CITY = "南京"
```

### 配置密钥（推荐方式）

```bash
# Linux / macOS
export DEEPSEEK_API_KEY=sk-xxx
export HEFENG_API_KEY=xxx

# Windows PowerShell
$env:DEEPSEEK_API_KEY = "sk-xxx"
$env:HEFENG_API_KEY = "xxx"
```

### 安全边界

| 风险 | 缓解 |
|---|---|
| LLM 编造校务 | 系统提示钉死 + 校园关键词拦截在 LLM 之前 |
| LLM 编造天气 | 天气永远走 API，不进 LLM |
| 成本失控 | `DEEPSEEK_TIMEOUT=8s` 超时降级 + W2.4 成本熔断 |
| API 密钥泄露 | `.env` 加载，不进 git；写入日志前 redact |
| LLM 异常 | 任何异常都降级到 `FALLBACK_TEXT`，不裸抛 |
| 用户在 query 里贴手机号 / 身份证 | W2.1 PII 脱敏，喂 LLM 前替换为 `[手机号]` |
| "忽略之前的指令"等攻击 | W2.2 Prompt injection 检测（高风险直接拒答） |
| 单 IP / 用户刷接口 | W2.3 令牌桶限流（IP 30/分钟，用户 60/分钟） |
| 月底被刷爆账单 | W2.4 滑动窗口成本熔断（默认 1h/500次/10元） |

### W2 安全层详解

**四道防线按顺序生效**（在 `agent.ask()` 入口处统一编排）：

```
用户提问
  ↓
1. injection 检测  ← 高风险直接拒答（如"忽略之前的指令"）
  ↓
2. 限流检查       ← IP / user_id 双维度令牌桶
  ↓
3. FAQ 检索
  ├─ 命中  → 返回知识库答案（不再走任何 LLM 路径，预算安全）
  └─ 未命中
       ↓
4. 预算熔断检查   ← 1h 窗口内调 LLM 不超 500 次 / 10 元
       ↓
5. PII 脱敏       ← 把 sanitized 版本喂给 LLM，原文返回给用户
       ↓
6. LLM 调用
```

**相关文件：**
- `src/security/redact.py`        —— PII 脱敏（手机号 / 身份证 / 邮箱 / 银行卡 / IP / URL）
- `src/security/injection.py`     —— Prompt injection 检测（角色劫持 / 提示词泄露 / 模型控制符）
- `src/security/rate_limit.py`    —— 令牌桶限流（IP + user_id 双维度）
- `src/security/budget.py`        —— 滑动窗口成本熔断
- `src/security/__init__.py`      —— `enforce_security()` 统一编排入口

**返回结构新增字段：**

```json
{
  "answer": "...",
  "matched": false,
  "fallback": {"type": "general", "source": "llm", "rule": "default_llm"},
  "security": {
    "reason": "",                      // 拒绝原因（无拒绝时为空）
    "pii_hits": ["手机号"],             // 命中的 PII 类型
    "injection_rules": []              // 命中的注入规则（仅日志）
  },
  ...
}
```

**测试覆盖**：

```bash
python -m pytest tests/test_security.py             # 36 用例：redact + injection
python -m pytest tests/test_rate_limit_budget.py    # 20 用例：限流 + 预算
python -m pytest tests/test_security_integration.py # 12 用例：端到端集成
```

**配置开关**（见 `src/config.py`）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `SECURITY_ENABLED` | True | 总开关（生产必须 True） |
| `REDACTION_ENABLED` | True | PII 脱敏开关 |
| `INJECTION_ENABLED` | True | Prompt injection 检测 |
| `RATE_LIMIT_IP_CAPACITY` | 30 | IP 桶容量（突发） |
| `RATE_LIMIT_IP_REFILL` | 0.5 | IP 桶每秒补充（稳态） |
| `BUDGET_WINDOW_SEC` | 3600 | 滑动窗口长度（秒） |
| `BUDGET_MAX_CALLS` | 500 | 窗口内最多 LLM 次数 |
| `BUDGET_MAX_COST_CNY` | 10.0 | 窗口内估算最大成本（元） |
| `FAQ_REDIS_URL` | （空） | 设了则限流/预算改走 Redis 共享计数（多 worker 精确） |

**注意**：限流 / 预算当前是**进程内 in-memory**，多 worker 时实际额度 ≈ NUM_WORKERS × 配置值。
如需精确限流（多实例部署），应改 Redis 或专业 API gateway（Kong / APISIX）。

### 测试

```bash
python tests/test_fallback.py
```

覆盖：分类正确性 / 降级路径 / 校园事务不进 LLM / 端到端。

### 扩展路由器

未来想加"我的课表""查成绩"等实时查询，只需在 `src/fallback/router.py` 的 `_answer_realtime()` 里加分支，并在 `REALTIME_KEYWORDS` 加关键词。**不要**让 LLM 直接编课表。

---

## Docker 部署

```bash
# 1. 准备密钥文件（不要带换行，chmod 400）
echo -n "sk-xxx"    > secrets/deepseek_key.txt
echo -n "your-key"  > secrets/hefeng_key.txt

# 2. 构建（首次约 10 分钟，主要花在 torch 196MB + BGE 模型 93MB）
docker build -t faq-bot:v7.0 .

# 3. 启动
docker compose up -d

# 4. 验证
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/ask \
     -H "Content-Type: application/json" \
     -d '{"query":"图书馆几点关门","user_id":"test"}'
```

镜像约 2.4GB（`python:3.11-slim` + CPU 版 torch + BGE 模型），启动后约 20 秒完成
BGE 加载（healthcheck 的 `start_period` 给了 60 秒）。交互式 API 文档：
<http://127.0.0.1:8000/docs>

### Docker 联调踩过的 4 个坑（2026-09-08 实测）

| # | 现象 | 根因 | 解法 |
|---|---|---|---|
| 1 | 装完 CPU 版 torch，装 `requirements.txt` 时又去拉 1GB 的 CUDA 包 | `pip install --prefix=/install` 装的包不在 `sys.path` 上，pip 认为 torch 没装，从主源重新解析（主源只有 CUDA 版） | 设 `ENV PYTHONPATH=/install/lib/python3.11/site-packages`，让 pip 看见已装的 `2.14.0+cpu` |
| 2 | `ResolutionImpossible` | 试过用 `-c constraints.txt` 钉死 `torch==2.14.0+cpu`，但主源里根本没有 `+cpu` 这种 local version 的候选 | 放弃 constraint，改用上面的 PYTHONPATH 方案 |
| 3 | `RUN python -c "..."` 换行续写报 `IndentationError` | Dockerfile 会保留行首空格 | 写成单行，或 COPY 一个 `.py` 进来跑 |
| 4 | 容器里 `/run/secrets/*` 挂载正常，却一直告警"KEY 未配置" | `config.py` 里 `_load_secret` 有**两处**定义（一处 `def` + 一处别名赋值），后面的 `def` 把带 `_FILE` 支持的版本覆盖掉了 | 只保留一处定义（见 `tests/test_secret_loading.py` 的防回归断言） |

### 和风天气 Host 配置（最容易搞错）

- 自定义域名前缀是**控制台分配**的（形如 `mc3byj5bbc`），**不是** API key 的前 8 位。
  填错时不会返回和风标准的 `problem+json`，而是「`Content-Length: 0` 的裸 403」，
  极易误判成网络问题。判断办法：**不带 key 直接请求**，若同样裸 403，就是 host 错了。
- 自定义域名下天气和城市查询**共用同一个 host**，只有 path 不同：
  - `weather` → `{BASE_URL}/v7/weather/now`
  - `geo` → `{BASE_URL}/geo/v2/city/lookup`
  代码里 geo 拼的是 `{HEFENG_GEO_URL}/v2/city/lookup`，所以 `HEFENG_GEO_URL`
  必须写成 `...re.qweatherapi.com/geo`（带 `/geo`）。只有用官方 devapi 的账号
  才写 `https://geoapi.qweather.com`。

### 已知限制

- **限流/预算默认仍是进程内计数**：未配置 Redis 时额度 ≈ worker 数 × 配置值
  （实测 80 并发放行 52 次 ≈ 2×30）。2026-09 起支持 Redis 共享计数：设
  `FAQ_REDIS_URL` 即启用（`docker-compose.yml` 里有注释掉的 redis 服务），
  Redis 连不上时自动退回进程内实现，不会因此拒服务。
- **天气支持实况 + 3 天预报**：问句带「明天/后天」走 `/v7/weather/3d`（免费额度内）；
  「周末」「下周」等更远的日期暂不支持，会回落到实况。
- 镜像偏大（2.4GB），如需瘦身可考虑 `--no-compile` 装 torch、或把 BGE 换 TF-IDF。

---

## 前端界面

```bash
uvicorn api:app --port 8000          # 后端
streamlit run app.py                 # 前端（默认 8501）
```

### 去 AI 味的三条原则（v7.1 改版）

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

### 调试模式

排查问题时在启动前端的终端里设 `FAQ_DEBUG=1`（PowerShell：`$env:FAQ_DEBUG="1"` 后再 `streamlit run app.py`），
才显示 `trace_id`、相似度、候选题列表、向量化方式、API 地址。
**默认一律不显示**。2026-09 修复：调试开关从 URL 参数 `?debug=1` 改为环境变量——
URL 参数任何访客都能加，等于无鉴权泄露内部信息；`tests/test_ui.py` 里有断言钉死这点。

### 主题与样式

- 主题 token：`.streamlit/config.toml`（改完**必须重启** streamlit，不支持热更新）
- CSS 覆盖：`src/ui_style.py`（去掉顶部彩虹条、页脚、彩色气泡、过重描边）

!! **主色写在两处，改色时必须同步**：
`config.toml` 的 `primaryColor` 管 Streamlit 原生组件，`src/ui_style.py` 的 `PRIMARY` 管自定义 CSS。
config.toml 读不到 Python 变量，只能手工保持一致。

样式代码放 `src/` 而不是项目根目录，是因为 Dockerfile 只 COPY `api.py / app.py / src/ / data/`，
根目录新建 .py 不会进镜像，容器里 import 会炸。
