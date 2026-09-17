# 部署在线 Demo

> 目标：让面试官点开一个公网链接就能直接试用。

---

## ✅ 首选：沙箱直接发布（已实操，2026-09-15）

**现状**：已发布在 **<https://campus-faq-bot.app.workbuddy.host/>**（HTTP 200，
`/_stcore/health` 返回 `ok`）。选它而不是 HF Spaces 的理由：**国内可直接访问**，
而且不需要任何账号或凭据。

发布参数（复现/重发时照抄）：

| 项 | 值 |
|---|---|
| 目录 | 项目根目录 |
| 语言 | `python` |
| 安装命令 | `pip install -r requirements-deploy.txt` |
| 启动命令 | `python -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true --server.enableCORS false --server.enableXsrfProtection false --browser.gatherUsageStats false` |
| 端口 | `8501` |

### ⚠️ 发布前检查（每一条都真踩过，2026-09-15）

1. **把 `.env` 移出项目目录**。发布是**上传整个目录**，而 `.env` 里有真实的
   `DEEPSEEK_API_KEY` / `HEFENG_API_KEY` —— 只改名成 `.env.deploy-bak` **不管用**
   （照样在目录里），必须移到项目目录**之外**。发布完再移回来，并 grep 一遍确认没残留。
2. **端口写字面值**。`--server.port $PORT` 不展开时会报
   `service did not become reachable within 60s`；写死 `8501` 就对了。
3. **`.env.example` 里不留 `redis://...` 字面连接串**。平台据此判定
   "本项目需要外部 Redis 服务"并**直接拒绝发布**（本项目 Redis 本就是可选的）。
4. **随包模型不能放在 `.gitignore` 里**：部署**按 `.gitignore` 排除上传内容**。
   本次把 92MB 的 `models/` 加进 `.gitignore` 想"不进 git"，结果连上传也被排除了。
   正解是写进 **`.git/info/exclude`**（只对本地生效、不进仓库）——git 保持干净，
   部署却能拿到它。
5. **发布依赖用 `requirements-deploy.txt`**：torch 锁 CPU 版（默认会拉 CUDA 版 2GB+），
   不带 gunicorn/fastapi/redis（单进程 Streamlit 用不上）。

---

## 🔧 故障排查：发布成功但一问就「服务暂时不可用」

**这是最坑的一种失败**：平台返回 `verified: true`、页面也渲染正常（标题、标签页都在），
但一提问就显示「服务暂时不可用」。

**原因**：`app.py` 里 `FaqBot` 是**懒加载**的（`@st.cache_resource`），
所以依赖缺失 / 模型加载失败**都不会**让进程崩 —— 只在第一次请求时抛异常，
被 UI 兜成一句通用提示。**"服务可达" ≠ "能用"**。

**排查顺序**（每一步都对应一个已修的坑）：

| 现象 | 根因 | 修法 |
|---|---|---|
| 页面正常，一问就报错 | 机器人懒加载，失败被 UI 吞掉 | **把初始化挪到构建期**：`scripts/prefetch_model.py` 放进 `installCmd`，失败会在**构建日志**里直接暴露 |
| 构建报 `does not appear to have a file named model.safetensors` | 1️⃣ 构建环境**连不上 hf-mirror**，模型下不下来<br>2️⃣ 且 `config.py` 的离线判定**只看快照目录存在与否** —— 一次失败留下的空目录会让它永久判定"已缓存、别联网"，把后续重试全堵死 | 已修 `config.py`：改为**必须存在权重文件**才算命中，并显式 `pop` 掉外部预设的 `HF_HUB_OFFLINE`；同时把模型**随包带上** |
| 随包了模型却仍走联网 | `scripts/prefetch_model.py` 误用 `BGE_MODEL_NAME`（HF 编号）而非 `BGE_MODEL_PATH`（本地路径）——**本地有 HF 缓存所以看不出来**，一到干净环境就暴露 | 已修：用 `BGE_MODEL_PATH`；`src/vectorizer.py` 同样改为优先本地目录 |
| 诊断信息看不到 | 构建日志只保留尾部若干行，单独 `print` 的诊断被截掉 | 把诊断（本地目录是否存在、目录内文件、权重字节数）**拼进失败那一行本身** |

**发布后一定要真的问一句**：`scripts/` 之外还有个一次性校验脚本（无头浏览器打开线上地址、
提问、读回答）。仅看 HTTP 200 或健康检查**不足以**说明能用 —— 本次就是"可达但坏着"。
注意 playwright 与本机 chromium 版本不匹配，要 `executable_path` 直指
`ms-playwright/chromium-1223/chrome-win64/chrome.exe`。

---

## 备选：Hugging Face Spaces

需要你的 HF 账号 + write token（沙箱无凭据，push 只能本机做）。
**注意国内访问常常打不开**，所以放在备选。


> 目标：让面试官点开一个公网链接就能直接试用你的校园问答机器人。
> 预计耗时：第一次约 15–30 分钟（含模型首次下载）。之后改代码推一下就更新。

---

## ⚠️ 部署前必读：一个架构前提

当前 `app.py` 是**纯前端**，本地靠 HTTP 调用独立的 FastAPI 后端
（`FAQ_API_BASE`，默认 `http://127.0.0.1:8000`）。

**Hugging Face Spaces 的 Streamlit 模式只能跑单个进程**，不能同时起前端 + 后端。

**两种解决路线（任选其一）：**

| 路线 | 改动 | 复杂度 | 说明 |
|------|------|--------|------|
| **A. 让 app.py 自包含（已默认启用 ✅，2026-09-15 实测通过）** | 已改好 | 低 | `FAQ_API_BASE` 未设置时进程内直接调 `FaqBot`；设了仍走 HTTP。只需**一个** Space |
| **B. 前后端分开部署（不改代码）** | 0 改动 | 中 | 后端部署到 Railway/Render 拿 URL，前端 Space 设 `FAQ_API_BASE` 指过去。需**两个**服务 |

下面清单按 **路线 A** 写（已默认生效，无需额外改代码）。

---

## 路线 A：单 Space 自包含部署

> ✅ **`app.py` 已支持无后端模式**：不设置 `FAQ_API_BASE` 时自动在进程内运行 `FaqBot`，
> 本地设了 `FAQ_API_BASE` 则照常走后端。所以直接按下面步骤部署即可，不用再改代码。

### 第 1 步：准备仓库文件
确认以下都在 git 里（它们已经在仓库中了）：
- `app.py` ✅
- `requirements.txt` ✅（HF 会自动 `pip install`）
- `src/` 整个目录 ✅
- `data/qa_corpus.json` ✅（语料，必带）

> **torch 体积提示**：`requirements.txt` 里 `torch` 是注释掉的，靠 `sentence-transformers`
> 自动拉取——默认会拉 **CUDA 版（约 800MB）**，在 HF 上构建偏慢。
> 稳妥起见，给 Space 单独放一个 `requirements.txt` 把 torch 锁成 CPU 版：
> ```
> torch --index-url https://download.pytorch.org/whl/cpu
> sentence-transformers
> streamlit
> jieba
> scikit-learn
> python-dotenv
> ```
> （若保留仓库原 `requirements.txt`，只是构建慢一点，也能跑。）

### 第 2 步：在 Hugging Face 上建 Space
1. 登录 https://huggingface.co （用 GitHub 账号授权最快）
2. 右上角 **＋ New** → **Space**
3. 填：
   - **Name**：`faq-bot`（或 `campus-faq-bot`）
   - **SDK**：选 **Streamlit**
   - **Visibility**：**Public**（面试官能直接打开）
4. 点 **Create Space**
5. 页面会给你一个 git 地址，形如：
   ```
   https://huggingface.co/spaces/<你的HF用户名>/faq-bot
   ```

### 第 3 步：把代码推上去
在你的**本机终端**（能连外网的环境）执行：

```bash
# 进入项目目录
cd "C:/Users/24830/Desktop/智答校园/faq-bot"

# 添加 HF Space 为远程（用你第 2 步拿到的地址）
git remote add space https://huggingface.co/spaces/<你的HF用户名>/faq-bot

# 推送。用户名=你的 HF 用户名，密码=HF 的 Access Token（需 write 权限）
# Token 在 https://huggingface.co/settings/tokens 生成
git push space master
```

> 推送时会要求登录：用户名填 HF 用户名，密码填 **HF Access Token**（不是账号密码）。

### 第 4 步（可选）：配置密钥 Secrets
机器人默认**不配密钥也能跑**（LLM 兜底 / 天气失败会优雅降级成固定话术）。
若想让"问天气""问通识"也生效，在 Space 页面的 **Settings → Variables and secrets**
里加两个环境变量（Secret 类型）：
- `QWEATHER_KEY` = 和风天气 API Key
- `DEEPSEEK_API_KEY` = DeepSeek API Key

### 第 5 步：等构建完成，拿到链接
- Space 页面会自动 `streamlit run app.py` 并构建（首次要下载 BGE 模型 ~93MB，稍等）。
- 构建完页面顶部的 **App** 标签就是公网地址，复制它填进 README 的「在线体验」。

---

## 路线 B：前后端分离（不改一行代码）

1. **后端**部署到 Railway（https://railway.app）：
   - New Project → Deploy from GitHub repo
   - Start Command 填：`uvicorn api:app --host 0.0.0.0 --port $PORT`
   - 拿到后端 URL，如 `https://faq-bot-api.up.railway.app`
2. **前端**按上面第 2–5 步建 Streamlit Space，但在第 4 步的 Secrets 里加：
   - `FAQ_API_BASE` = `https://faq-bot-api.up.railway.app`
3. 前端 Space 启动时读到 `FAQ_API_BASE`，就会走 HTTP 调你的后端。

> 优点：零代码改动。缺点：要维护两个服务、两个可能过期的免费实例。

---

## 部署后别忘了
1. 把 Space 的公网链接填进 `README.md` 顶部「🔗 在线体验」那一行，然后 `git push`。
2. 补 3 张截图（问 FAQ / 问天气 / 被安全拦截），替换 README 顶部占位格。
3. 在简历里写：*「已部署公网 Demo（Hugging Face Spaces），可在线试用」*。
