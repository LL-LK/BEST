# -*- coding: utf-8 -*-
"""校验溯源表：逐条核对『论文行号』与『论文原文片段』是否真的出现在该行。

用法： python validate_ledger.py
"""
import csv, re, sys, os

ROOT = r"<WORKSPACE>"
SRC = os.path.join(ROOT, r"10_脱敏复现包\BEST_v72_图2嵌入正文确认_20261023\source")
LEDGER = os.path.join(ROOT, r"11_投稿包\_work\稿件取证\溯源表_稿件.csv")


def norm(s):
    s = s.replace("\\%", "%").replace("\\,", ",").replace("\\$", "$")
    s = s.replace("\\{", "{").replace("\\}", "}")
    s = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", "", s)
    s = s.replace("$", "").replace("{", "").replace("}", "")
    s = s.replace("&", "").replace("，", ",").replace("：", ":")
    s = s.replace("\\\\", "").replace("\\", "")
    s = re.sub(r"\s+", "", s)
    return s


def main():
    cache = {}
    rows = list(csv.DictReader(open(LEDGER, encoding="utf-8-sig")))
    bad = []
    for r in rows:
        tex = r["论文文件"]
        if tex not in cache:
            cache[tex] = open(os.path.join(SRC, tex), encoding="utf-8").read().splitlines()
        lines = cache[tex]
        ln = int(r["论文行号"])
        if ln < 1 or ln > len(lines):
            bad.append((r["claim_id"], tex, ln, "行号越界", r["论文原文片段"]))
            continue
        line = lines[ln - 1]
        nline = norm(line)
        # 片段可能用 | 分隔表格列、或用 … 省略中间文字：拆成片段后逐段要求出现
        parts = [p for p in re.split(r"[|…]", r["论文原文片段"]) if norm(p)]
        missing = [p for p in parts if norm(p) not in nline]
        if missing:
            bad.append((r["claim_id"], tex, ln, "片段未在该行出现: " + " / ".join(missing),
                        r["论文原文片段"]))
    print("校验条数 =", len(rows))
    print("不匹配 =", len(bad))
    for b in bad:
        print("  [%s] %s:%d  %s\n      片段: %s" % (b[0], b[1], b[2], b[3], b[4]))
    return bad


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
