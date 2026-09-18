# -*- coding: utf-8 -*-
"""重新生成 docs/answerable_samples.md（可回答样本清单）。

口径：`tests/test_set.json` 里 `expected_tag` **非空**的问句。
分组顺序 = **测试集里 tag 首次出现的顺序**（不是语料顺序——用语料序会让几十个
section 整体重排，diff 没法看）。

用法：
    python scripts/render_answerable_samples.py            # 写入
    python scripts/render_answerable_samples.py --check    # 只做保真自检，不写
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST_SET = ROOT / "tests" / "test_set.json"
OUT = ROOT / "docs" / "answerable_samples.md"


def render() -> str:
    data = json.loads(TEST_SET.read_text(encoding="utf-8"))
    cases = data["cases"]

    # 按 tag 首次出现顺序分组（dict 保序）
    groups: dict[str, list[str]] = {}
    for c in cases:
        tag = c.get("expected_tag")
        if tag:
            groups.setdefault(tag, []).append(c["query"])

    total = sum(len(v) for v in groups.values())
    lines = [
        "# 可回答样本清单（answerable samples）",
        "",
        "- 来源：`tests/test_set.json`",
        "- 口径：`expected_tag` 非空的测试问句（即应被机器人正确命中、不应转入兜底/拒答）",
        f"- 合计：**{total}** 条，覆盖 **{len(groups)}** 个意图",
        "",
        "> 每条样本均为对语料问法的改写（换同义词/改语序/加口语助词/错别字），用于检验模型泛化而非死记。",
        "",
    ]
    for tag, qs in groups.items():
        lines.append(f"## {tag}（{len(qs)} 条）")
        lines.append("")
        lines.extend(f"- {q}" for q in qs)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def main() -> int:
    new = render()
    old = OUT.read_text(encoding="utf-8", newline="") if OUT.exists() else None

    if "--check" in sys.argv:
        if old is None:
            print("清单不存在，无法自检")
            return 1
        same = old.replace("\r\n", "\n") == new
        print("保真自检：", "✅ 生成器能复现现有清单" if same else "❌ 不一致，先修生成器")
        if not same:
            import difflib

            a = old.replace("\r\n", "\n").splitlines()
            b = new.splitlines()
            for i, d in enumerate(list(difflib.unified_diff(a, b, "现有", "重新生成", lineterm=""))[:40]):
                print("   ", d)
        return 0 if same else 1

    OUT.write_text(new.replace("\n", "\r\n"), encoding="utf-8", newline="")
    print(f"[ok] 已写入 {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
