# -*- coding: utf-8 -*-
"""用**官方入口**（`python -m evals.robustness.runner`）复判三箱，与快路径对账。

与 `reproduce.py` 的区别：
  reproduce.py           另造的判定路径 —— pipeline 直接调 `grade_one`
  reproduce_official.py  官方入口 —— `runner --tier P --answers`，同时触发
                         判定器自证（metascore / 正例门禁 / schema guard）

用法：
    cd "<HOME>\E4-答题沙箱-2026-10-21\\_复现"
    python reproduce_official.py            # P 层三箱 + W 层协议臂
    python reproduce_official.py --p-only   # 只跑 P 层

退出码：0 = 官方入口与快路径逐项一致；1 = 有偏差。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV = HERE / "env"
OUT = HERE / "out"
BOXES = ("sb1", "sb2", "sb3")


def run_runner(args: list[str]) -> dict:
    """在 env/ 下跑官方入口，返回落盘的 json。"""
    cmd = [sys.executable, "-m", "evals.robustness.runner", *args]
    p = subprocess.run(cmd, cwd=ENV, env={**__import__("os").environ, "PYTHONPATH": str(ENV)},
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = (p.stdout or "").strip().splitlines()[-3:]
    print(f"    runner {' '.join(args[:2])} … rc={p.returncode} | " + " / ".join(tail))
    if p.returncode not in (0, 1):
        print(p.stderr[-1500:])
        raise SystemExit(f"[STOP] 官方入口跑失败 (rc={p.returncode})")
    return p


def p_layer() -> dict:
    got = {}
    for b in BOXES:
        src = OUT / f"{b}_answers.json"
        if not src.is_file():
            raise SystemExit(f"[STOP] 缺 {src.name}：先跑 reproduce.py 生成官方输入件")
        dst = OUT / f"official-{b}.json"
        run_runner(["--tier", "P", "--answers", str(src), "--json", str(dst)])
        d = json.loads(dst.read_text(encoding="utf-8"))
        s = d["P"]["summary"]
        got[b] = {
            "disposal": f"{s['disposal_ok']}/{s['n_graded']}",
            "disposal_rate": s["disposal_rate"],
            "n_weighted_pass": s["n_weighted_pass"],
            "n_weighted_graded": s["n_weighted_graded"],
            "n_na": s["n_na"],
            "redline": s["must_not_call_violations"],
            "metascore": d.get("_metascore", {}).get("value"),
            "guard": d.get("_metascore", {}).get("guard_score"),
            "positive": d.get("_positive", {}).get("value"),
            "P_pass": d["P"].get("pass"),
            "n_cases": d["P"].get("n_cases"),
            "n_answered": d["P"].get("n_answered"),
        }
    return got


def w_layer() -> dict:
    dst = OUT / "official-tierW.json"
    run_runner(["--tier", "W", "--json", str(dst)])
    d = json.loads(dst.read_text(encoding="utf-8"))
    w = d.get("W", {})
    return {"n_pass": w.get("n_pass"), "n_cases": w.get("n_cases"),
            "pass": w.get("pass"), "surface": w.get("surface")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--p-only", action="store_true", help="跳过 W 层（协议臂较慢）")
    a = ap.parse_args()

    (OUT).mkdir(exist_ok=True)
    print("=" * 62)
    print("[1/2] 官方入口 --tier P：三箱话术层")
    got = p_layer()
    for b, v in got.items():
        print(f"  {b}: 处置 {v['disposal']} = {v['disposal_rate']} | 有分达标 "
              f"{v['n_weighted_pass']}/{v['n_weighted_graded']} | 红线 {v['redline']} | "
              f"metascore {v['metascore']} / guard {v['guard']} / 正例 {v['positive']}")
    print(f"  注：P 层整体 pass={got['sb1']['P_pass']} —— 这不是跑失败，"
          f"是「有分条目未全部过 0.90 线」的如实结论；runner 因此返回 rc=1。")

    if not a.p_only:
        print("\n[2/2] 官方入口 --tier W：协议臂 15 条（回放 + 注入）")
        w = w_layer()
        print(f"  通过 {w['n_pass']}/{w['n_cases']} | surface={w['surface']} | 整体 pass={w['pass']}")

    exp_path = HERE / "expected" / "official.json"
    payload = {"P": got, **({} if a.p_only else {"W": w})}
    if not exp_path.is_file():
        exp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print("\n[基线] 首次运行，已写为基准: expected/official.json")
        return 0

    exp = json.loads(exp_path.read_text(encoding="utf-8"))
    bad = [b for b in got if exp.get("P", {}).get(b) != got[b]]
    if not bad and ("W" not in payload or exp.get("W") == payload["W"]):
        print("\nOK 官方入口与快路径逐项一致")
        return 0
    print("\nFAIL 与基准不一致")
    for b in bad:
        print(f"  {b}: 基准 {exp['P'].get(b)}")
        print(f"      本次 {got[b]}")
    if "W" in payload and exp.get("W") != payload["W"]:
        print(f"  W: 基准 {exp.get('W')} != 本次 {payload['W']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
