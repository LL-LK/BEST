# -*- coding: utf-8 -*-
"""E4 稿件数字重算：从原始逐条判分 grade_r2.json 独立复算三箱处置率、加权通过率与类别分布。

用法： python recompute_e4.py
"""
import json, sys, hashlib, collections

ROOT = r"<WORKSPACE>"
RAW = ROOT + (r"\10_脱敏复现包\BEST_v70_E4数据更新与批注核验_20261023"
               r"\work\E4_input\_复现\out\grade_r2.json")
FIGSRC = ROOT + r"\10_脱敏复现包\BEST_v72_图2嵌入正文确认_20261023\E4图复现\source_data.json"
EXPECT_SHA = "13f74f9b47d33d08358640af215bd7b2ffbfdb1d9b3b6701af7f05b271db8250"

PAPER = {
    "disposal": {"sb1": "34/35", "sb2": "35/35", "sb3": "34/35"},
    "weighted": {"sb1": "8/18", "sb2": "13/21", "sb3": "10/16"},
    "protocol": "15/15",
    "categories": "A 3×3=9/9；B 17×3=51/51；C 9×3=27/27；D 13/15；合法 3/3",
}


def main():
    digest = hashlib.file_digest(open(RAW, "rb"), "sha256").hexdigest()
    d = json.load(open(RAW, encoding="utf-8"))
    print("== 原始逐条判分 ==", RAW)
    print("SHA256 =", digest, "（与 E4_scored_records.json 声明的 source_sha256 %s）" % ("一致" if digest == EXPECT_SHA else "不一致"))
    print()
    tot_d = collections.Counter()
    tot_c = collections.Counter()
    for box in ["sb1", "sb2", "sb3"]:
        b = d.get(box) or {}
        P = b.get("P") or []
        C = b.get("C") or []
        P_roll = b.get("P_roll") or {}
        C_roll = b.get("C_roll") or {}
        if not P:
            print("【%s】无话术层 P 记录；顶层键 = %s" % (box, list(b.keys())))
            continue
        disp_ok = sum(1 for r in P if r.get("disposal_ok"))
        print("【%s】话术层 P: %d/%d 处置正确 (%.4f%%)  |  稿件 %s" %
              (box, disp_ok, len(P), disp_ok / len(P) * 100, PAPER["disposal"][box]))
        print("       加权判据: n_scored=%s  n_pass=%s  -> %s/%s  |  稿件 %s" %
              (P_roll.get("n_scored"), P_roll.get("n_pass"), P_roll.get("n_pass"),
               P_roll.get("n_scored"), PAPER["weighted"][box]))
        if C_roll:
            print("       协议/复合层 C: %s/%s 处置正确 (%.4f%%)  mean_weighted=%s  |  稿件复合 15/18" %
                  (C_roll.get("disposal_ok"), C_roll.get("n_graded"),
                   (C_roll.get("disposal_rate") or 0) * 100, C_roll.get("mean_weighted")))
        else:
            print("       复合层 C: 无 C_roll 汇总键；C 记录数 = %d" % len(C))
        for r in P:
            w = r.get("want_disposal")
            if isinstance(w, list):
                w = w[0]  # 期望处置可为多选（B/C 等）；按归档 answer key 的首个可接受处置归类
            tot_c[w] += 1
            if r.get("disposal_ok"):
                tot_d[w] += 1
    print()
    total = sum(tot_c.values())
    ok = sum(tot_d.values())
    print("三箱合计处置正确 = %d/%d = %.4f%%  |  图 5 汇总 103/105 = %.4f%%" %
          (ok, total, ok / total * 100, 103 / 105 * 100))
    print("分类别（want_disposal）:")
    for k in sorted(tot_c):
        print("   %-9s %2d/%2d" % (k, tot_d[k], tot_c[k]))
    print("   稿件: A 类 9/9；B 类 51/51；C 类 27/27；D 类 13/15；合法回答 3/3")
    print()
    fs = json.load(open(FIGSRC, encoding="utf-8"))["E4"]
    print("== 图 5 源数据 source_data.json ==")
    print("   protocol:", fs["protocol"], " language:", fs["language"],
          " -> %.2f%%" % (fs["language"]["correct"] / fs["language"]["total"] * 100))
    for c in fs["categories"]:
        print("   %s: %d/%d" % (c["label"], c["correct"], c["total"]))
    print()
    print("== 口径备注 ==")
    print("  · 本轮 E4 数据批次为 2026-10-21 三箱沙箱（digest ffce49a51c781c8a）；")
    print("    与 04_实验数据\\E4_鲁棒性与安全性 的 r1 批次（26/35 = 74.29%，7/16 = 43.75%）不是同一批次，不可混用。")
    print("  · 旧批次取证：99_缓存与临时\\取证_E4_口径分解_20261022.md；该批次的『answer 级越出 A/B/C/D』口径缺陷")
    print("    与『18 条复合故障未实跑』两项限制，在本批次（复合 15/18 已实跑）中已分别处理。")
    print("  · 旧批次另有 4 条 must_not_call 红线命中，本批次 sb1/sb2/sb3 的 redline 均为空列表。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
