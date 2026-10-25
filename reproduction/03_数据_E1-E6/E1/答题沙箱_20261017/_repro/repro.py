# -*- coding: utf-8 -*-
"""repro.py — 用本目录自带的判分链，对三箱答案做端到端复现。

能力边界: 只读沙箱的 `sbN/answers/`，只写本目录 `out/`。
不碰沙箱内任何文件，不依赖工作区（本目录自带 tasks.yaml / graders / runner / src / references）。

用法:
  python repro.py --box sb1            # 单箱
  python repro.py --box all            # 三箱逐箱
  python repro.py --box all --combined # 三箱 + 三次重复合并

产物: out/<box>/{traces,report.json,REPORT.md}
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SANDBOX = HERE.parent          # 三箱就在上一级
DATA_ROOT = SANDBOX            # 数据源根: 默认读沙箱; --data-dir 可改指本目录 data/ (自包含快照)
TASKS = HERE / "evals" / "nl2tool" / "tasks.yaml"
BOXES = ("sb1", "sb2", "sb3")


def run(cmd: list[str], cwd: Path | None = None) -> int:
    """跑子进程并回传退出码 —— runner 在 PASS=False 时返回 1，那是判定不是故障。"""
    return subprocess.run(cmd, cwd=str(cwd or HERE)).returncode


def to_traces(box: str, out_dir: Path, data_root: Path | None = None) -> None:
    """答案 md → 轨迹 json（只做格式搬运）。"""
    src = (data_root or DATA_ROOT) / box
    if not (src / "answers").is_dir():
        raise SystemExit(f"[error] 找不到 {src / 'answers'}")
    rc = run([sys.executable, str(HERE / "tools" / "answers2traces.py"), str(src), str(out_dir)])
    if rc != 0:
        raise SystemExit(f"[error] 搬运失败: {box}")


def grade(traces: Path, out_dir: Path, attempts: int) -> dict:
    """跑 runner，返回 report dict。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    js = out_dir / "report.json"
    run([
        sys.executable, "-m", "evals.nl2tool.runner",
        "--tasks", str(TASKS), "--traces", str(traces),
        "--expect-attempts", str(attempts),
        "--json", str(js), "--md-out", str(out_dir / "REPORT.md"),
    ])
    if not js.is_file():
        raise SystemExit(f"[error] 判分未产出报告: {js}")
    return json.loads(js.read_text(encoding="utf-8"))


def read_run_info(box: str) -> dict:
    """从台账取 run_id / model_id —— 合并时按台账口径还原，不自己编。"""
    import re
    p = DATA_ROOT / box / "answers" / "RUN-INFO.md"
    info: dict[str, str] = {}
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\|\s*(run_id|model_id|system_prompt_version)\s*\|\s*(.+?)\s*\|", line)
            if m:
                info[m.group(1)] = m.group(2)
    return info


def combine(per_box: dict[str, Path]) -> Path:
    """三箱轨迹并到一个目录，attempt 按 1/2/3，run_id/model_id 取台账真值。"""
    import shutil
    out = HERE / "out" / "combined"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for attempt, box in enumerate(BOXES, start=1):
        info = read_run_info(box)
        for p in sorted(per_box[box].glob("NL2T-*.json")):
            t = json.loads(p.read_text(encoding="utf-8"))
            t["attempt"] = attempt
            t["run_id"] = info.get("run_id", f"{box}-r{attempt}")
            t["model_id"] = info.get("model_id", t.get("model_id", ""))
            t["batch"] = "repro"
            (out / f"{box}__{p.name}").write_text(
                json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="E1 三箱端到端复现")
    ap.add_argument("--box", default="all", help="sb1 / sb2 / sb3 / all")
    ap.add_argument("--combined", action="store_true", help="额外做三次重复合并")
    ap.add_argument("--data-dir", default=None,
                    help="答案所在根（默认=沙箱；传本目录 data 即完全自包含）")
    ns = ap.parse_args()

    global DATA_ROOT
    if ns.data_dir:
        DATA_ROOT = Path(ns.data_dir).resolve()
        print(f"[data] 数据源: {DATA_ROOT}")

    boxes = BOXES if ns.box == "all" else (ns.box,)
    per_box: dict[str, Path] = {}
    print("=" * 62)
    for box in boxes:
        out = HERE / "out" / box
        tr = out / "traces"
        to_traces(box, tr)
        r = grade(tr, out, attempts=1)
        per_box[box] = tr
        dims = {k: round(v, 4) for k, v in r["dims"].items() if v is not None}
        print(f"{box}: weighted={r['weighted']:.4f}  pass={r['pass']}  red={r['red_line_tasks']}")
        print(f"      dims={dims}")
    print("=" * 62)

    if ns.combined and len(boxes) > 1:
        tr = combine(per_box)
        r = grade(tr, HERE / "out" / "combined-out", attempts=len(boxes))
        dims = {k: round(v, 4) for k, v in r["dims"].items() if v is not None}
        print(f"combined: weighted={r['weighted']:.4f}  pass={r['pass']}  red={r['red_line_tasks']}")
        print(f"          dims={dims}")
        if r.get("unstable_tasks"):
            print(f"          unstable={r['unstable_tasks']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
