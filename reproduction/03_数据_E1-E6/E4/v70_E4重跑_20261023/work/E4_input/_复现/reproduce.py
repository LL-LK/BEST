# -*- coding: utf-8 -*-
"""一键复现：读 `../_answers/sbN/r2/` 三份答卷 → 抽取 → 判分 → 题型汇总 → 自检。

用法（只需 Python 3.10+ 与 PyYAML，不依赖任何仓库路径）：
    cd "<HOME>\E4-答题沙箱-2026-10-21\\_复现"
    python reproduce.py

退出码：0 = 与 expected/metrics.json 逐项一致；1 = 有偏差（会打印差在哪）。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "env"))           # 完整判定环境（evals/*, src/*, items.yaml）
sys.path.insert(0, str(HERE / "pipeline"))      # 管线（answers / routes / grading / by_type）

import answers  # noqa: E402
import grading  # noqa: E402


def check_env() -> None:
    """判据指纹自检：env/ 里的每个文件都必须与构建时逐字节一致。

    这条是"没用错判分器"的唯一机证 —— 任何人改一行 graders.py 或换一份
    items.yaml，这里就会停，而不是悄悄给出另一组分数。
    """
    want = {}
    for line in (HERE / "env" / "SHA256.txt").read_text(encoding="utf-8").splitlines():
        if line.strip():
            h, rel = line.split(None, 1)
            want[rel.strip()] = h
    bad = []
    for rel, h in want.items():
        p = HERE / "env" / rel
        got = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "MISSING"
        if got != h:
            bad.append(rel)
    if bad:
        raise SystemExit(f"[STOP] 判据文件被改过，复现结果不可比: {bad}")
    print(f"判据自检通过：{len(want)} 个文件指纹一致")


def metrics() -> dict:
    """把 159 个判定格压成可对账的摘要 + 一个稳定指纹。"""
    g = json.loads((HERE / "out" / "grade_r2.json").read_text(encoding="utf-8"))
    boxes = ("sb1", "sb2", "sb3")
    cells, per_box = [], {}
    rows_all = {}
    for b in boxes:
        rows = {r["id"]: r for r in g[b]["P"] + g[b]["C"]}
        rows_all[b] = rows
        for i in sorted(rows):
            r = rows[i]
            cells.append(f"{b}|{i}|{r['route']}|{r['status']}|{r['disposal_ok']}|{r['weighted']}")
        per_box[b] = {
            "P_disposal": f"{g[b]['P_roll']['disposal_ok']}/{g[b]['P_roll']['n_graded']}",
            "P_mean_weighted": g[b]["P_roll"]["mean_weighted"],
            "P_pass": f"{g[b]['P_roll']['n_pass']}/{g[b]['P_roll']['n_scored']}",
            "composite_disposal": f"{g[b]['C_roll']['disposal_ok']}/{g[b]['C_roll']['n_graded']}",
            "redline": g[b]["P_roll"]["redline"] + g[b]["C_roll"]["redline"],
            "dims": g[b]["P_roll"]["dims"],
        }
    ids = sorted(rows_all["sb1"])
    all_ok = [i for i in ids if all(rows_all[b][i]["disposal_ok"] for b in boxes)]
    all_bad = [i for i in ids if not any(rows_all[b][i]["disposal_ok"] for b in boxes)]
    same = sum(1 for i in ids
               if len({bool(rows_all[b][i]["disposal_ok"]) for b in boxes}) == 1)
    return {
        "per_box": per_box,
        "consistency": {"n": len(ids), "same_verdict": same,
                        "all_ok": len(all_ok), "all_bad": len(all_bad),
                        "all_bad_ids": all_bad},
        "digest": hashlib.sha256("\n".join(cells).encode("utf-8")).hexdigest()[:16],
    }


def main() -> int:
    print("=" * 62)
    (HERE / "out").mkdir(exist_ok=True)          # 产物目录: 每次跑都可从零重建
    check_env()

    print("\n[1/3] 抽取：三份答卷 → 逐题记录")
    answers.main()

    print("\n[2/3] 判分：53 题 × 3 箱（双口径）")
    grading.main()

    print("\n[3/3] 题型汇总")
    import by_type  # noqa: PLC0415  延迟导入: 它读 out/grade_r2.json, 必须等判分先落盘
    by_type.main()

    got = metrics()
    print("\n" + "=" * 62)
    print("复现结果")
    for b, v in got["per_box"].items():
        print(f"  {b}: P 处置 {v['P_disposal']} | 加权均值 {v['P_mean_weighted']} | "
              f"有分达标 {v['P_pass']} | 复合 {v['composite_disposal']} | 红线 {v['redline'] or '无'}")
    print(f"  一致性: 判定一致 {got['consistency']['same_verdict']}/{got['consistency']['n']}，"
          f"三箱全对 {got['consistency']['all_ok']} 条，三箱全错 {got['consistency']['all_bad']} 条 "
          f"{got['consistency']['all_bad_ids']}")
    print(f"  判定指纹 digest = {got['digest']}")

    exp_path = HERE / "expected" / "metrics.json"
    if not exp_path.is_file():
        exp_path.parent.mkdir(parents=True, exist_ok=True)
        exp_path.write_text(json.dumps(got, ensure_ascii=False, indent=1), encoding="utf-8")
        print("\n[基线] 首次运行，已把本次结果写为基准: expected/metrics.json")
        return 0
    exp = json.loads(exp_path.read_text(encoding="utf-8"))
    if exp["digest"] == got["digest"] and exp["per_box"] == got["per_box"]:
        print("\nOK 与基准逐项一致（159 个判定格指纹相同）")
        return 0
    print("\nFAIL 与基准不一致")
    for b in got["per_box"]:
        if exp["per_box"].get(b) != got["per_box"][b]:
            print(f"  {b}: 基准 {exp['per_box'].get(b)} != 本次 {got['per_box'][b]}")
    print(f"  digest: 基准 {exp['digest']} != 本次 {got['digest']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
