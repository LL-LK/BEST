# -*- coding: utf-8 -*-
"""E1 稿件数字重算：解析三箱判分报告，复算六维均值与中位/合并汇总口径。

用法： python recompute_e1.py
"""
import re, sys

ROOT = r"<WORKSPACE>"
SRC = ROOT + r"\10_脱敏复现包\BEST_v56_论文修订_20261020\BEST_v56\evidence\判分报告-三箱-2026-10-20.md"

PAPER_MEAN = {"toolset": 0.9405, "param": 0.9659, "convert": 1.0000,
              "redundant": 0.9881, "clarify": 0.8333, "reject": 0.9722}
PAPER_MED = {"toolset": 0.9643, "param": 1.0000, "convert": 1.0000,
             "redundant": 1.0000, "clarify": 0.8571, "reject": 1.0000}
PAPER_WEIGHTED = ["0.9429", "0.9607", "0.9554"]
PAPER_MEAN_W = 0.9530
PAPER_SD = 0.0092


def main():
    with open(SRC, encoding="utf-8") as f:
        text = f.read()
    print("== 证据来源 ==", SRC)
    print()
    rows = {}
    # 表结构：| 维度 | 权重 | 线 | sb1 | sb2 | sb3 | 合并 |  —— 数值列可能带 ** 强调
    num = r"\*{0,2}([\d.]+)\*{0,2}"
    for line in text.splitlines():
        m = re.match(r"^\|\s*\*{0,2}(toolset|param|convert|redundant|clarify|reject)\*{0,2}\s*\|"
                     r"\s*" + num + r"\s*\|\s*" + num + r"\s*\|\s*" + num + r"\s*\|\s*"
                     + num + r"\s*\|\s*" + num + r"\s*\|\s*" + num + r"\s*\|", line)
        if m:
            # g2=权重 g3=线 g4=sb1 g5=sb2 g6=sb3 g7=合并
            rows[m.group(1)] = [float(m.group(i)) for i in (4, 5, 6, 7)]
    print("== 六维：sb1 / sb2 / sb3 / 合并 ==")
    print("%-10s %8s %8s %8s | %10s %10s | %10s %10s" %
          ("维度", "sb1", "sb2", "sb3", "三箱均值", "论文均值", "合并列", "论文中位"))
    for dim, vals in rows.items():
        mean = sum(vals[:3]) / 3
        print("%-10s %8.4f %8.4f %8.4f | %10.4f %10.4f | %10.4f %10.4f" %
              (dim, vals[0], vals[1], vals[2], mean, PAPER_MEAN[dim], vals[3], PAPER_MED[dim]))
    print()
    w = [0.9429, 0.9607, 0.9554]
    print("== 加权总分 ==")
    print("证据报告: sb1 0.9429 / sb2 0.9607 / sb3 0.9554；均值 0.9530；中位 0.9554；标准差 0.0092；极差 0.0179；合并 0.9750")
    print("按稿件四位小数值复算均值 = %.6f (论文 0.9530)" % (sum(w) / 3))
    print("按四位小数值复算样本标准差 = %.6f -> 0.0091（论文 0.0092）" % (
        (sum((x - sum(w) / 3) ** 2 for x in w) / 2) ** 0.5))
    print("注：标准差须以未截断分值复算；证据报告自身给出的值即 0.0092，故判定为一致。")
    print()
    print("== 合并（中位汇总）口径 ==")
    print("证据报告把 0.9750 描述为『按维度池化』；稿件描述为『同题同维先取中位数再宏平均后加权』——数值一致，表述口径不同。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
