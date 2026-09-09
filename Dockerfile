# faq-bot Dockerfile（多阶段构建）
#
# 阶段 1（builder）：装依赖 + 预下载 BGE 模型
# 阶段 2（runtime）：只复制必要文件 + 非 root 运行
#
# 构建：
#   docker build -t faq-bot:v7.0 .
#
# 运行（推荐用 docker-compose.yml）：
#   docker compose up -d
#
# 健康检查：
#   curl http://127.0.0.1:8000/health

# ============================================================
# 阶段 1：builder
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /build

# 装构建工具（BGE 模型依赖里有 torch 等大包）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖清单（单独 COPY 利用 Docker 缓存：requirements.txt 不变就不重装）
COPY requirements.txt .

# 换清华镜像源（国内沙箱/Docker 默认拉 pypi 经常超时）
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn

# ---------------------------------------------------------------------------
# 关键：torch 单独一层装，且装 CPU 版
#
# 为什么这么拆：
#   1. 默认的 torch wheel 带 CUDA 支持，554MB —— 国内网络下载极易超时断连
#   2. 本项目是 CPU 推理（BGE_DEVICE=cpu），CUDA 完全是浪费
#   3. 单独一层 = torch 装失败重跑时，前面的轻量依赖层全部命中缓存
#
# CPU 版体积约 200MB，比 CUDA 版小 64%
#
# 源的选择（2026-09 实测，用 pip index versions torch 验证过）：
#   download.pytorch.org/whl/cpu/   → torch 2.14.0+cpu  ✅ 用这个（标准 PEP503 index）
#   清华 pypi 主源                   → 只有 2.14.0（CUDA 版，554MB，太大）
#   清华 mirrors/.../pytorch-wheels  → 404（已失效）
#   阿里云 mirrors/.../pytorch-wheels → HTTP 200 但是 HTML 目录页，pip 解析不了
#
# 判断技巧：用 pip index versions torch --index-url <源> 验证，
#           能列出 "x.y.z+cpu" 的才是真能用的 CPU 源。
# ---------------------------------------------------------------------------
RUN pip install --no-cache-dir --prefix=/install \
        --timeout=180 --retries=8 \
        torch --index-url https://download.pytorch.org/whl/cpu/

# ---------------------------------------------------------------------------
# 让 pip / python 能看见「装在 /install 下」的包
#
# !! 坑（踩了两轮，务必看懂再改）：
#    pip install --prefix=/install 装出来的包在 /install/lib/pythonX.Y/site-packages，
#    这个目录默认**不在 sys.path 上**。于是后面 pip 装 requirements.txt 时：
#      · pip 以为「torch 没装」→ 从主源重新解析 → 主源只有 CUDA 版
#      · 连带拉 nvidia-cudnn-cu13(553MB) + cuda-toolkit ≈ 1GB，前功尽弃
#    试过 -c constraints.txt 钉死 torch==2.14.0+cpu，结果直接
#    ResolutionImpossible（主源里根本没有 +cpu 这个 local version 的候选）。
#
# 正解：把 /install 的 site-packages 挂到 PYTHONPATH 上，pip 解析时发现
#       「torch 2.14.0+cpu 已安装且满足 torch>=2.2」→ 不再重装。
# ---------------------------------------------------------------------------
ENV PYTHONPATH=/install/lib/python3.11/site-packages

# 失败早退：确认 torch 装的是 CPU 版且能被 import
RUN python -c "import torch; \
    assert torch.__version__.endswith('+cpu'), torch.__version__; \
    print('[builder] torch', torch.__version__, 'OK')"

# 其余依赖（fastapi / jieba / scikit-learn / sentence-transformers ...）
#
# streamlit 是本地网页调试用的，API 镜像不需要，且会拖进 pandas+pyarrow
# （多 ~200MB、多几分钟下载），Docker 里用 grep 过滤掉。
RUN grep -vE '^\s*streamlit\s*(>=|==|$)' requirements.txt > /tmp/req-docker.txt && \
    pip install --no-cache-dir --prefix=/install \
        --timeout=180 --retries=8 \
        -r /tmp/req-docker.txt

# 预下载 BGE 模型到缓存，构建阶段联网，运行时离线
# !! 关键：这一步必须在构建时跑，否则容器无网会卡死
# !! 坑：RUN python -c "..." 千万别用 \ 换行 + 缩进续写，
#     Dockerfile 会把行首空格原样保留，Python 直接 IndentationError。
#     要么写成单行，要么 COPY 一个 .py 文件进来跑。
ENV HF_ENDPOINT=https://hf-mirror.com
ENV HF_HOME=/root/.cache/huggingface
RUN python -c "from sentence_transformers import SentenceTransformer; m = SentenceTransformer('BAAI/bge-small-zh-v1.5'); print('[builder] BGE 预下载完成:', m.get_sentence_embedding_dimension(), 'dim')"

# ============================================================
# 阶段 2：runtime
# ============================================================
FROM python:3.11-slim AS runtime

# 非 root 用户（容器逃逸后无法获得主机权限）
RUN useradd -m -u 1000 -s /bin/bash app

WORKDIR /app

# 从 builder 复制依赖（不是 site-packages，是 --prefix=/install）
COPY --from=builder /install /usr/local

# 从 builder 复制预下载的模型缓存
COPY --from=builder /root/.cache/huggingface /home/app/.cache/huggingface

# 复制代码
COPY --chown=app:app api.py /app/
COPY --chown=app:app app.py /app/
COPY --chown=app:app src/ /app/src/
COPY --chown=app:app data/ /app/data/

# 模型缓存目录归属 app 用户
RUN chown -R app:app /home/app/.cache

# 切换到非 root 用户
USER app

# 强制 HuggingFace 离线（模型已预下载，容器运行时不应联网）
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

EXPOSE 8000

# 健康检查：每 30 秒 GET /health，3 次失败视为不健康
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; \
        urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()" \
    || exit 1

# 启动命令：Gunicorn + Uvicorn worker × 2
# !! 注意：BGE 模型每个 worker 进程都会加载一次（~400MB 内存/进程）
#    4 核 8GB 服务器建议 -w 2；8 核 16GB 可以 -w 4
CMD ["gunicorn", "api:app", \
     "-w", "2", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-b", "0.0.0.0:8000", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--timeout", "60", \
     "--graceful-timeout", "30"]