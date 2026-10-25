# -*- coding: utf-8 -*-
"""E3 稿件数字重算：从 E3-main-recomputed.json 与 paired-bootstrap-all-metrics.json 复算。

用法： python recompute_e3.py
"""
import json, sys

ROOT = r"<WORKSPACE>"
RECOMP = ROOT + r"\04_实验数据\E3_科学忠实性\实验产物\01_当前结果\E3-main-recomputed.json"
BOOT = ROOT + r"\04_实验数据\E3_科学忠实性\实验产物\05_原始实验归档\paired-bootstrap-all-metrics.json"

PAPER = {
    "sfa": ("关键科学断言命中率", "S-A 90.14% / S-B 66.20% / 差 23.94pp"),
    "ungr": ("无来源科学数值率", "S-B 15.68% -> S-A 7.14%"),
    "ucr": ("无支撑科学主张率", "S-B 42.73% -> S-A 30.26%"),
    "slr": ("静态测光时间序列误述率", "S-B 14.29% -> S-A 0%"),
    "rqc": ("必要限定语覆盖率", "S-B 87.67% -> S-A 95.89%"),
    "pass_rate": ("严格合格率", "S-B 40.62% -> S-A 81.25%"),
}


def main():
    with open(RECOMP, encoding="utf-8") as f:
        d = json.load(f)
    with open(BOOT, encoding="utf-8") as f:
        b = json.load(f)
    print("== 指标中位数（原始主测32题）==")
    print("%-10s %-28s %14s %14s" % ("指标", "论文呈现值", "S-A", "S-B"))
    for k, (name, pv) in PAPER.items():
        a = d["systems"]["S-A"]["metrics"][k]["median"]
        s = d["systems"]["S-B"]["metrics"][k]["median"]
        print("%-10s %-28s %14.10f %14.10f" % (k + "/" + name, pv, a, s))
    print()
    print("== 逐重复计数（每次重复的分母）==")
    for i, rep in enumerate(d["systems"]["S-A"]["per_repeat"], 1):
        c = rep["counts"]
        print("S-A 重复%d: critical %d/%d  qualifier %d/%d  claims %d  unsupported %d  "
              "UCR %.4f%%  n_items %d  slr_denominator %d"
              % (i, c["critical_hit"], c["critical_total"], c["qualifier_hit"], c["qualifier_total"],
                 c["claims_total"], c["unsupported_claim"], c["unsupported_claim"] / c["claims_total"] * 100,
                 rep["n_items"], rep["slr_denominator"]))
    print()
    print("== 配对自助重抽样（%d 次，seed=%s）==" % (b["resamples"], b.get("seed")))
    for k, v in b["metrics"].items():
        lo, hi = v["bootstrap_95"]
        print("%-8s 点差 %+.10f  95%%CI [%+.4f, %+.4f] pp" % (k, v["point_A_minus_B"], lo * 100, hi * 100))
    sfa = b["metrics"]["sfa"]
    print()
    print("sfa 差值 = %.4f pp (论文 23.94)" % (sfa["point_A_minus_B"] * 100))
    print("sfa 95%%CI = %.2f -- %.2f pp (论文 12.68 -- 33.33)" % (sfa["bootstrap_95"][0] * 100, sfa["bootstrap_95"][1] * 100))
    print("McNemar 精确双侧 p = 0.00048828 (见 05_原始实验归档\\FINAL-REPORT.md) -> 论文呈现 0.00049")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
