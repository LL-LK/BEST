# -*- coding: utf-8 -*-
"""稿件图/文件引用存在性核对：解析 main.tex 与 supplementary_material.tex 的
\\includegraphics / \\input / \\include 指令，解析目标是否存在并给出 SHA256。

用法： python check_figures.py
输出：控制台核对表 + 图引用缺失表.csv（写到脚本同级目录）
"""
import re, os, sys, csv, hashlib

ROOT = r"<WORKSPACE>"
SRC = ROOT + r"\10_脱敏复现包\BEST_v72_图2嵌入正文确认_20261023\source"
OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAT = re.compile(r"\\(includegraphics|input|include)\s*(\[[^\]]*\])?\s*\{([^}]*)\}")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    rows = []
    for tex in ["main.tex", "supplementary_material.tex"]:
        p = os.path.join(SRC, tex)
        with open(p, encoding="utf-8") as f:
            for n, line in enumerate(f.read().splitlines(), 1):
                for m in PAT.finditer(line):
                    kind, opts, target = m.group(1), m.group(2) or "", m.group(3)
                    resolved = os.path.normpath(os.path.join(SRC, target))
                    exists = os.path.isfile(resolved)
                    rows.append(dict(
                        tex=tex, line=n, kind=kind, options=opts.strip("[]"), target=target,
                        resolved=resolved, exists="存在" if exists else "缺失",
                        sha256=(sha256(resolved) if exists else "无"),
                        bytes=(os.path.getsize(resolved) if exists else ""),
                    ))
    w = max(len(r["resolved"]) for r in rows)
    print("%-24s %5s %-14s %-42s %-6s %s" % ("tex", "line", "kind", "resolved", "exists", "sha256[:16]"))
    for r in rows:
        print("%-24s %5d %-14s %-*s %-6s %s" %
              (r["tex"], r["line"], r["kind"], w, r["resolved"], r["exists"], r["sha256"][:16]))
    missing = [r for r in rows if r["exists"] == "缺失"]
    print()
    print("引用总数 = %d；缺失 = %d" % (len(rows), len(missing)))
    for r in rows:
        print("  %s:%d  %s -> %s  [%s]" % (r["tex"], r["line"], r["target"], r["exists"], r["kind"]))

    out = os.path.join(OUT, "图引用缺失表.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        wri = csv.writer(f)
        wri.writerow(["论文文件", "论文行号", "引用命令", "引用参数", "引用目标", "解析后绝对路径", "存在性", "SHA256", "字节数"])
        for r in rows:
            wri.writerow([r["tex"], r["line"], "\\" + r["kind"], r["options"], r["target"],
                          r["resolved"], r["exists"], r["sha256"], r["bytes"]])
    print()
    print("已写出:", out)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
