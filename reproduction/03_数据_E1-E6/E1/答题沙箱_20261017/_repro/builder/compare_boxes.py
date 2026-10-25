#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""三箱台账一致性比对（G4）—— 补齐旧沙箱只写进计划书、从未实现的一闸

为什么需要它
────────────
三个沙箱是**同一个模型的三次重复**。`model_id` 只要有任何字面差异
（大小写 / 多一个空格 / 多个括号后缀，如 `WorkBuddy AI (DeepSeek-V3.2)`），
判分侧分组就会当成**三个不同模型**：三次重复退化成单次，方差算不出来，
横比直接失效。

上一版（E1-答题沙箱-2026-10-14）在《沙箱完善计划书》G4 里点名了这个缺陷，
也写了"compare_sandboxes.py 增加台账三栏比对，model_id 必须逐字相同否则判红" 的验收项 ——
但那个文件**从来没被创建**。所以这里补上。

为什么放在 `_builder/` 而不是箱内
────────────────────────────────
三箱互盲是硬约束：越界闸禁止**箱内**任何文件出现其他沙箱的名字。
所以比对只能在**箱外**做。本脚本位于沙箱根 `_builder/`，不属于任何一箱，
也就不会被判越界。

用法
────
    python _builder/compare_boxes.py              # 比对 + 打印
    python _builder/compare_boxes.py --json      # 机器可读输出
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BOXES = ("sb1", "sb2", "sb3")

# 三箱必须**逐字相同**的字段（不一致 = 废掉横比）
MUST_SAME = ("model_id", "system_prompt_version")
# 三箱必须**互不相同**的字段（相同 = 三次重复退化成一批）
MUST_DIFF = ("run_id",)

FIELD_RE = re.compile(r"^\|\s*([A-Za-z_][A-Za-z0-9_]*)\s*\|\s*(.*?)\s*\|\s*$", re.M)
UNSET = "<!-- UNSET -->"


def read_ledger(box: str) -> tuple[dict[str, str], str]:
    """读某箱台账。返回 (字段字典, 错误串)。"""
    p = ROOT / box / "answers" / "RUN-INFO.md"
    if not p.exists():
        return {}, f"{box}: 缺 answers/RUN-INFO.md"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        return {}, f"{box}: 读不了台账 ({e})"
    fields: dict[str, str] = {}
    for m in FIELD_RE.finditer(text):
        fields.setdefault(m.group(1), m.group(2))
    return fields, ""


def is_filled(val: str) -> bool:
    """值算不算已填：哨兵消失 + 非空 + 不是残留表头。"""
    v = (val or "").strip()
    return bool(v) and UNSET not in v and v != "|" and not v.startswith("---")


def compare() -> tuple[list[str], list[str], dict[str, dict[str, str]]]:
    """返回 (判红项, 提醒项, {箱: {字段: 值}})。"""
    errors: list[str] = []
    warns: list[str] = []
    data: dict[str, dict[str, str]] = {}

    for b in BOXES:
        fields, err = read_ledger(b)
        if err:
            errors.append(err)
            continue
        data[b] = fields

    if len(data) < 2:
        return errors, warns, data

    # ── 1) 是否填写 ────────────────────────────────────────────────────
    for b, fields in data.items():
        for f in MUST_SAME:
            val = fields.get(f, "")
            if not is_filled(val):
                warns.append(f"{b}: `{f}` 未填 —— 该批与别的批次不可横比")
        if not is_filled(fields.get("run_id", "")):
            warns.append(f"{b}: `run_id` 未填")

    # ── 2) 必须逐字相同 ────────────────────────────────────────────────
    for f in MUST_SAME:
        vals = {b: (data[b].get(f, "") or "").strip() for b in data if b in data}
        filled = {b: v for b, v in vals.items() if is_filled(v)}
        if len(filled) < 2:
            continue                       # 未填已在上一步提醒，不重复判红
        uniq = set(filled.values())
        if len(uniq) > 1:
            detail = " ｜ ".join(f"{b}=“{v}”" for b, v in sorted(filled.items()))
            errors.append(
                f"[G4] `{f}` 三箱不一致 —— 判分侧会当成 {len(uniq)} 个不同模型，"
                f"三次重复退化、方差算不出来、横比失效。\n"
                f"        {detail}\n"
                f"        修法：以其中一箱为准，**复制粘贴**到另外两箱，不要手打。")
        else:
            # 逐字相同，但顺带查一下"看起来像同一模型却写法不同"的隐患
            sample = next(iter(filled.values()))
            if sample != sample.strip():
                warns.append(f"`{f}` 首尾有空白字符（三箱虽一致，建议清掉）")

    # ── 3) 必须互不相同 ────────────────────────────────────────────────
    for f in MUST_DIFF:
        vals = {b: (data[b].get(f, "") or "").strip() for b in data if b in data}
        filled = {b: v for b, v in vals.items() if is_filled(v)}
        if len(filled) >= 2 and len(set(filled.values())) < len(filled):
            dup = " ｜ ".join(f"{b}=“{v}”" for b, v in sorted(filled.items()))
            errors.append(
                f"`{f}` 三箱出现了重复值 —— 三次重复必须各占一批，"
                f"否则事后分不清哪次是哪次。\n        {dup}")

    return errors, warns, data


def main() -> int:
    ap = argparse.ArgumentParser(description="三箱台账一致性比对（G4）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ns = ap.parse_args()

    errors, warns, data = compare()

    if ns.json:
        print(json.dumps({
            "boxes": sorted(data),
            "fields": data,
            "errors": errors,
            "warnings": warns,
            "verdict": "PASS" if not errors else "FAIL",
        }, ensure_ascii=False, indent=2))
        return 0 if not errors else 1

    print("═══════ 三箱台账一致性比对（G4）═══════")
    print(f"沙箱根: {ROOT}")
    print()

    if data:
        fields = ["run_id", "model_id", "system_prompt_version"]
        print("| 字段 | " + " | ".join(f"`{b}`" for b in BOXES if b in data) + " |")
        print("|---" * (len(data) + 1) + "|")
        for f in fields:
            cells = []
            for b in BOXES:
                if b not in data:
                    continue
                v = (data[b].get(f, "") or "").strip()
                cells.append("（未填）" if not is_filled(v) else f"`{v}`")
            print(f"| `{f}` | " + " | ".join(cells) + " |")
        print()

    if warns:
        print("── 提醒（不判红，但该批不可横比）──")
        for w in warns:
            print("   · " + w)
        print()

    if errors:
        print("── 判红 ──")
        for e in errors:
            print("   ✗ " + e)
        print()

    print("══════════════════════════════════")
    print(f"   判红 {len(errors)} 条 · 提醒 {len(warns)} 条")
    print(f"   ── 判定: {'PASS ✅' if not errors else 'FAIL ❌'}")
    print("══════════════════════════════════")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
