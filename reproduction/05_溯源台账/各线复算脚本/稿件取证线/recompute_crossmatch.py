# -*- coding: utf-8 -*-
"""E5 交叉匹配扩展评价重算：从 formal-scores.json 复算主验证成功率、仅一方成功数与运行总数。

用法： python recompute_crossmatch.py
"""
import json, sys, hashlib

ROOT = r"<WORKSPACE>"
F = ROOT + r"\10_脱敏复现包\BEST_v56_论文修订_20261020\BEST_v56\evidence\formal-scores.json"


def main():
    with open(F, "rb") as fh:
        digest = hashlib.file_digest(fh, "sha256").hexdigest()
    rows = json.loads(open(F, encoding="utf-8").read())
    print("== 证据来源 ==", F)
    print("文件 SHA256 =", digest)
    print("总记录数（两组 x (1024 主验证 + 96 诊断)）=", len(rows))
    for arm in ["B2b", "B3_compact"]:
        prim = [r for r in rows if r["arm"] == arm and r["primary"]]
        diag = [r for r in rows if r["arm"] == arm and not r["primary"]]
        ok = sum(r["objective_verified_data_task_success"] for r in prim)
        print("%-11s 主验证 %d/%d = %.4f%%  诊断来源 %d 条（成功 %d）"
              % (arm, ok, len(prim), ok / len(prim) * 100, len(diag),
                 sum(r["objective_verified_data_task_success"] for r in diag)))
    pb = {r["task_id"]: r["objective_verified_data_task_success"] for r in rows if r["arm"] == "B2b" and r["primary"]}
    pc = {r["task_id"]: r["objective_verified_data_task_success"] for r in rows if r["arm"] == "B3_compact" and r["primary"]}
    keys = set(pb) & set(pc)
    onlyB3 = sum(1 for k in keys if pc[k] and not pb[k])
    onlyB2b = sum(1 for k in keys if pb[k] and not pc[k])
    print()
    print("配对题数 =", len(keys))
    print("仅 B3_compact 成功 = %d (稿件 18)" % onlyB3)
    print("仅 B2b 成功      = %d (稿件 22)" % onlyB2b)
    print()
    print("稿件附录 C：1024 个主验证来源 + 96 个诊断来源，两组共 2240 次运行")
    print("复算: (1024 + 96) x 2 = %d" % ((1024 + 96) * 2))
    print("稿件正文：两种配置的程序核验成功率均超过 97%% -> %.4f%% / %.4f%%" % (
        sum(r["objective_verified_data_task_success"] for r in rows if r["arm"] == "B2b" and r["primary"]) / 1024 * 100,
        sum(r["objective_verified_data_task_success"] for r in rows if r["arm"] == "B3_compact" and r["primary"]) / 1024 * 100))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
