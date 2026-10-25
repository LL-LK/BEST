from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(r"<REPO_ROOT>")
ROOT = Path(__file__).resolve().parent / "run-07"
SCENARIOS = ROOT / "scenarios"
SNAPSHOTS = ROOT / "snapshots"
GOLD = ROOT / "gold"
OUT = ROOT / "preregistration.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_inventory() -> dict[str, str]:
    inventory = {}
    for base in sorted(p for p in SNAPSHOTS.iterdir() if p.is_dir()):
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            relative = path.relative_to(SNAPSHOTS).as_posix()
            inventory[relative] = sha(path)
    return inventory


def check_snapshot_manifests() -> list[str]:
    errors = []
    for directory in (p for p in SNAPSHOTS.rglob("*") if p.is_dir() and (p / "manifest.json").is_file()):
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        declared = manifest.get("files", {})
        actual = {p.relative_to(directory).as_posix(): sha(p)
                  for p in directory.rglob("*") if p.is_file() and p.name != "manifest.json"}
        normalized = {key: str(value).removeprefix("sha256:") for key, value in declared.items()}
        if normalized != actual:
            errors.append(f"snapshot_manifest_mismatch:{directory.relative_to(SNAPSHOTS)}")
    return errors


def main() -> int:
    errors = check_snapshot_manifests()
    scenario_files = sorted(SCENARIOS.glob("*.yaml"))
    gold_files = sorted(GOLD.glob("*.json"))
    if len(scenario_files) != 21:
        errors.append(f"scenario_count:{len(scenario_files)}")
    if len(gold_files) != 21:
        errors.append(f"gold_count:{len(gold_files)}")
    ids = []
    for path in scenario_files:
        scenario = yaml.safe_load(path.read_text(encoding="utf-8"))
        ids.append(scenario["case_id"])
        gold_path = GOLD / f"{scenario['case_id']}.json"
        snapshot_dir = SNAPSHOTS / scenario["snapshot_id"]
        if not gold_path.is_file():
            errors.append(f"missing_gold:{scenario['case_id']}")
            continue
        if not (snapshot_dir / "manifest.json").is_file():
            errors.append(f"missing_snapshot_manifest:{scenario['case_id']}")
            continue
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        expected_fp = "sha256:" + sha(snapshot_dir / "manifest.json")
        if gold.get("snapshot_id") != expected_fp:
            errors.append(f"gold_snapshot_fingerprint_mismatch:{scenario['case_id']}")
    if len(set(ids)) != 21:
        errors.append("duplicate_case_ids")
    large = SNAPSHOTS / "syn_ps1_60000_rows_20261011"
    if sum(1 for _ in (large / "rows_full.csv").open(encoding="utf-8-sig")) - 1 != 60000:
        errors.append("large_fixture_row_count_not_60000")
    if len(list((large / "pages").glob("page_*.csv"))) != 60:
        errors.append("large_fixture_page_count_not_60")
    try:
        from evals.groundtruth.verify_independent import verify_all
        report = verify_all(gold_dir=GOLD, scenarios_dir=SCENARIOS, snapshots_root=SNAPSHOTS)
        if not report.get("pass"):
            errors.append("independent_gold_verification_failed")
    except Exception as exc:
        report = {"error": repr(exc)}
        errors.append("independent_gold_verification_error")
    if errors:
        print(json.dumps({"pre_registration": "BLOCKED", "errors": errors,
                          "independent_verify": report}, ensure_ascii=False, indent=2))
        return 1
    code_paths = [
        REPO / "evals/groundtruth/frozen_runner.py", REPO / "evals/groundtruth/frozen_transport.py",
        REPO / "evals/groundtruth/canonical.py", REPO / "evals/groundtruth/gold/gen_gold.py",
        REPO / "evals/groundtruth/gold/gold_algorithms.py", REPO / "evals/groundtruth/gold/gold_dictionaries.py",
        REPO / "evals/groundtruth/metrics", REPO / "src/client.py", REPO / "src/protocol.py",
        REPO / "src/query_builder.py", REPO / "docs/E2-RERUN-PROTOCOL-v2-2026-10-11.md",
        Path(__file__).resolve().parent / "prepare_assets.py",
        Path(__file__).resolve().parent / "freeze_prereg.py",
        Path(__file__).resolve().parent / "execute_e2_v2.py",
    ]
    code_hashes = {}
    for path in code_paths:
        if path.is_file():
            code_hashes[str(path)] = sha(path)
        else:
            for file in sorted(path.rglob("*.py")):
                code_hashes[str(file)] = sha(file)
    pip_freeze = subprocess.run([sys.executable, "-m", "pip", "freeze"],
                                capture_output=True, text=True, check=False)
    pre = {
        "protocol_version": "E2-FROZEN-v2-2026-10-11",
        "run_id": "e2-v2-" + uuid.uuid4().hex,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "design": {"scenarios": 21, "repeats_per_scenario": 3, "planned_repeats": 63,
                   "lane": "offline_query_aware_snapshot_replay", "confirmatory": True,
                   "transport_errors_inconclusive": False,
                   "retry_policy": "no overwrite; every retry needs a new attempt receipt and cannot replace original"},
        "scenario_manifest": {p.name: sha(p) for p in scenario_files},
        "gold_manifest": {p.name: sha(p) for p in gold_files},
        "snapshot_manifest": snapshot_inventory(),
        "code_hashes": code_hashes,
        "independent_verify": {"pass": report.get("pass"), "n_pass": report.get("n_pass"),
                               "n_cases": report.get("n_cases"), "n_na": report.get("n_na")},
        "environment": {"python": sys.version, "platform": platform.platform(),
                        "pip_freeze": pip_freeze.stdout, "pip_freeze_exit_code": pip_freeze.returncode},
        "limits": ["Dense Field uses 2026-10-04 empirical PS1 capture (1000 rows in 0.5-degree radius); not a globular-cluster core.",
                   "60,000-row stress fixture is synthetic and cannot support a claim that BEST returned 60,000 real rows.",
                   "NULL-vs-ZERO fixture is synthetic; raw CSV bytes and independent oracle are bundled.",
                   "Three retired/unavailable snapshots are replaced with clearly labeled synthetic fixtures.",
                   "Expert double-blind Gold review is not available; do not claim expert-validated Gold."],
    }
    OUT.write_text(json.dumps(pre, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pre_registration": "FROZEN", "run_id": pre["run_id"],
                      "scenario_count": len(scenario_files), "gold_count": len(gold_files),
                      "snapshot_file_count": len(pre["snapshot_manifest"]),
                      "planned_repeats": 63, "independent_verify": pre["independent_verify"],
                      "output": str(OUT)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    raise SystemExit(main())
