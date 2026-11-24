"""Recompute the paper from frozen E1–E6 records and the v15 paired score table."""

import argparse
from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path
import runpy
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
REPRO = ROOT / "reproduction"
EXPERIMENTS = REPRO / "03_数据_E1-E6"
LEDGER = REPRO / "05_溯源台账" / "复算脚本"
ROUNDS = ("sb1", "sb2", "sb3")
METRICS = ("TSC", "PAC_call", "RDC", "FCC")


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def command_json(path):
    output = subprocess.check_output([sys.executable, "-B", str(path)], encoding="utf-8")
    return json.loads(output)


def crossmatch(path):
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    pairs = {"primary": defaultdict(dict), "diagnostic": defaultdict(dict)}
    strata = {}
    for row in rows:
        lane, arm, label = row["lane"], row["arm"], row["success"]
        pair = pairs[lane][row["pair_id"]]
        if arm not in ("B2b", "B3_compact") or arm in pair or label not in ("0", "1"):
            raise ValueError(f"Invalid v15 row for {row['pair_id']}")
        pair[arm] = int(label)
        if lane == "primary" and strata.setdefault(row["pair_id"], row["stratum"]) != row["stratum"]:
            raise ValueError(f"Mismatched strata for {row['pair_id']}")
    main, diag = pairs["primary"], pairs["diagnostic"]
    if len(main) != 1024 or len(diag) != 96 or set(main) & set(diag):
        raise ValueError("Expected 1,024 primary and 96 separate diagnostic pairs")
    if any(len(pair) != 2 for lane in pairs.values() for pair in lane.values()):
        raise ValueError("Both arms are required for every v15 pair")
    only_baseline = sum(p["B2b"] > p["B3_compact"] for p in main.values())
    only_compact = sum(p["B2b"] < p["B3_compact"] for p in main.values())
    discordant = only_baseline + only_compact
    tail = sum(math.comb(discordant, i) for i in range(min(only_baseline, only_compact) + 1))
    differences = defaultdict(list)
    for key, pair in sorted(main.items()):
        differences[strata[key]].append(pair["B3_compact"] - pair["B2b"])
    rng = np.random.default_rng(2026101913)
    bootstrap = np.zeros(10_000)
    for _, values in sorted(differences.items()):
        samples = rng.integers(0, len(values), size=(10_000, len(values)))
        bootstrap += np.asarray(values)[samples].sum(axis=1)
    contrasts = {
        "only_B2b": only_baseline, "only_B3_compact": only_compact,
        "delta": (only_compact - only_baseline) / len(main),
        "bootstrap_95": np.quantile(bootstrap / len(main), [0.025, 0.975]).tolist(),
        "p_exact_two_sided": min(1.0, 2 * tail / 2**discordant),
    }
    return {
        "batch": "v15", "score_rows": len(rows), "primary_pairs": len(main),
        "diagnostic_pairs": len(diag),
        "primary_success": {a: sum(p[a] for p in main.values()) for a in ("B2b", "B3_compact")},
        "diagnostic_success": {a: sum(p[a] for p in diag.values()) for a in ("B2b", "B3_compact")},
        "primary_contrast": contrasts,
    }


def e3():
    base = EXPERIMENTS / "E3"
    with (base / "01_当前结果" / "E3-逐回答计数.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    design = load(base / "05_原始实验归档" / "bundle.json")
    fields = ("critical_hit", "critical_total", "qualifier_hit", "qualifier_total",
              "numbers_total", "unsourced_num", "claims_total", "unsupported_claim", "fatal_num",
              "static_as_lc")
    fixture = [
        {"group": r["group"], "item_id": r["item_id"], "repeat": int(r["repeat"]),
         "counts": {**{f: int(r[f]) for f in fields}, "pass": r["pass"] == "True"}}
        for r in rows if r["tier"] == "fixture"
    ]
    items = [i["id"] for i in design["items"] if i["tier"] == "fixture"]
    stats = runpy.run_path(str(base / "statistics_e3.py"))
    summary = stats["summarize"](fixture, items, design["slr_ids"])
    return {
        "fixture_answers": len(fixture), "online_answers": len(rows) - len(fixture),
        "offline": summary,
    }


def e4():
    base = (EXPERIMENTS / "E4" / "v70_E4重跑_20261023" / "work" / "E4_input" / "_复现" / "out")
    grade = load(base / "grade_r2.json")
    protocol = load(base / "official-tierW.json")["W"]["cases"]
    category_total, category_success = Counter(), Counter()
    rounds = {}
    for key in ROUNDS:
        rows = grade[key]["P"]
        relevant = [r for r in rows if r["weighted"] is not None]
        rounds[key] = {
            "ordinary_correct": sum(r["disposal_ok"] for r in rows), "ordinary_n": len(rows),
            "weighted_pass": sum(r["pass"] for r in relevant), "weighted_n": len(relevant),
        }
        for row in rows:
            want = row["want_disposal"]
            label = want[0] if isinstance(want, list) else want
            category_total[label] += 1
            category_success[label] += int(row["disposal_ok"])
    return {
        "protocol_correct": sum(r["pass"] for r in protocol), "protocol_n": len(protocol),
        "rounds": rounds,
        "category": {k: {"correct": category_success[k], "total": n} for k, n in sorted(category_total.items())},
    }


def e6():
    base = EXPERIMENTS / "E6"
    cluster_ci = runpy.run_path(str(base / "statistics_e6.py"))["cluster_ci"]
    results = {}
    for name, folder in (("original", "02_原批次结果与原始归档"), ("R3", "01_当前R3补测")):
        data = load(base / folder / "R3-consistency.json")
        scores = {metric: cluster_ci([t[metric]["point"] for t in data["per_task"].values()]) for metric in METRICS}
        for metric, values in scores.items():
            reference = data["aggregate"][metric]
            if (not math.isclose(values["point"], reference["point"], abs_tol=1e-12)
                    or values["task_units"] != reference["task_units"]
                    or any(abs(x - y) > 1e-12 for x, y in zip(values["bootstrap_95"], reference["bootstrap_95"], strict=True))):
                raise ValueError(f"E6 {name} {metric} differs from its archived aggregate")
        results[name] = {
            "records": sum(task["runs"] for task in data["per_task"].values()),
            "target": data["coverage"]["record_target"],
            "tasks_with_five": sum(task["runs"] == 5 for task in data["per_task"].values()),
            "metrics": scores,
        }
    return results


def e5():
    rows = load(EXPERIMENTS / "E5" / "scores.json")
    tasks = {r["task"] for r in rows}
    arms = {r["arm"] for r in rows}
    keys = {(r["task"], r["arm"], r["replicate"]) for r in rows}
    expected = {(t, a, r) for t in tasks for a in arms for r in (1, 2, 3)}
    if len(tasks) != 56 or len(arms) != 12 or len(rows) != len(keys) or keys != expected:
        raise ValueError("Expected the complete 56 × 12 × 3 E5 score matrix")
    contrasts = command_json(LEDGER / "verify_e5_contrasts.py")
    return {**contrasts, "scored_cells": len(keys), "paper_cells": sum(a != "sham" for _, a, _ in keys)}


def check(results):
    paper = results["E4"]
    rounds = list(paper["rounds"].values())
    if [r["ordinary_correct"] for r in rounds] != [34, 35, 34] or any(r["ordinary_n"] != 35 for r in rounds):
        raise ValueError("E4 ordinary results differ from the paper")
    if ([r["weighted_pass"] for r in rounds], [r["weighted_n"] for r in rounds]) != ([8, 13, 10], [18, 21, 16]):
        raise ValueError("E4 weighted results differ from the paper")
    if (paper["protocol_correct"], paper["protocol_n"]) != (15, 15):
        raise ValueError("E4 protocol results differ from the paper")
    e3_result = results["E3"]
    ci = e3_result["offline"]["sfa_difference"]["bootstrap_95"]
    if (e3_result["fixture_answers"], e3_result["online_answers"]) != (192, 24) or [round(v * 100, 2) for v in ci] != [12.68, 33.33]:
        raise ValueError("E3 results differ from the paper")
    if not math.isclose(results["E1"]["weighted_mean"], 0.9529761904761905, abs_tol=1e-12):
        raise ValueError("E1 result differs from the paper")
    primary = results["E5"]["primary_B3_minus_B2b"]
    if (round(primary["delta_pp"], 2), round(primary["p_exact_paired_sign_flip"], 5)) != (7.14, 0.08848):
        raise ValueError("E5 primary comparison differs from the paper")
    v15 = results["crossmatch"]
    if v15["primary_success"] != {"B2b": 999, "B3_compact": 995} or (
            v15["primary_contrast"]["only_B2b"], v15["primary_contrast"]["only_B3_compact"]) != (22, 18):
        raise ValueError("v15 primary comparison differs from the paper")
    if v15["primary_contrast"]["bootstrap_95"] != [-0.015625, 0.0078125]:
        raise ValueError("v15 paired bootstrap interval differs from the archived analysis")
    if results["E6"]["R3"]["records"] != 133:
        raise ValueError("E6 valid records differ from the paper")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("paper-results.json"))
    parser.add_argument("--e2-replay", type=Path, help="Run all 63 E2 replays into this new directory")
    args = parser.parse_args()
    e2 = [sys.executable, "-B", str(EXPERIMENTS / "E2" / "reproduce_e2.py")]
    e2 += ["--output", str(args.e2_replay)] if args.e2_replay else ["--verify-only"]
    # The E2 script prints diagnostics before its final JSON receipt.
    e2_receipt = json.loads(subprocess.check_output(e2, encoding="utf-8", errors="replace").splitlines()[-1])
    results = {
        "E1": command_json(LEDGER / "verify_e1_paper.py"), "E2": e2_receipt,
        "E3": e3(), "E4": e4(), "E5": e5(),
        "crossmatch": crossmatch(Path(__file__).with_name("crossmatch-v15.csv")), "E6": e6(),
    }
    check(results)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Verified E1–E6 and v15; wrote {args.output}")


if __name__ == "__main__":
    main()
