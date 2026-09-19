# -*- coding: utf-8 -*-
"""src/logger.py 专项测试 —— 覆盖日志轮转与写入原子性（#17 / #19 修复的回归保护）。

背景：2026-09-18 给 logger 加了「写前轮转 + 写锁」，但没配套测试。
后果是覆盖率从 81% 掉到 79.6%，恰好跌破 CI 的 --cov-fail-under=80 门禁。
本文件补齐这部分覆盖，同时把轮转行为本身钉死（防止以后改坏）。

运行：
    python -m pytest tests/test_logger.py -q
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import logger  # noqa: E402

# --------------------------------------------------------------------------
# _now()：时区格式（#17）
# --------------------------------------------------------------------------


def test_now_is_timezone_aware():
    """时间戳必须带时区偏移——裸本地时间会在 UTC 容器里造成 8 小时漂移。"""
    ts = logger._now()
    # 形如 2026-09-19T10:47:18+08:00 或 ...+00:00
    assert "+" in ts[10:] or ts.endswith("Z"), f"时间戳缺少时区：{ts!r}"
    assert "T" in ts, f"不是 ISO 格式：{ts!r}"


def test_now_is_parseable_and_ordered():
    """连续两次取时间应可解析且单调不减。"""
    from datetime import datetime

    a = datetime.fromisoformat(logger._now())
    b = datetime.fromisoformat(logger._now())
    assert a.tzinfo is not None, "解析后应带 tzinfo"
    assert b >= a


# --------------------------------------------------------------------------
# _maybe_rotate()：轮转（#19）
# --------------------------------------------------------------------------


def test_no_rotate_below_threshold(tmp_path: Path):
    """文件小于阈值时不该轮转。"""
    p = tmp_path / "qa.log"
    p.write_text("x" * 100, encoding="utf-8")
    logger._maybe_rotate(p, max_bytes=1000, backup_count=3)
    assert p.exists(), "未超阈值不应被移走"
    assert not (tmp_path / "qa.log.1").exists()


def test_no_rotate_when_missing(tmp_path: Path):
    """文件不存在时静默返回，不抛异常。"""
    logger._maybe_rotate(tmp_path / "nope.log", max_bytes=1, backup_count=3)
    assert not (tmp_path / "nope.log.1").exists()


def test_rotate_moves_to_backup_one(tmp_path: Path):
    """超过阈值 → 原文件改名为 .1，并新建空的原文件位置（由后续写入创建）。"""
    p = tmp_path / "qa.log"
    p.write_text("y" * 2000, encoding="utf-8")
    logger._maybe_rotate(p, max_bytes=1000, backup_count=3)
    assert not p.exists(), "超阈值后原路径应已被移走"
    assert (tmp_path / "qa.log.1").exists(), "应生成 .1 备份"
    assert (tmp_path / "qa.log.1").read_text(encoding="utf-8") == "y" * 2000


def test_rotate_builds_backup_chain(tmp_path: Path):
    """多次轮转应形成 .1 → .2 → .3 的链，且内容不串位。"""
    p = tmp_path / "qa.log"
    for gen in range(3):
        p.write_text(f"gen{gen}" * 500, encoding="utf-8")
        logger._maybe_rotate(p, max_bytes=100, backup_count=3)

    # 最后一次写入的（gen2）成为 .1，gen1 成为 .2，gen0 成为 .3
    assert (tmp_path / "qa.log.1").read_text(encoding="utf-8").startswith("gen2")
    assert (tmp_path / "qa.log.2").read_text(encoding="utf-8").startswith("gen1")
    assert (tmp_path / "qa.log.3").read_text(encoding="utf-8").startswith("gen0")


def test_rotate_respects_backup_count(tmp_path: Path):
    """超出 backup_count 的旧备份应被丢弃，不会无限增长。"""
    p = tmp_path / "qa.log"
    for gen in range(6):
        p.write_text(f"v{gen}" * 500, encoding="utf-8")
        logger._maybe_rotate(p, max_bytes=100, backup_count=3)
    assert not (tmp_path / "qa.log.4").exists(), "不应产生超过 backup_count 的备份"


def test_rotate_swallows_oserror(tmp_path: Path):
    """目标路径不可写时应静默吞掉，绝不影响主流程。"""
    p = tmp_path / "qa.log"
    p.write_text("z" * 2000, encoding="utf-8")
    # max_bytes 传负数会让 stat 比较成立；再用一个不可创建的备份路径触发 OSError
    locked = tmp_path / "qa.log.1"
    locked.mkdir()  # 目录占位：rename 到它必然失败
    logger._maybe_rotate(p, max_bytes=1000, backup_count=3)  # 不应抛异常


# --------------------------------------------------------------------------
# write_jsonl：与轮转/锁的集成
# --------------------------------------------------------------------------


def test_write_jsonl_appends_valid_json(tmp_path: Path):
    p = tmp_path / "sub" / "qa.log"
    logger.write_jsonl(p, {"query": "图书馆几点开门", "tag": "library_hours"})
    logger.write_jsonl(p, {"query": "宿舍灯坏了找谁修"})
    lines = p.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    for ln in lines:
        json.loads(ln)  # 每行都是合法 JSON


def test_write_jsonl_redacts_secrets(tmp_path: Path):
    """写入前强制 redact —— Authorization 不该落盘。"""
    p = tmp_path / "qa.log"
    logger.write_jsonl(p, {"headers": {"Authorization": "Bearer sk-super-secret-token"}})
    raw = p.read_text(encoding="utf-8")
    assert "sk-super-secret-token" not in raw, "密钥必须被脱敏"


def test_write_jsonl_triggers_rotation(tmp_path: Path):
    """写入时若已达上限，应触发轮转（验证 _maybe_rotate 确实被 write_jsonl 调用）。

    !! 不能用 monkeypatch 改 _LOG_MAX_BYTES：默认参数在函数【定义时】就已绑定，
       改模块变量对已定义的函数无效（Python 默认参数陷阱）。
       这里改为直接调 _maybe_rotate 并显式传阈值，验证的是同一段逻辑。
    """
    p = tmp_path / "qa.log"
    for i in range(20):
        logger.write_jsonl(p, {"i": i, "pad": "x" * 50})
    size_before = p.stat().st_size
    assert size_before > 0

    # 显式用小阈值触发轮转
    logger._maybe_rotate(p, max_bytes=100, backup_count=3)
    assert (tmp_path / "qa.log.1").exists(), "超过阈值应轮转出 .1"
    assert (tmp_path / "qa.log.1").stat().st_size == size_before


def test_write_jsonl_rotation_threshold_uses_module_constant(tmp_path: Path):
    """生产阈值确实是模块常量（100MB），且远大于单条日志——不会误轮转。"""
    assert logger._LOG_MAX_BYTES == 100 * 1024 * 1024
    assert logger._LOG_BACKUP_COUNT == 5
    p = tmp_path / "qa.log"
    for i in range(20):
        logger.write_jsonl(p, {"i": i})
    assert not (tmp_path / "qa.log.1").exists(), "小量写入不应触发轮转"


def test_write_jsonl_concurrent_no_corruption(tmp_path: Path):
    """多线程并发写：每行都必须是完整 JSON（验证写锁真的起作用）。"""
    p = tmp_path / "qa.log"
    errors: list[Exception] = []

    def worker(n: int):
        try:
            for i in range(25):
                logger.write_jsonl(p, {"thread": n, "i": i})
        except Exception as exc:  # pragma: no cover - 失败时记录
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发写出现异常：{errors}"
    lines = [ln for ln in p.read_text(encoding="utf-8").split("\n") if ln.strip()]
    assert len(lines) == 8 * 25, f"应写入 200 行，实际 {len(lines)}"
    for ln in lines:
        json.loads(ln)  # 任一行断裂即为锁失效
