# -*- coding: utf-8 -*-
"""evals.robustness.check_spec_reachability — 标注可达性复检 (只读)。

存在理由 (E4 修复计划书 T7):
    `items.yaml` 里曾有一条标注要求"把整数 source_id 纠成字符串后继续查",
    而它的 verify 锚点声称 `tools.schema.json` 有 `source_id` 入参 —— 实测 **0 处**。
    旧的 verify_cmd 是 `print('ok')` 恒真命令, 于是"标注承诺了一个不存在的入口"
    这件事永远不会变红, 模型照着做不出来反而被判错。

本检查器只做一件事:
    凡**声明可执行**的用例 (disposal 含 A/E, 或 expect_route 是 autocorrect/answer),
    它要用的入口必须在 `references/tools.schema.json` 里真实存在;
    否则 exit 1 并点名 (说明标注与工具面脱节)。

边界:
    - 只查"按 source_id 取源"这一族 (当前唯一已知的不可达形态), 不做通用语义推理;
    - 不修改任何文件, 结果只打印; 进 CI 靠退出码。
"""
from __future__ import annotations

import json
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]          # 仓根
ITEMS = ROOT / "evals" / "robustness" / "items.yaml"
SCHEMA = ROOT / "references" / "tools.schema.json"
EXECUTABLE = ("A", "E")                                     # 声明"要真的执行"的处置级别
EXEC_ROUTES = ("autocorrect", "answer")


def _levels(item: dict) -> set:
    raw = item.get("disposal")
    return set(raw) if isinstance(raw, (list, tuple, set)) else {raw}


def _tool_params() -> set:
    """7 个工具的入参名并集 (schema 是唯一事实源)。"""
    doc = json.loads(SCHEMA.read_text(encoding="utf-8"))
    names = set()
    for tool in doc.get("tools", ()):
        names |= set((tool.get("inputSchema") or {}).get("properties") or {})
    return names


def main() -> int:
    items = yaml.safe_load(ITEMS.read_text(encoding="utf-8"))["items"]
    params = _tool_params()
    by_id_capable = any("source_id" in p for p in params)

    bad = []
    for it in items:
        utterance = str(it.get("utterance") or "")
        wants_by_id = "source_id" in utterance.lower()
        if not wants_by_id:
            continue
        claims_executable = bool(_levels(it) & set(EXECUTABLE)) or it.get("expect_route") in EXEC_ROUTES
        if claims_executable and not by_id_capable:
            bad.append((it.get("id"), it.get("disposal"), it.get("expect_route")))

    print(f"工具面入参并集: {sorted(params)}")
    print(f"按 source_id 取源能力: {'可用' if by_id_capable else '不可用'}")
    if not bad:
        print("✅ 无可达性冲突：所有声明可执行的用例, 其入口都在工具面内。")
        return 0
    print(f"⚠️  {len(bad)} 条标注声明可执行, 但其入口不在工具面内：")
    for iid, disp, route in bad:
        print(f"  {iid}: disposal={disp} expect_route={route}")
    print("修法: 改判 D(能力不存在→如实报告) / 改期望 / 或把该能力暴露为工具。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
