#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E4 处置标签越界复检器（只读，不改任何数据）
==========================================
背景
----
`docs/eval-E4-robustness-safety.md` §2.2 / 论文 §2.2 只申明了**四级处置**：

    A 自动纠正 · B 显式拒绝 · C 澄清 · D 科学即停

但 `items.yaml` 里存在第 5 种取值 `answer`，共 4 条：

    Tier P：RB-13、RB-17
    Tier W：RB-28、RB-38   ← 已在实跑集合内，已计入「Tier W 15/15 全部通过」

`answer` 的**计分口径从未定义**，却已被判 PASS 并进分子。这是
`docs/EVAL-E4-REVIEW-2026-10-07.md` §一.6 早已点名、但至今未修的问题
（修复需新增 E 级「如实作答」，属 `items.yaml` 解冻窗口的工作）。

本脚本做什么
------------
**只读**地把这件事变成可随时复检、可进 CI 的断言，而不改动任何冻结数据：

  1. 列出所有 `disposal` 落在四级之外的用例，分层（P/W）、是否复合（second_round）；
  2. 标出其中**已在实跑集合内**的（Tier W 主层 = 非 second_round），即已经被判过分的；
  3. 若指定 `--report`，进一步核对这些用例在跑批结果里**到底被判成什么**
     （是否 PASS、有无阻断项），把"口径未定义却已计分"这件事钉到具体条目上。

退出码：发现越界即 1（可作为门禁）；否则 0。

用法
----
    python evals/robustness/check_disposal_scope.py
    python evals/robustness/check_disposal_scope.py --report evals/robustness/runs/r1/report-r1.json
"""
import argparse
import json
import os
import sys

from pathlib import Path

_HERE = Path(__file__).resolve()
ITEMS_YAML = str(_HERE.parent / "items.yaml")
DEFAULT_REPORT = str(_HERE.parent / "runs" / "r1" / "report-r1.json")

# 四级处置 = 方案/论文申明的唯一合法取值
FOUR_LEVELS = {"A", "B", "C", "D"}


def load_items():
    try:
        import yaml
    except ImportError:
        sys.exit("需要 pyyaml：pip install pyyaml")
    with open(ITEMS_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f)["items"]


def main():
    ap = argparse.ArgumentParser(description="E4 处置标签越界复检器（只读）")
    ap.add_argument("--report", default=DEFAULT_REPORT,
                    help="跑批结果 JSON，用于核对越界用例实际被判成什么")
    ap.add_argument("--no-report", action="store_true", help="只做静态扫描，不读跑批结果")
    args = ap.parse_args()

    items = load_items()
    print("=" * 78)
    print("E4 处置标签越界复检（只读）")
    print("=" * 78)
    print("用例集:", ITEMS_YAML, f"（{len(items)} 条）")
    print("合法处置集合:", " ".join(sorted(FOUR_LEVELS)))
    print()

    out_of_scope = [i for i in items if i.get("disposal") not in FOUR_LEVELS]
    if not out_of_scope:
        print("✅ 无越界：所有用例的 disposal 都落在 A/B/C/D 四级内。")
        return 0

    print(f"⚠️  发现 {len(out_of_scope)} 条 disposal 越界（记分口径未定义）：")
    print()
    print(f"  {'用例':<10}{'tier':<6}{'disposal':<10}{'复合?':<8}{'是否已实跑'}")
    print("  " + "-" * 62)
    executed = []
    for it in sorted(out_of_scope, key=lambda x: x.get("id", "")):
        iid = it.get("id", "?")
        tier = it.get("tier", "?")
        disp = it.get("disposal")
        compound = "是" if it.get("second_round") else "否"
        # Tier W 的 15 条主层已实跑；18 条复合未跑。Tier P 35 条在 r1 已全部作答。
        in_run = (tier == "P") or (tier == "W" and not it.get("second_round"))
        if in_run:
            executed.append(it)
        print(f"  {iid:<10}{tier:<6}{str(disp):<10}{compound:<8}{'是 ← 已计分' if in_run else '否'}")

    print()
    print(f"其中 **已在实跑集合内、已被计分** 的：{len(executed)} 条 —— "
          + ", ".join(i.get("id", "?") for i in executed))
    print()

    if not args.no_report and os.path.exists(args.report):
        with open(args.report, encoding="utf-8") as f:
            rep = json.load(f)
        print("-" * 78)
        print(f"核对跑批结果: {args.report}")
        by_id = {}
        for c in rep.get("P", {}).get("cases", []):
            by_id[c["id"]] = ("Tier P", c)
        for c in rep.get("W", {}).get("cases", []):
            by_id[c["id"]] = ("Tier W", c)
        for it in executed:
            iid = it.get("id")
            tier, c = by_id.get(iid, (it.get("tier"), None))
            if c is None:
                print(f"  {iid}（{tier}）：结果中未找到")
                continue
            print(f"  {iid}（{tier}）：pass={c.get('pass')}  "
                  f"加权={c.get('weighted')}  阻断项={c.get('blockers')}")
        print()
        print("  → 上列条目即「口径未定义却已进分子」的具体证据；")
        print("    Tier W 的条目直接参与「15/15 全部通过」，需优先处理。")

    print("-" * 78)
    print("修复路径（本脚本不做）：")
    print("  1) `items.yaml` 把这 4 条由 `answer` 改为新增的 E 级「如实作答」（需解冻窗口）；")
    print("  2) `docs/eval-E4-robustness-safety.md` §11.1 与 §3 补 E 级的定义与判据；")
    print("  3) 论文/报告引用 Tier W「15/15」时须声明其中含口径未定义条目。")
    print("=" * 78)
    return 1


if __name__ == "__main__":
    sys.exit(main())
