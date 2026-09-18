# -*- coding: utf-8 -*-
"""构建期预取 BGE 模型 —— 让「模型下载」从运行时挪到构建时。

为什么需要它
--------------------------------------------------------------------------
沙箱/云托管首次发布时踩过一个坑：**Streamlit 起来了、页面渲染正常，但一问就显示
「服务暂时不可用」**。原因是 app.py 里 FaqBot 是**懒加载**的（`@st.cache_resource`），
所以依赖缺失或模型下载失败都**不会**让进程崩，只会在第一次请求时抛异常，
被 UI 兜成一句通用错误 —— **线上完全看不出真实原因**。

把预取放进安装命令后，同一个失败会**在构建阶段直接报错**，日志里能看到
到底是 pip 装不上、import 失败，还是模型下不下来。

顺带的好处：模型进入构建缓存，**运行时不碰网络**，首屏更快也更稳。

用法（部署时的 installCmd）：
    pip install -r requirements-deploy.txt && python scripts/prefetch_model.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 先导入 config：HF_ENDPOINT（镜像）与 HF_HUB_OFFLINE（离线模式）都在
# config 的 import 阶段设置好，顺序反了会走到默认的 huggingface.co，
# 在受限网络下会卡住。这一步与运行时行为保持一致。
from src import config  # noqa: E402


def main() -> int:
    import os

    name = config.BGE_MODEL_NAME
    print(f"[prefetch] 目标模型：{name}")
    # 关键诊断行：随包模型是否被上传、代码是否真的选用了它。
    # 曾经踩过：把 models/ 加进 .gitignore 后，托管平台把该目录一起排除在上传之外，
    # 于是"本地明明有模型、构建时却加载不到"。
    print(f"[prefetch] 本地目录={config.BGE_LOCAL_DIR} ｜ 存在={config.BGE_LOCAL_DIR.is_dir()}")
    print(f"[prefetch] 实际使用={config.BGE_MODEL_PATH}")
    # HF_ENDPOINT / HF_HUB_OFFLINE 都是 config 在 import 阶段塞进 os.environ 的，
    # 所以这里读环境变量而不是读 config 属性（config 里那个常量叫 HF_MIRROR）。
    print(
        f"[prefetch] HF_ENDPOINT={os.environ.get('HF_ENDPOINT', '(unset)')} "
        f"HF_HUB_OFFLINE={os.environ.get('HF_HUB_OFFLINE', '(unset)')}"
    )

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        print(f"[prefetch] ✗ sentence-transformers 导入失败：{exc}", file=sys.stderr)
        return 2

    try:
        # !! 必须用 BGE_MODEL_PATH（不是 BGE_MODEL_NAME）：前者在随包了本地模型时
        #    指向 models/<模型名>/，后者永远是 HF 编号、会去联网下载。
        #    这里曾经写成 NAME —— 本地有 HF 缓存所以"看起来没问题"，
        #    一到受限网络的构建环境就暴露成"下载失败"。
        model = SentenceTransformer(config.BGE_MODEL_PATH, device="cpu")
    except Exception as exc:
        # 诊断信息写进**这一行**：构建日志通常只保留尾部若干行，
        # 单独 print 的诊断会被截掉，只有失败行本身能确保被看到。
        # 另外把目录内容也列出来 —— 用于判断"目录传上来了但大文件被丢弃"这类情况。
        try:
            import os as _os

            _files = sorted(_os.listdir(config.BGE_LOCAL_DIR)) if config.BGE_LOCAL_DIR.is_dir() else []
            _w = config.BGE_LOCAL_DIR / "model.safetensors"
            _wsize = _w.stat().st_size if _w.exists() else -1
            _info = f"目录内={_files} ｜ 权重字节={_wsize}"
        except Exception as _e:  # 诊断失败不能掩盖原始错误
            _info = f"(列目录失败：{_e})"
        print(
            f"[prefetch] ✗ 模型加载失败 ｜ 本地目录存在={config.BGE_LOCAL_DIR.is_dir()} "
            f"｜ 使用路径={config.BGE_MODEL_PATH} ｜ {_info} "
            f"｜ {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 3

    dim = model.get_sentence_embedding_dimension()
    if not dim or dim <= 0:
        print(f"[prefetch] ✗ 拿不到向量维度：{dim}", file=sys.stderr)
        return 4

    print(f"[prefetch] ✓ 就绪：dim={dim}，运行时可离线")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
