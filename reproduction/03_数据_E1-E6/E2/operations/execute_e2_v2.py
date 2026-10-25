from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(r"<REPO_ROOT>")
ROOT = Path(__file__).resolve().parent / "run-07"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from evals.groundtruth import frozen_runner


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    prereg_path = ROOT / "preregistration.json"
    report_path = ROOT / "results.json"
    trace_path = ROOT / "trace.jsonl"
    if not prereg_path.is_file():
        raise SystemExit("missing pre-registration; refuse to run")
    if report_path.exists() or trace_path.exists():
        raise SystemExit("run outputs already exist; refusing to overwrite")
    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    expected_hash = prereg["code_hashes"].get(str(REPO / "evals/groundtruth/frozen_runner.py"))
    if expected_hash != sha(REPO / "evals/groundtruth/frozen_runner.py"):
        raise SystemExit("frozen runner hash differs from pre-registration")
    expected_transport = prereg["code_hashes"].get(str(REPO / "evals/groundtruth/frozen_transport.py"))
    if expected_transport != sha(REPO / "evals/groundtruth/frozen_transport.py"):
        raise SystemExit("frozen transport hash differs from pre-registration")
    frozen_runner.SNAPSHOTS_DIR = ROOT / "snapshots"
    frozen_runner.GOLD_DIR = ROOT / "gold"
    frozen_runner.SCENARIOS_DIR = ROOT / "scenarios"
    started = datetime.now(timezone.utc)
    started_perf = time.perf_counter()
    report = frozen_runner.run(scenarios_dir=ROOT / "scenarios", repeat=3)
    elapsed = time.perf_counter() - started_perf
    ended = datetime.now(timezone.utc)
    planned = 63
    actual_repeats = len({(event.get("case_id"), event.get("repeat_index")) for event in report.get("trace_events", [])})
    report.update({"run_id": prereg["run_id"], "protocol_version": prereg["protocol_version"],
                   "planned_repeats": planned, "actual_repeats": actual_repeats,
                   "coverage_complete": report.get("n_cases") == 21 and actual_repeats == planned,
                   "elapsed_seconds": elapsed,
                   "started_at_utc": started.isoformat(), "ended_at_utc": ended.isoformat(),
                   "preregistration_sha256": sha(prereg_path)})
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with trace_path.open("w", encoding="utf-8", newline="\n") as f:
        for event in report.get("trace_events", []):
            f.write(json.dumps({"run_id": prereg["run_id"], **event}, ensure_ascii=False) + "\n")
    (ROOT / "exit-code.txt").write_text(("0" if report["pass"] and report["coverage_complete"] else "1") + "\n", encoding="utf-8")
    (ROOT / "run-summary.md").write_text(frozen_runner.render_markdown(report) +
        f"\n\n- protocol: `{report['protocol_version']}`\n- run_id: `{report['run_id']}`\n"
        f"- repeats: {actual_repeats}/{planned}\n- complete: {report['coverage_complete']}\n"
        f"- elapsed: {elapsed:.2f}s\n- preregistration SHA-256: `{report['preregistration_sha256']}`\n",
        encoding="utf-8")
    print(json.dumps({"run_id": report["run_id"], "pass": report["pass"],
                      "n_cases": report["n_cases"], "n_pass": report["n_pass"],
                      "actual_repeats": actual_repeats, "planned_repeats": planned,
                      "coverage_complete": report["coverage_complete"],
                      "metascore": report["metascore"], "elapsed_seconds": elapsed,
                      "results": str(report_path), "trace": str(trace_path)},
                     ensure_ascii=False, indent=2))
    return 0 if report["pass"] and report["coverage_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
