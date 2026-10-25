#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E4 三箱验收（四部）：一致性 / 静态隔离 / 负向反证 / 命令自检。

A 一致性: 三箱逐文件 sha256 相同, 文件数相同, 且与构建时登记的清单哈希一致。
B 静态隔离: 调用 audit_leak.py, 必须 exit 0。
C 负向反证: 往 sb2 塞一句**真实答案原文**, 审计必须变红; 清掉后必须转绿。
   —— 这一部不能省: 没有它, "审计通过"可能只是"审计没在扫东西"。
D 命令自检: 每箱能在自身 cwd 里导入被测对象 (`src.protocol`), 入口件齐全,
   题卷 68 条, 答案面在盒外且为空, 无符号链接/联接点。

输出 `_验收/验收报告.md`(脚本产物)。任一部失败即 exit 1。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BOXES = ("sb1", "sb2", "sb3")
DEFAULT_SOURCE = Path(r"<USER_HOME>\OneDrive\桌面\AI-archive-pre-sinking-snapshot-20261010\E4-work")
PY = sys.executable


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def manifest(box: Path) -> dict[str, str]:
    return {p.relative_to(box).as_posix(): sha256(p)
            for p in sorted(box.rglob("*")) if p.is_file()}


def part_a() -> dict:
    ms = {b: manifest(ROOT / b) for b in BOXES}
    counts = {b: len(ms[b]) for b in BOXES}
    ident = len({json.dumps(ms[b], sort_keys=True) for b in BOXES}) == 1
    recorded = {}
    mf = ROOT / "SANDBOX-MANIFEST.json"
    if mf.is_file():
        doc = json.loads(mf.read_text(encoding="utf-8"))
        recorded = {b: doc["boxes"][b].get("manifest_sha") for b in BOXES if b in doc.get("boxes", {})}
    now = {b: hashlib.sha256(json.dumps(ms[b], sort_keys=True).encode()).hexdigest()[:16] for b in BOXES}
    drift = [b for b in BOXES if recorded.get(b) and recorded[b] != now[b]]
    return {"ok": ident and not drift, "identical": ident, "counts": counts,
            "hash_now": now, "hash_recorded": recorded, "drift_since_build": drift}


def run_audit() -> tuple[int, str]:
    r = subprocess.run([PY, str(HERE / "audit_leak.py"), "--no-report"],
                       capture_output=True, text=True, cwd=str(ROOT))
    return r.returncode, (r.stdout + r.stderr)[-1500:]


def part_c(source: Path) -> dict:
    """负向: 塞一句真实答案原文进 sb2 的题卷, 审计必须红。"""
    items = yaml.safe_load((source / "evals" / "robustness" / "items.yaml").read_text(encoding="utf-8"))["items"]
    victim = ROOT / "sb2" / "questions" / "per_item" / "__leak_probe__.txt"
    token = None
    for it in items:
        for s in (it.get("reject") or {}).get("suggest") or []:
            if isinstance(s, str) and len(s) >= 20:
                token = s
                break
        if token:
            break
    if not token:
        return {"ok": False, "note": "找不到可用的答案原文做探针"}
    victim.write_text(token + "\n", encoding="utf-8")
    try:
        code_bad, _ = run_audit()
    finally:
        victim.unlink(missing_ok=True)
    code_good, _ = run_audit()
    return {"ok": code_bad != 0 and code_good == 0,
            "audit_with_probe": code_bad, "audit_after_cleanup": code_good,
            "probe": token[:40]}


def part_d() -> dict:
    rows = []
    for b in BOXES:
        box = ROOT / b
        problems = []
        for rel in ("SKILL.md", "SANDBOX-RULES.md", "ALLOWED-FILES.md"):
            if not (box / rel).is_file():
                problems.append(f"缺 {rel}")
        per_item = list((box / "questions" / "per_item").glob("*.txt"))
        if len(per_item) != 53:      # P 35 + 复合 18; W 15 条不进模型题卷
            problems.append(f"题卷 per_item {len(per_item)} != 53")
        if (box / "TASKS.md").exists() or (box / "questions" / "TASKS.md").exists():
            problems.append("盒内出现 TASKS.md（操作手册，含注入剧透）")
        links = [p.relative_to(box).as_posix() for p in box.rglob("*") if p.is_symlink()]
        if links:
            problems.append(f"存在符号链接: {links[:3]}")
        answers = ROOT / "_answers" / b
        try:
            answers.relative_to(box)
            problems.append("答案面在盒内")
        except ValueError:
            pass
        # 构建态答案面必须完全为空（不再豁免 batch-manifest.json：
        # 那个豁免让一张带源绝对路径的旧卡在答案面里躺了两轮没人发现）
        extra = ([p.relative_to(answers).as_posix() for p in answers.rglob("*") if p.is_file()]
                 if answers.is_dir() else ["缺答案目录"])
        if extra:
            problems.append(f"答案面构建态应为空, 实有: {extra[:3]}")
        # 批次卡在 _batch/，且不得含溯源字段/绝对路径
        card = ROOT / "_batch" / f"{b}.json"
        if not card.is_file():
            problems.append(f"缺批次卡 _batch/{b}.json")
        else:
            raw = card.read_text(encoding="utf-8")
            for kw in ("request_sources", "shared_request_families", "items_path"):
                if kw in raw:
                    problems.append(f"批次卡含溯源字段 {kw}")
            if re.search(r"[A-Za-z]:\\\\", raw):
                problems.append("批次卡含盘符绝对路径")
        # 命令自检: 在盒内 cwd 导入被测对象 (依赖已装在宿主 python)
        r = subprocess.run([PY, "-c", "import src.protocol as p; print(len(p.CATALOG_PATHS))"],
                           capture_output=True, text=True, cwd=str(box), timeout=120)
        if r.returncode != 0:
            problems.append(f"import 失败: {(r.stderr or '')[-160:]}")
        rows.append({"box": b, "ok": not problems, "problems": problems,
                     "n_per_item": len(per_item), "import_ok": r.returncode == 0})
    return {"ok": all(r["ok"] for r in rows), "rows": rows}


def render(rep: dict) -> str:
    a, b, c, d = rep["A"], rep["B"], rep["C"], rep["D"]
    lines = ["# E4 三箱验收报告", "",
             f"- 时间：{rep['at']}",
             f"- 总判定：**{'通过' if rep['ok'] else '未通过'}**", "",
             "| 部 | 内容 | 结果 |", "|---|---|---|",
             f"| A | 三箱逐文件一致 | {'✅' if a['ok'] else '❌'} 计数 {a['counts']} 哈希 {set(a['hash_now'].values())} |",
             f"| B | 静态隔离（审计 exit 0） | {'✅' if b['code'] == 0 else '❌ exit %s' % b['code']} |",
             f"| C | 负向反证（塞答案必须红） | {'✅' if c['ok'] else '❌'} 塞入后 exit={c.get('audit_with_probe')}、清除后 exit={c.get('audit_after_cleanup')} |",
             f"| D | 命令自检 | {'✅' if d['ok'] else '❌'} |", ""]
    if a.get("drift_since_build"):
        lines.append(f"- ⚠️ 与构建清单漂移：{a['drift_since_build']}")
    for r in d["rows"]:
        lines.append(f"- {r['box']}: {'OK' if r['ok'] else 'FAIL'}（题卷 {r['n_per_item']}，import {'ok' if r['import_ok'] else 'fail'}）")
        lines += [f"  - {p}" for p in r["problems"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    rep = {"at": datetime.now().isoformat(timespec="seconds")}
    rep["A"] = part_a()
    code, out = run_audit()
    rep["B"] = {"ok": code == 0, "code": code, "tail": out}
    rep["C"] = part_c(src.resolve())
    rep["D"] = part_d()
    rep["ok"] = all(rep[k]["ok"] for k in "ABCD")

    out_dir = ROOT / "_验收"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "验收报告.md").write_text(render(rep), encoding="utf-8", newline="\n")
    (out_dir / "verify.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2),
                                         encoding="utf-8", newline="\n")
    print(json.dumps({k: rep[k].get("ok") for k in "ABCD"} | {"overall": rep["ok"]}, ensure_ascii=False))
    print(f"报告: {out_dir / '验收报告.md'}")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
