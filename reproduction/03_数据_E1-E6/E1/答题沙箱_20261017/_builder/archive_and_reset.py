# -*- coding: utf-8 -*-
"""归档并复位三箱答题记录（移动，不删除）。

只做四件事：
  1. 把 sbN/answers/{NL2T-*.md, RUN-INFO.md} 移到 E1-答案归档-2026-10-18批次/sbN/answers/
  2. 把 sbN/_lock/{ANSWERS.sha256, *_report.md} 移到 归档/sbN/_lock/
  3. 用构建器的 run_info_template() 在原位重建一份未填台账
  4. 目标已存在则**拒绝覆盖**并报错退出（同一批不能归档两次）

不碰：skill/ 题卷/ _exec/ _lock 的 MANIFEST·BASELINE·脚本、answers/_答题模板.md
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(r"<USER_HOME>\E1-答题沙箱-2026-10-17")
ARCH = Path(r"<USER_HOME>\E1-答案归档-2026-10-18批次")
BOXES = ("sb1", "sb2", "sb3")
DRY = "--apply" not in sys.argv

sys.path.insert(0, str(ROOT / "_builder"))
from build_sandboxes import run_info_template  # noqa: E402


def plan() -> list[tuple[Path, Path]]:
    moves: list[tuple[Path, Path]] = []
    for box in BOXES:
        for p in sorted((ROOT / box / "answers").glob("NL2T-*.md")):
            moves.append((p, ARCH / box / "answers" / p.name))
        ri = ROOT / box / "answers" / "RUN-INFO.md"
        if ri.is_file():
            moves.append((ri, ARCH / box / "answers" / ri.name))
        for name in ("ANSWERS.sha256", "preflight_report.md", "progress_report.md", "verify_report.md"):
            p = ROOT / box / "_lock" / name
            if p.is_file():
                moves.append((p, ARCH / box / "_lock" / name))
    return moves


def main() -> int:
    moves = plan()
    print(f"[plan] 共 {len(moves)} 个文件 → {ARCH}")
    for src, dst in moves:
        flag = ""
        if not src.is_file():
            flag = "  ← 源不存在"
        elif dst.exists():
            flag = "  ✗ 目标已存在（拒绝覆盖）"
        print(f"  {src.relative_to(ROOT)} → {dst.relative_to(ARCH)}{flag}")
    if any(dst.exists() for _, dst in moves):
        print("[abort] 归档目录里已有同名文件：这批可能已归档过，未做任何改动。")
        return 1
    if DRY:
        print("\n[dry-run] 加 --apply 才真正移动。")
        return 0

    for src, dst in moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    print(f"[ok] 已移动 {len(moves)} 个文件")

    for box in BOXES:
        ri = ROOT / box / "answers" / "RUN-INFO.md"
        ri.write_text(run_info_template(box), encoding="utf-8")
        print(f"[ok] {box}/answers/RUN-INFO.md 已重建为未填模板")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
