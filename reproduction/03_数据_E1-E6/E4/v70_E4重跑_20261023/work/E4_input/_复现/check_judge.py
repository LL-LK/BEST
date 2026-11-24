# -*- coding: utf-8 -*-
"""判分器体检：确认复现用的是**当前这一版**判据，不是旧副本。

两种用法：
    python check_judge.py                  # 只核对 env/ 与构建时指纹是否一致
    python check_judge.py --vs "D:\\path\\to\\E4-work"
                                           # 再与源仓逐文件比对，列出漂移

退出码：0 = 无漂移；1 = 有文件被改过 / 与源仓不一致。

为什么需要这个脚本：`reproduce.py` 的 SHA256 自检只回答"包里的文件有没有被我改过"，
不回答"包里的是不是最新那版"。后者必须有一个外部参照 —— 就是源仓。
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV = HERE / "env"

# 判分链上真正决定分数的 7 个文件（其余是运行环境，不影响口径）
CRITICAL = [
    "evals/robustness/items.yaml",
    "evals/robustness/graders.py",
    "evals/robustness/judge_tier_p.py",
    "evals/robustness/__init__.py",
    "evals/paths.py",
    "src/protocol.py",
    "src/protocol_catalog_tables.py",
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def mtime(p: Path) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vs", default="", help="源仓路径（如 E4-work），给了就做逐文件比对")
    a = ap.parse_args()

    recorded = {}
    for line in (ENV / "SHA256.txt").read_text(encoding="utf-8").splitlines():
        if line.strip():
            h, rel = line.split(None, 1)
            recorded[rel.strip()] = h

    print(f"{'文件':<44}{'sha256':<14}{'改于':<18}状态")
    print("-" * 92)
    bad = []
    for rel in CRITICAL:
        p = ENV / rel
        if not p.is_file():
            print(f"{rel:<44}{'-':<14}{'-':<18}缺失")
            bad.append(rel)
            continue
        h = sha(p)
        st = "一致" if recorded.get(rel) == h else "★与包内指纹不符"
        print(f"{rel:<44}{h[:12]:<14}{mtime(p):<18}{st}")
        if recorded.get(rel) != h:
            bad.append(rel)

    if a.vs:
        src = Path(a.vs)
        if not (src / "evals/robustness/items.yaml").is_file():
            print(f"\n[STOP] {src} 不像 E4 源仓（找不到 evals/robustness/items.yaml）")
            return 1
        print("\n与源仓比对：")
        drift = []
        for rel in CRITICAL:
            p, q = ENV / rel, src / rel
            if not q.is_file():
                print(f"  {rel:<44} 源仓无此文件")
                continue
            if sha(p) != sha(q):
                drift.append(rel)
                print(f"  ★漂移 {rel:<40} 包内 {sha(p)[:10]} / 源仓 {sha(q)[:10]}"
                      f" | 源仓改于 {mtime(q)}")
        if drift:
            print(f"\n有 {len(drift)} 个判据文件与源仓不一致 —— 包内是旧版，不能用来复现当前结果。")
            bad += drift
        else:
            print(f"  {len(CRITICAL)} 个判据文件与源仓逐字节一致")

    if bad:
        print(f"\nFAIL {len(set(bad))} 个文件有问题")
        return 1
    print("\nOK 判据与构建时指纹一致，且未见旧版混入")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
