# -*- coding: utf-8 -*-
"""E6 稿件数字重算：从 01_当前R3补测\\R3-consistency.json 复算四项一致性指标与有效记录。

用法： python recompute_e6.py
"""
import json, sys, os

ROOT = r"<WORKSPACE>"
CONS = ROOT + r"\04_实验数据\E6_可复现性\实验产物\01_当前R3补测\R3-consistency.json"
REPORT = ROOT + r"\04_实验数据\E6_可复现性\实验产物\01_当前R3补测\REPORT.md"

PAPER = {
    "TSC": "0.8637, CI 0.7869--0.9310",
    "PAC_call": "0.8538, CI 0.7980--0.9066",
    "RDC": "0.7286, CI 0.6315--0.8167",
    "FCC": "0.8673, CI 0.7810--0.9405",
}


def main():
    with open(CONS, encoding="utf-8") as f:
        d = json.load(f)
    agg = d.get("aggregate", {})
    print("== E6 聚合（aggregate）==")
    for k in ["TSC", "PAC_call", "RDC", "FCC"]:
        v = agg.get(k)
        print("%-9s %s" % (k, json.dumps(v, ensure_ascii=False) if v is not None else "MISSING"))
    print()
    pt = d.get("per_task", {})
    usable = {k: [] for k in ["TSC", "PAC_call", "RDC", "FCC"]}
    runs = 0
    full5 = 0
    for tid, rec in pt.items():
        runs += rec.get("runs", 0)
        if rec.get("runs", 0) == 5:
            full5 += 1
        for k in usable:
            node = rec.get(k) or {}
            val = node.get("value", node.get("estimate"))
            if val is not None:
                usable[k].append((tid, val))
    print("逐题记录数 = %d；有效重复数合计 = %d；完整五次重复题数 = %d/32" % (len(pt), runs, full5))
    for k in ["TSC", "PAC_call", "RDC", "FCC"]:
        vals = [v for _, v in usable[k]]
        if vals:
            print("%-9s 宏平均(n=%d) = %.10f  | 论文呈现 %s" % (k, len(vals), sum(vals) / len(vals), PAPER[k]))
    print()
    print("== 有效记录率 ==")
    print("REPORT.md: 有效 133/160 -> 133/160 = %.6f (%%.2f = %.2f%%)" % (133 / 160, 133 / 160 * 100))
    print("论文呈现 133/160（83.13%%）；证据文件写 83.12%% -> 舍入口径不同（0.83125 恰为半值）")
    print()
    print("== 生成预算 ==")
    print("run_manifest.json: max_output_tokens = 32768, reasoning.effort = max, 未发送 temperature, 未请求 seed")
    print("REPORT.md 另记: 有效 133/160（83.12%%），失败 27，完整 5 次有效题 21/32，可估计题数 28")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
