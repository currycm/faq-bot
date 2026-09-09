# 部署到 Hugging Face Spaces（可照抄清单）

> 目标：让面试官点开一个公网链接就能直接试用你的校园问答机器人。
> 预计耗时：第一次约 15–30 分钟（含模型首次下载）。之后改代码推一下就更新。

---

## ⚠️ 部署前必读：一个架构前提

当前 `app.py` 是**纯前端**，本地靠 HTTP 调用独立的 FastAPI 后端
（`FAQ_API_BASE`，默认 `http://127.0.0.1:8000`）。

**Hugging Face Spaces 的 Streamlit 模式只能跑单个进程**，不能同时起前端 + 后端。
所以直接传现在的代码上去，前端会连不上后端而白屏。

**两种解决路线（任选其一）：**

| 路线 | 改动 | 复杂度 | 说明 |
|------|------|--------|------|
| **A. 让 app.py 自包含（推荐）** | 改 1 个文件 | 低 | 无 `FAQ_API_BASE` 时进程内直接调 `FaqBot`；本地有后端仍走 HTTP。改完只需**一个** Space |
| **B. 前后端分开部署（不改代码）** | 0 改动 | 中 | 后端部署到 Railway/Render 拿 URL，前端 Space 设 `FAQ_API_BASE` 指过去。需**两个**服务 |

下面清单按 **路线 A（推荐）** 写。路线 B 见文末。

---

## 路线 A：单 Space 自包含部署

### 第 0 步：让 app.py 支持"无后端"模式（需改代码，改动很小）
请在 `app.py` 中加一段"进程内兜底"：当环境变量 `FAQ_API_BASE` 未设置时，
直接 `from src.agent import FaqBot` 在进程内回答问题，而不是发 HTTP 请求。
本地若设了 `FAQ_API_BASE` 则行为不变（仍走后端）。

> 这一步需要动 `app.py`。要不要我直接帮你改好并本地验证？改完这份清单就能一字不差照抄。

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
cd "C:/Users/24830/Desktop/问答机器/faq-bot"

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
