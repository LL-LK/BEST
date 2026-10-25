# -*- coding: utf-8 -*-
"""
独立复算 E5 确认性消融结果（不依赖任何中间结论，直接读原始归档）。
来源：<WORKSPACE>\\04_实验数据\\E5_消融\\正式结果_2026-10-12\\scores.json
目标：复现 05_评审与验收\\BEST_v71_三项实验源头追查_20261023\\源头核验报告.md 中的
      B3=95/168=56.55%、A5=98/168=58.33%、净差3格、精确符号翻转检验 p=0.741865、
      95%题目重抽样区间 -8.93~+4.76 个百分点，以及按 decision_class 的净格分解。
只读原始文件，不写回、不修改。
"""
import json, hashlib, itertools, random
from collections import defaultdict, Counter

SRC = r"<WORKSPACE>\04_实验数据\E5_消融\正式结果_2026-10-12\scores.json"

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()

def _binom(n, k):
    """整数二项式系数 C(n, k)，避免依赖 math.comb / itertools.comb 的版本差异。"""
    if k < 0 or k > n:
        return 0
    k = min(k, n - k)
    res = 1
    for i in range(k):
        res = res * (n - i) // (i + 1)
    return res


def exact_sign_flip_two_sided(n_plus, n_minus):
    """精确配对符号翻转检验：按题目配对单位，n 个非零差，各符号等概率。"""
    n = n_plus + n_minus
    if n == 0:
        return 1.0
    m = min(n_plus, n_minus)
    tail = sum(_binom(n, k) for k in range(m + 1)) / float(2 ** n)
    return min(1.0, 2 * tail)

def main():
    raw = open(SRC, "rb").read()
    digest = hashlib.sha256(raw).hexdigest().upper()
    rows = json.loads(raw.decode("utf-8"))

    out = {}
    out["source_file"] = SRC
    out["source_sha256"] = digest
    out["source_bytes"] = len(raw)
    out["total_cells"] = len(rows)

    # ---- 结构完整性 ----
    tasks = sorted({r["task"] for r in rows})
    arms = sorted({r["arm"] for r in rows})
    reps = sorted({r["replicate"] for r in rows})
    out["n_tasks"] = len(tasks)
    out["n_arms"] = len(arms)
    out["arms"] = arms
    out["replicates"] = reps
    out["unique_session_ids"] = len({r["session_id"] for r in rows})
    out["unique_cell_ids"] = len({r["cell_id"] for r in rows})

    # ---- e2e_success 是否等于 all(checks.values()) ----
    mismatch = [r["cell_id"] for r in rows
                if bool(r.get("e2e_success")) != all(bool(v) for v in r.get("checks", {}).values())]
    out["e2e_success_rule_mismatches"] = len(mismatch)

    # ---- 各臂通过率 ----
    arm_pass = defaultdict(int); arm_total = defaultdict(int)
    for r in rows:
        arm_total[r["arm"]] += 1
        if r.get("e2e_success"):
            arm_pass[r["arm"]] += 1
    out["arm_pass_rates"] = {
        a: {"pass": arm_pass[a], "total": arm_total[a], "rate_pct": round(100.0 * arm_pass[a] / arm_total[a], 4)}
        for a in arms
    }

    # ---- 先在同题同配置内对三次重复取均值，再以 56 题为配对单位 ----
    task_arm = defaultdict(list)
    for r in rows:
        task_arm[(r["task"], r["arm"])].append(1.0 if r.get("e2e_success") else 0.0)

    def task_mean(task, arm):
        vals = task_arm.get((task, arm), [])
        return sum(vals) / len(vals) if vals else None

    b3, a5 = "B3", "A5"
    diffs = []
    for t in tasks:
        mb, ma = task_mean(t, b3), task_mean(t, a5)
        if mb is None or ma is None:
            continue
        diffs.append((t, mb, ma, mb - ma))
    n_plus = sum(1 for d in diffs if d[3] > 0)   # B3 更高
    n_minus = sum(1 for d in diffs if d[3] < 0)  # A5 更高
    n_tie = sum(1 for d in diffs if d[3] == 0)
    p_exact = exact_sign_flip_two_sided(n_plus, n_minus)

    out["paired"] = {
        "unit": "56 tasks (per-task mean over 3 replicates)",
        "B3_pass": arm_pass[b3], "B3_total": arm_total[b3],
        "B3_rate_pct": round(100.0 * arm_pass[b3] / arm_total[b3], 4),
        "A5_pass": arm_pass[a5], "A5_total": arm_total[a5],
        "A5_rate_pct": round(100.0 * arm_pass[a5] / arm_total[a5], 4),
        "B3_minus_A5_pp": round(100.0 * (arm_pass[b3] / arm_total[b3] - arm_pass[a5] / arm_total[a5]), 4),
        "tasks_B3_higher": n_plus, "tasks_A5_higher": n_minus, "tasks_tied": n_tie,
        "exact_sign_flip_two_sided_p": p_exact,
    }

    # ---- 题目级重抽样区间（10000 次，固定种子） ----
    rnd = random.Random(20261024)
    deltas = [d[3] * 100.0 for d in diffs]
    n = len(deltas)
    boots = []
    for _ in range(10000):
        s = 0.0
        for _ in range(n):
            s += deltas[rnd.randrange(n)]
        boots.append(s / n)
    boots.sort()
    lo = boots[int(0.025 * len(boots))]
    hi = boots[min(len(boots) - 1, int(0.975 * len(boots)))]
    out["paired"]["bootstrap_ci95_pp"] = [round(lo, 2), round(hi, 2)]
    out["paired"]["bootstrap_seed"] = 20261024
    out["paired"]["bootstrap_resamples"] = 10000

    # ---- 非零配对差的具体题目 ----
    out["paired"]["nonzero_pairs"] = [
        {"task": t, "B3_mean": round(mb, 4), "A5_mean": round(ma, 4), "diff_pp": round(d * 100, 2)}
        for t, mb, ma, d in diffs if abs(d) > 1e-12
    ]

    # ---- 按 decision_class 的净格分解（逐格配对） ----
    def key(r):
        return (r["task"], r["replicate"])
    b3map = {key(r): r for r in rows if r["arm"] == b3}
    a5map = {key(r): r for r in rows if r["arm"] == a5}
    cls = defaultdict(lambda: {"B3_pass": 0, "B3_total": 0, "A5_pass": 0, "A5_total": 0})
    discord = {"A5_pass_B3_fail": 0, "B3_pass_A5_fail": 0}
    for k in set(b3map) & set(a5map):
        c = b3map[k]["decision_class"]
        bucket = cls[c]
        bucket["B3_total"] += 1; bucket["A5_total"] += 1
        if b3map[k].get("e2e_success"): bucket["B3_pass"] += 1
        if a5map[k].get("e2e_success"): bucket["A5_pass"] += 1
        if a5map[k].get("e2e_success") and not b3map[k].get("e2e_success"): discord["A5_pass_B3_fail"] += 1
        if b3map[k].get("e2e_success") and not a5map[k].get("e2e_success"): discord["B3_pass_A5_fail"] += 1
    out["by_decision_class"] = {c: {**v, "net_cells": v["A5_pass"] - v["B3_pass"]} for c, v in sorted(cls.items())}
    out["discordant_cells"] = discord
    out["discordant_total"] = discord["A5_pass_B3_fail"] + discord["B3_pass_A5_fail"]

    # ---- R21 ----
    r21 = [d for d in diffs if "R21" in d[0]]
    out["R21_task_pairs"] = [
        {"task": t, "B3_mean": round(mb, 4), "A5_mean": round(ma, 4), "diff_pp": round(d * 100, 2)} for t, mb, ma, d in r21
    ]
    out["R21_raw_decisions"] = [
        {"task": r["task"], "replicate": r["replicate"], "arm": r["arm"],
         "decision_class": r["decision_class"],
         "first_decision_check": r["checks"].get("first_decision"),
         "e2e_success": r.get("e2e_success"),
         "failed_checks": [k for k, v in r["checks"].items() if not v]}
        for r in rows if r["arm"] in (b3, a5) and "R21" in r["task"]
    ]

    # ---- 辅助指标：B3 / A5 平均调用与输出 token ----
    usage = {}
    for arm in (b3, a5):
        calls, outtok, tok4096, fmt_fail, done = [], [], 0, 0, 0
        for r in rows:
            if r["arm"] != arm:
                continue
            calls.append(r.get("tool_calls") or 0)
            u = r.get("model_usage") or []
            tot = sum((x.get("outputTokens") or 0) for x in u)
            outtok.append(tot)
            if tot >= 4096: tok4096 += 1
            if r["checks"].get("session_completed"): done += 1
            else: fmt_fail += 1
        usage[arm] = {
            "mean_tool_calls": round(sum(calls) / len(calls), 4),
            "mean_output_tokens": round(sum(outtok) / len(outtok), 4),
            "runs_touching_4096": tok4096,
            "not_completed": fmt_fail,
            "completed": done,
        }
    out["aux_usage"] = usage

    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
