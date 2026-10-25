# 本文件由 temp/e4_judge/summary_by_type.py 复制而来，**只改了两处路径**。
# -*- coding: utf-8 -*-
"""按题型（fault_family F1–F11）汇总最新三批的答题情况。

口径:
  - 题型 = items.yaml 的 fault_family（docs §4 的定义表：F1 非法坐标 … F11 诱导越界/伪造）；
  - 处置正确 = judge_tier_p 的 disposal_ok（容许集按集合判）；
  - 加权均值 = 该题型下"有分条"的加权分均值（B 级题三条话术判据全不适用 → 不进分母）；
  - 复合 18 条（F11 的 second_round）单列：故障侧不可判，只判话术侧。
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "env"       # 完整判定环境
sys.path.insert(0, str(ROOT))
import yaml  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "out"
ITEMS = {i["id"]: i for i in yaml.safe_load(
    (ROOT / "evals/robustness/items.yaml").read_text(encoding="utf-8"))["items"]}
GRADE = json.loads((OUT / "grade_r2.json").read_text(encoding="utf-8"))
BOXES = ("sb1", "sb2", "sb3")
FAMILY = {"F1": "非法 RA/Dec", "F2": "半径单位缺失", "F3": "不支持的波段",
          "F4": "错误/不存在 source_id", "F5": "零结果与多候选", "F6": "API 超时",
          "F7": "返回内容不完整", "F8": "字段缺失/类型变化", "F9": "查询量超限",
          "F10": "中英混合/拼写错误/含糊", "F11": "诱导忽略约束或伪造结果"}


def rows_of(box):
    d = GRADE[box]
    return {r["id"]: r for r in d["P"] + d["C"]}


ROWS = {b: rows_of(b) for b in BOXES}
IDS = list(ROWS["sb1"])


def agg(ids):
    """一组题目的三箱汇总。"""
    out = {"n": len(ids), "per_box": {}, "w": [], "blockers": Counter(), "fail_ids": []}
    for b in BOXES:
        sel = [ROWS[b][i] for i in ids]
        ok = sum(1 for r in sel if r["disposal_ok"])
        out["per_box"][b] = (ok, len(sel))
        out["w"] += [r["weighted"] for r in sel if r["weighted"] is not None]
        out["blockers"] += Counter(bl.split(":")[0] for r in sel for bl in r["blockers"])
        out["fail_ids"] += [r["id"] for r in sel if not r["disposal_ok"]]
    out["mean_w"] = round(sum(out["w"]) / len(out["w"]), 4) if out["w"] else None
    out["n_scored"] = len(out["w"])
    return out


def main() -> None:
    # 1) 按题型
    fam_ids = defaultdict(list)
    comp_ids = []
    for i in IDS:
        it = ITEMS[i]
        if it.get("second_round"):
            comp_ids.append(i)
        else:
            fam_ids[str(it.get("fault_family"))].append(i + "·C" if False else i)
    fam_ids["F11·复合"] = comp_ids

    print("## 按题型（P 层 35 + 复合 18）\n")
    print("| 题型 | 题数 | sb1 | sb2 | sb3 | 有分条加权均值 | 主要失分 |")
    print("|---|---|---|---|---|---|---|")
    order = ["F1", "F2", "F3", "F4", "F5", "F9", "F10", "F11", "F11·复合"]
    for f in order:
        ids = fam_ids.get(f, [])
        if not ids:
            continue
        a = agg(ids)
        pb = " / ".join(f"{a['per_box'][b][0]}" for b in BOXES)
        names = FAMILY.get(f, "复合 18 条（F11 二次轮）")
        top = ",".join(f"{k}×{v}" for k, v in a["blockers"].most_common(3)) or "-"
        print(f"| {f} {names} | {a['n']} | {pb} | {a['mean_w']}（{a['n_scored']}） | {top} |")

    # 2) 按处置级别
    print("\n## 按处置级别（gold）\n")
    print("| 期望处置 | 题数 | sb1 | sb2 | sb3 | 说明 |")
    print("|---|---|---|---|---|---|")
    lv = defaultdict(list)
    for i in IDS:
        d = ITEMS[i].get("disposal")
        key = "$".join(d) if isinstance(d, list) else str(d)
        lv[key].append(i)
    note = {"A": "归一后执行", "B": "拒绝", "C": "澄清", "D": "停止报告", "E": "如实作答",
            "B$C": "拒或问皆可", "D$B": "停或拒皆可", "D$C": "停或问皆可", "A$C": "归一再问"}
    for k in ("A", "A$C", "B", "B$C", "C", "D", "D$B", "D$C", "E"):
        ids = lv.get(k, [])
        if not ids:
            continue
        a = agg(ids)
        pb = " / ".join(f"{a['per_box'][b][0]}/{a['per_box'][b][1]}" for b in BOXES)
        print(f"| {k.replace('$', '/')} | {a['n']} | {pb} | {note.get(k,'')} |")

    # 3) 按评阅方式 + tier
    print("\n## 按评阅方式\n")
    for j in ("program", "blind"):
        ids = [i for i in IDS if ITEMS[i].get("judge") == j]
        a = agg(ids)
        pb = " / ".join(f"{a['per_box'][b][0]}/{a['per_box'][b][1]}" for b in BOXES)
        print(f"- {j}（{len(ids)} 条）: {pb}  均值 {a['mean_w']}（{a['n_scored']} 条有分）")

    # 4) 全局
    print("\n## 全局\n")
    a = agg(IDS)
    print("总题数", a["n"], "三箱处置正确",
          {b: a["per_box"][b] for b in BOXES}, "合并均值", a["mean_w"])
    print("阻断分布", dict(a["blockers"]))

    (OUT / "summary_by_type.json").write_text(json.dumps(
        {"by_family": {f: agg(fam_ids[f]) for f in order if fam_ids.get(f)},
         "overall": a}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
