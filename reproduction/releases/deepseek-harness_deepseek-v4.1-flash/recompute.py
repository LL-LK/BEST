from pathlib import Path
from tempfile import TemporaryDirectory
import json
import runpy
import subprocess
import sys

root = Path(__file__).resolve().parent


def invoke(script, *arguments):
    return subprocess.check_output(
        [sys.executable, "-B", "-X", "utf8", str(script), *arguments],
        cwd=root, text=True, encoding="utf-8",
    )


def replay_e2():
    with TemporaryDirectory(prefix="e2-replay-", dir=root) as tmp:
        script = root / "E2" / "reproduce_e2.py"
        receipt = json.loads(invoke(script, "--output", str(Path(tmp) / "replay")).splitlines()[-1])
    return {key: receipt[key] for key in ("units", "cases_passed", "accepted_full_trace_matches")}


def recalculate_e6():
    base = root / "E6"
    cluster_ci = runpy.run_path(str(base / "statistics_e6.py"))["cluster_ci"]
    batches = {}
    for batch, folder in (("original", "original_batch"), ("R3", "r3_recheck")):
        record = json.loads((base / folder / "R3-consistency.json").read_text(encoding="utf-8-sig"))
        tasks = record["per_task"].values()
        metrics = {metric: cluster_ci([task[metric]["point"] for task in tasks])
                   for metric in ("TSC", "PAC_call", "RDC", "FCC")}
        batches[batch] = {"records": sum(task["runs"] for task in tasks),
                          "target": record["coverage"]["record_target"],
                          "tasks_with_five": sum(task["runs"] == 5 for task in tasks),
                          "metrics": metrics}
    return batches


def main():
    data = json.loads(invoke(root / "recompute_core.py"))
    common = {"E2": replay_e2(), "E6": recalculate_e6()}
    if "E1" in data:
        all_experiments = data | common
        result = {name: all_experiments[name] for name in ("E1", "E2", "E3", "E4", "E5", "E6")}
    else:
        result = {"models": data, "shared_experiments": common}
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
