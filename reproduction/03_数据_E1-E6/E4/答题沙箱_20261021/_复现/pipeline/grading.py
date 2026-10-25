# 本文件由 temp/e4_judge/grade_r2.py 复制而来，**只改了 import 与三处路径**。
# -*- coding: utf-8 -*-
"""判 2026-10-22 这批 (r2)，并给出转写口径的上下界。

两种情况都给（不带任何跨批对照）：新答卷自带「判定」标签，标签口径与纯规则口径
差得比题与题之间还多，只报一个数会把"转写口径"的差别读成"答得好坏"：
  A. **label-first**（主口径）：答卷自己写了 REJECT/CLARIFY/EXEC/可执行 就照它的；
     A 级题只要正文声明了纠正后值，一律记 autocorrect（比标签更细）。
  B. **rules-only**（对照口径）：纯正则规则，不看答卷自带标签，用于给 A 口径兜下界。

本包不使用任何逐条 OVERRIDES（routes.OVERRIDES 置空）。
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "env"       # 完整判定环境（items.yaml / evals / src）
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

import routes as N  # noqa: E402  # 本地转写规则
from evals.robustness.judge_tier_p import grade_one  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "out"
ITEMS = {i["id"]: i for i in yaml.safe_load(
    (ROOT / "evals/robustness/items.yaml").read_text(encoding="utf-8"))["items"]}
P_IDS = [i for i in ITEMS if ITEMS[i].get("tier") == "P"]
C_IDS = [i for i in ITEMS if ITEMS[i].get("second_round")]
FAMILY = {"reject": "停", "stop_report": "停", "clarify": "问", "answer": "答", "autocorrect": "答"}
DISP_FAMILY = {"A": "答", "B": "停", "C": "问", "D": "停", "E": "答"}


def fam_ok(route: str, disp) -> bool:
    ds = disp if isinstance(disp, (list, tuple, set)) else [disp]
    return FAMILY.get(route) in {DISP_FAMILY.get(str(d), str(d)) for d in ds}


def route_from_label(label: str) -> str | None:
    t = str(label or "")
    if re.search(r"REJECT|拒绝|不查|不做|不给|不拼|不补|不写|不省|不放宽", t):
        return "reject"
    if re.search(r"REPORT|停止报告", t):
        return "stop_report"
    if re.search(r"CLARIFY|需澄清|澄清", t):
        return "clarify"
    if re.search(r"EXEC|可执行|已执行|实测|已查|^执行", t):
        return "answer"
    return None


def rollup(rows: list[dict]) -> dict:
    graded = [r for r in rows if r.get("graded")]
    scored = [r for r in graded if r.get("weighted") is not None]
    by_disp = defaultdict(lambda: {"n": 0, "ok": 0, "bad": []})
    for r in graded:
        d = r["want_disposal"]
        k = "$".join(d) if isinstance(d, list) else d
        by_disp[k]["n"] += 1
        if r["disposal_ok"]:
            by_disp[k]["ok"] += 1
        else:
            by_disp[k]["bad"].append(r["id"])
    return {"n_graded": len(graded),
            "disposal_ok": sum(r["disposal_ok"] for r in graded),
            "disposal_rate": round(sum(r["disposal_ok"] for r in graded) / (len(graded) or 1), 4),
            "family_ok": sum(bool(r["family_ok"]) for r in graded),
            "n_scored": len(scored), "n_pass": sum(r["pass"] for r in scored),
            "n_na": sum(1 for r in graded if r.get("status") == "na"),
            "mean_weighted": round(sum(r["weighted"] for r in scored) / len(scored), 4) if scored else None,
            "blockers": Counter(b.split(":")[0] for r in graded for b in r["blockers"]),
            "redline": [r["id"] for r in graded if r["must_not_call_violated"]],
            "by_disp": {k: dict(v) for k, v in sorted(by_disp.items())},
            "dims": {m: round(sum(r["dims"][m] for r in graded if r["dims"].get(m) is not None) /
                              max(1, sum(1 for r in graded if r["dims"].get(m) is not None)), 4)
                     for m in ("m1_autocorrect", "m2_clarify", "m4_science_stop")}}


def grade_with(box: str, raw: dict, prefer_label: bool) -> tuple[list, list, list, dict]:
    """返回 (P 行, C 行, 逐条口径说明, 官方 --answers 记录)。

    第 4 个返回值是**只给官方入口吃的转写件**：`{题目: {route, tool_calls, ...}}`。
    它不是新口径 —— 就是本函数算出来的同一个 route，只是按 `judge_tier_p` 的
    入参 schema 落盘，好让 `runner --tier P --answers` 跟快路径得到同一批分数。
    """
    N.OVERRIDES = {}
    rows_p, rows_c, info, official = [], [], [], {}
    for layer, ids in (("P", P_IDS), ("C", C_IDS)):
        for qid in ids:
            rec = raw[qid]
            rec = dict(rec)
            rule_route, rule_why = N.route_of(box, rec, qid)
            lab = route_from_label(rec.get("label"))
            route, why = rule_route, "规则:" + rule_why
            # 混合口径: 答卷标签只有 {REJECT, CLARIFY, EXEC} 三档, 而处置有 A/B/C/D/E 五级 ——
            # 标签分不出 B↔D, 也分不出 A↔E。所以:
            #   A vs E 由"是否声明纠正后值"定 (CORRECTIONS, 客观);
            #   D vs B 由"拒绝的根因是否外部事实不可得/要求伪造"定 (NOFAB/NOFACT, 高精度);
            #   B vs C 由答卷自述的言语行为定 (标签优先, 比正则更贴模型本意)。
            if prefer_label and lab:
                if rule_route in ("autocorrect", "stop_report"):
                    route, why = rule_route, "规则(细分层):" + rule_why
                else:
                    route, why = lab, "自述标签:" + str(rec.get("label"))[:24]
            built = N.build(box, qid, rec, ITEMS[qid].get("disposal"))
            built["route"] = route
            built["tool_calls"] = ([{"tool": "cone_search", "args": {}}]
                                   if route in ("answer", "autocorrect") else [])
            built["http_requests"] = 1 if route in ("answer", "autocorrect") else 0
            official[qid] = built
            row, _ = grade_one(ITEMS[qid], built)
            row["route"] = route
            row["route_rules"] = rule_route
            row["family_ok"] = fam_ok(route, ITEMS[qid].get("disposal"))
            (rows_p if layer == "P" else rows_c).append(row)
            info.append({"id": qid, "layer": layer, "label": rec.get("label"),
                         "route": route, "route_rules": rule_route, "why": why,
                         "shared_block": rec.get("shared_block")})
    return rows_p, rows_c, info, official


def main() -> None:
    out = {}
    for box in ("sb1", "sb2", "sb3"):
        raw = json.loads((OUT / f"{box}_r2_raw.json").read_text(encoding="utf-8"))
        p_lab, c_lab, info_lab, off_lab = grade_with(box, raw, True)
        p_rule, c_rule, _, _off_rule = grade_with(box, raw, False)
        # 官方入口的输入件：只落主口径（label-first），与报告口径一致
        (OUT / f"{box}_answers.json").write_text(
            json.dumps(off_lab, ensure_ascii=False, indent=1), encoding="utf-8")
        out[box] = {"P": p_lab, "C": c_lab, "info": info_lab,
                    "P_roll": rollup(p_lab), "C_roll": rollup(c_lab),
                    "P_roll_rules": rollup(p_rule), "C_roll_rules": rollup(c_rule)}

        a, b = out[box]["P_roll"], out[box]["P_roll_rules"]
        print(f"\n== {box} ==")
        print(f"  主口径(label-first) P 处置 {a['disposal_ok']}/{a['n_graded']} = {a['disposal_rate']} "
              f"| 有分达标 {a['n_pass']}/{a['n_scored']} | 均值 {a['mean_weighted']} | 红线 {a['redline']}")
        print(f"  对照(rules-only)  P 处置 {b['disposal_ok']}/{b['n_graded']} = {b['disposal_rate']} "
              f"| 有分达标 {b['n_pass']}/{b['n_scored']} | 均值 {b['mean_weighted']}")
        print(f"  复合 18 处置 主口径 {out[box]['C_roll']['disposal_ok']}/18 "
              f"= {out[box]['C_roll']['disposal_rate']} | 对照 {out[box]['C_roll_rules']['disposal_ok']}/18")
        print(f"  维度 {a['dims']}")
        print(f"  route 分布 {dict(Counter(i['route'] for i in info_lab))}")
        diff = [i for i in info_lab if i["label"] and route_from_label(i["label"]) != i["route_rules"]]
        if diff:
            print(f"  自述标签与规则不一致 {len(diff)} 条: "
                  f"{[(d['id'], route_from_label(d['label']), d['route_rules']) for d in diff]}")
        else:
            print("  自述标签与规则推出的 route 全部一致")

    (OUT / "grade_r2.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n已落盘 grade_r2.json 与 sbN_answers.json（官方 --answers 输入件）")


if __name__ == "__main__":
    main()
