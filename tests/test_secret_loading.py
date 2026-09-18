# -*- coding: utf-8 -*-
"""密钥加载（Docker secret / 环境变量）回归测试

背景（2026-09-08 Docker 联调踩坑）：
    config.py 里曾经「先定义 _resolve_secret，再 _load_secret = _resolve_secret」，
    结果被文件下方另一个 `def _load_secret` 覆盖回只读环境变量的旧实现，
    Docker secret（*_FILE）完全失效，容器里 secret 挂好了却一直告警 KEY 未配置。

这组测试就是钉死这个行为：只要有人再把 _FILE 分支弄丢，红灯立刻亮。
"""

from __future__ import annotations

import os

import pytest

from src import config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每个用例前清掉可能干扰的环境变量，避免本地 .env / shell 污染。"""
    for name in ("FAKBOT_TEST_KEY", "FAKBOT_TEST_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    yield


def test_direct_env_var_wins():
    """风格 A：直接环境变量优先。"""
    os.environ["FAKBOT_TEST_KEY"] = "sk-from-env"
    assert config._load_secret("FAKBOT_TEST_KEY") == "sk-from-env"


def test_direct_env_var_takes_priority_over_file(tmp_path, monkeypatch):
    """同时给了环境变量和 _FILE 时，环境变量优先（方便线上临时覆盖）。"""
    key_file = tmp_path / "key.txt"
    key_file.write_text("sk-from-file", encoding="utf-8")
    monkeypatch.setenv("FAKBOT_TEST_KEY_FILE", str(key_file))
    os.environ["FAKBOT_TEST_KEY"] = "sk-from-env"

    assert config._load_secret("FAKBOT_TEST_KEY") == "sk-from-env"


def test_file_secret_is_read(tmp_path, monkeypatch):
    """风格 B：Docker secret 走 _FILE，读文件内容。"""
    key_file = tmp_path / "deepseek_key"
    key_file.write_text("sk-from-file", encoding="utf-8")
    monkeypatch.setenv("FAKBOT_TEST_KEY_FILE", str(key_file))

    assert config._load_secret("FAKBOT_TEST_KEY") == "sk-from-file"


def test_file_secret_strips_surrounding_whitespace(tmp_path, monkeypatch):
    """echo "sk-xxx" > secret.txt 会带换行，读取时必须 strip，否则鉴权 401。"""
    key_file = tmp_path / "key.txt"
    key_file.write_text("  sk-with-newline \n", encoding="utf-8")
    monkeypatch.setenv("FAKBOT_TEST_KEY_FILE", str(key_file))

    assert config._load_secret("FAKBOT_TEST_KEY") == "sk-with-newline"


def test_missing_file_falls_back_to_empty(monkeypatch):
    """_FILE 指向不存在的路径：不能抛异常，降级为空串（否则启动直接崩）。"""
    monkeypatch.setenv("FAKBOT_TEST_KEY_FILE", "/run/secrets/does-not-exist")
    assert config._load_secret("FAKBOT_TEST_KEY") == ""


def test_nothing_configured_returns_empty():
    """什么都没配 → 空串，功能降级到固定话术。"""
    assert config._load_secret("FAKBOT_TEST_KEY") == ""


def test_blank_env_var_is_treated_as_missing(tmp_path, monkeypatch):
    """环境变量是空串/纯空格时，应继续尝试 _FILE，而不是提前返回空。"""
    key_file = tmp_path / "key.txt"
    key_file.write_text("sk-from-file", encoding="utf-8")
    monkeypatch.setenv("FAKBOT_TEST_KEY", "   ")
    monkeypatch.setenv("FAKBOT_TEST_KEY_FILE", str(key_file))

    assert config._load_secret("FAKBOT_TEST_KEY") == "sk-from-file"


def test_no_duplicate_definition_of_load_secret():
    """防回归：config.py 里 `_load_secret` 只能有**一处**定义。

    之前就是因为有两处（一处 def + 一处别名赋值），后者被覆盖导致 _FILE 失效。
    这里直接查源码，比运行期行为断言更能定位问题。
    """
    source = (config.__file__ and open(config.__file__, encoding="utf-8").read()) or ""
    defs = [ln for ln in source.splitlines() if ln.startswith("def _load_secret")]
    aliases = [ln for ln in source.splitlines() if ln.strip().startswith("_load_secret =")]

    assert len(defs) == 1, f"_load_secret 定义了 {len(defs)} 次，只允许 1 次"
    assert not aliases, f"不允许用别名赋值覆盖 _load_secret：{aliases}"
