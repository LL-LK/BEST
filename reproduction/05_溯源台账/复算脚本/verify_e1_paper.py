"""Recompute the paper E1 scores from the 2026-10-20 regraded records."""

import json
import math
from pathlib import Path
from statistics import mean


SOURCE = Path(__file__).resolve().parents[2] / "03_数据_E1-E6/E1/v55_重新判分_20261020"
WEIGHTS = {"toolset": .30, "param": .25, "convert": .15, "redundant": .10, "clarify": .10, "reject": .10}


def score_round(repeat):
    path = SOURCE / f"E1_sb{repeat}.json"
    grade = json.loads(path.read_text(encoding="utf-8-sig"))
    tasks = {row["task_id"]: row["dims"] for row in grade["task_grades"]}
    if len(tasks) != 28 or len(grade["task_grades"]) != 28:
        raise ValueError(f"Expected 28 distinct E1 tasks in {path.name}")
    dimensions = {}
    eligible = {}
    for name in WEIGHTS:
        used = [row[name] for row in tasks.values() if row[name] is not None]
        eligible[name] = len(used)
        dimensions[name] = mean(used) if used else None
    active = [name for name, value in dimensions.items() if value is not None]
    weighted = sum(WEIGHTS[name] * dimensions[name] for name in active) / sum(WEIGHTS[name] for name in active)
    if eligible != grade["dim_n"] or not math.isclose(weighted, grade["weighted"], rel_tol=0, abs_tol=1e-12):
        raise ValueError(f"Recomputed E1 score disagrees with {path.name}")
    return set(tasks), {"round": repeat, "weighted": weighted, "dimensions": dimensions, "eligible": eligible}


def main():
    rounds = [score_round(repeat) for repeat in (1, 2, 3)]
    if any(task_set != rounds[0][0] for task_set, _ in rounds):
        raise ValueError("The three E1 rounds use different task IDs")
    rows = [round_data for _, round_data in rounds]
    print(json.dumps({"scoring": "2026-10-20 regrade", "n_tasks": 28, "rounds": rows,
                      "weighted_mean": mean(row["weighted"] for row in rows)}, indent=2))


if __name__ == "__main__":
    main()
