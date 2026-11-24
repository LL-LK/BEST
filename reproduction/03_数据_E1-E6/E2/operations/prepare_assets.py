from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

import yaml

REPO = Path(r"<REPO_ROOT>")
GT = REPO / "evals" / "groundtruth"
ROOT = Path(__file__).resolve().parent / "run-07"
SCENARIOS = ROOT / "scenarios"
SNAPSHOTS = ROOT / "snapshots"
GOLD = ROOT / "gold"
REPLACED = {"cone_5as", "huge_3700rows", "sentinel_value"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_manifest(directory: Path) -> None:
    files = {}
    for path in sorted(p for p in directory.rglob("*") if p.is_file() and p.name != "manifest.json"):
        files[path.relative_to(directory).as_posix()] = digest(path)
    (directory / "manifest.json").write_text(
        json.dumps({"files": files, "algorithm": "sha256"}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def copy_snapshot(snapshot_id: str) -> None:
    source = GT / "snapshots" / snapshot_id
    target = SNAPSHOTS / snapshot_id
    if not source.is_dir():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_dense() -> dict:
    snapshot_id = "dense_field_empirical_ps1_20261004"
    source_id = "live-2026-10-04/live_ps1_ra359.5_dec0.0_r1800.0as"
    target = SNAPSHOTS / snapshot_id
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(GT / "snapshots" / source_id, target,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    meta_path = target / "snapshot.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta["snapshot_id"] = snapshot_id
    meta["source_snapshot_id"] = source_id
    meta["density_definition"] = "1000 captured rows in a 1800 arcsec radius; 1273.24 rows/deg^2"
    meta_path.write_text(yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8")
    snapshot_manifest(target)
    return {
        "case_id": "dense_field",
        "category": "dense_field",
        "snapshot_id": snapshot_id,
        "main_metrics": ["M1", "M2", "M4", "M7"],
        "query": {
            "catalog": "ps1", "ra": 359.5, "dec": 0.0, "radius_arcsec": 1800.0,
            "columns": ["ps1_source_id", "ps1_ra", "ps1_dec", "ps1_rpsf"],
            "sort": "ps1_ra", "order": "asc", "max_rows": 1000, "page_size": 1000,
        },
        "expect": {"result_state": "rows"},
        "notes": "置换 cone_5as 槽。实抓 L 类 PS1 快照，来源为 2026-10-04 实站捕获；1000 行 / 0.7854 deg^2。不是球状星团核心样本，不声称天体物理密集星团验证。",
        "replacement_slot": "cone_5as",
        "gold_focus": "高返回量 PS1 场的主键、排序与分页不变量",
    }


def build_small_fixture(snapshot_id: str, columns: list[str], rows: list[dict[str, str]],
                        data_version: str, note: str) -> None:
    directory = SNAPSHOTS / snapshot_id
    directory.mkdir(parents=True, exist_ok=True)
    if rows:
        write_csv(directory / "rows_full.csv", columns, rows)
        write_csv(directory / "pages" / "page_0001.csv", columns, rows)
    else:
        (directory / "pages").mkdir(exist_ok=True)
        (directory / "pages" / "page_0001.csv").write_text("", encoding="utf-8")
    (directory / "phase1.html").write_text('<script>url:"/data/best/sqlid/s0002?output.fmt=dbgrid"</script>', encoding="utf-8")
    (directory / "count.json").write_text(json.dumps({"total": len(rows)}) + "\n", encoding="utf-8")
    meta = {"snapshot_id": snapshot_id, "kind": "S", "material_class": "synthetic-protocol-fixture",
            "catalog": "ps1", "columns": columns, "row_count": len(rows), "data_version": data_version,
            "page_size": 1000, "sort_key": columns[0] if columns else None, "fetched_at": "2026-10-11",
            "note": note}
    (directory / "snapshot.yaml").write_text(yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8")
    snapshot_manifest(directory)


def build_missing_snapshots() -> None:
    pole_cols = ["ps1_source_id", "ps1_ra", "ps1_dec", "ps1_rpsf"]
    pole_rows = [{"ps1_source_id": f"POLE_SYN_{i:02d}", "ps1_ra": f"{i * 31.0:.6f}",
                  "ps1_dec": f"{89.990 + i * 0.0010:.6f}", "ps1_rpsf": f"{17.0 + i / 10:.1f}"}
                 for i in range(8)]
    build_small_fixture("syn_pole_boundary", pole_cols, pole_rows, "synthetic@2026-10-11",
                        "合成天极几何 fixture；用于RA收敛/haversine解析压力，不是真实天极观测。")
    exact_page_rows = [{"ps1_source_id": f"PAGE_SYN_{i:04d}", "ps1_ra": f"180.0{i%10:01d}",
                        "ps1_dec": "30.000000", "ps1_rpsf": f"{16 + (i%100)/100:.2f}"}
                       for i in range(1000)]
    build_small_fixture("syn_exact_page_1000", ["ps1_source_id", "ps1_ra", "ps1_dec", "ps1_rpsf"],
                        exact_page_rows, "synthetic@2026-10-11",
                        " exactly 1000 rows, synthetic page-boundary fixture; not a live service capture.")
    exact_cols = ["gaiaxp_photinfo_replenish_source_id", "gaiaxp_photinfo_replenish_ra",
                  "gaiaxp_photinfo_replenish_dec", "gaiaxp_photinfo_replenish_bp_mag",
                  "gaiaxp_photinfo_replenish_ruwe", "correctedxpspecv1_c2"]
    exact_rows = [{"gaiaxp_photinfo_replenish_source_id": "SYNTHETIC_XMATCH_0001",
                   "gaiaxp_photinfo_replenish_ra": "180.076750000", "gaiaxp_photinfo_replenish_dec": "30.001238000",
                   "gaiaxp_photinfo_replenish_bp_mag": "15.492219", "gaiaxp_photinfo_replenish_ruwe": "1.1094214",
                   "correctedxpspecv1_c2": "0.28823552"}]
    build_small_fixture("syn_single_exact", exact_cols, exact_rows, "synthetic@2026-10-11",
                        "合成精确ID匹配fixture；取代缺失的旧dr3xpcorr快照，不代表实站样本。")
    build_small_fixture("syn_no_request", [], [], "synthetic@2026-10-11",
                        "参数校验场景不应发HTTP请求；本快照仅供M6来源字段占位。")
    soft = SNAPSHOTS / "syn_soft404"
    soft.mkdir(parents=True, exist_ok=True)
    (soft / "pages").mkdir(exist_ok=True)
    (soft / "phase1.html").write_text('{"error":"Not Found"}', encoding="utf-8")
    (soft / "count.json").write_text('{"total":0}\n', encoding="utf-8")
    (soft / "snapshot.yaml").write_text(yaml.safe_dump(
        {"snapshot_id": "syn_soft404", "kind": "S", "material_class": "synthetic-soft404",
         "catalog": "ps1", "row_count": 0, "data_version": "synthetic@2026-10-11",
         "page_size": 1000, "note": "合成HTTP200软404协议回包，用于客户端错误态识别。"},
        allow_unicode=True, sort_keys=False), encoding="utf-8")
    snapshot_manifest(soft)


def build_large() -> dict:
    snapshot_id = "syn_ps1_60000_rows_20261011"
    directory = SNAPSHOTS / snapshot_id
    pages = directory / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    columns = ["ps1_source_id", "ps1_ra", "ps1_dec", "ps1_rpsf"]
    all_rows = []
    for i in range(60000):
        all_rows.append({
            "ps1_source_id": f"BEST_SYN_{i:06d}",
            "ps1_ra": f"{180.0 + (i % 1000) * 0.00001:.8f}",
            "ps1_dec": f"{30.0 + (i // 1000) * 0.000001:.8f}",
            "ps1_rpsf": "-999.0" if i % 5000 == 4999 else f"{16 + (i % 500) / 100:.2f}",
                    })
    write_csv(directory / "rows_full.csv", columns, all_rows)
    for offset in range(0, len(all_rows), 1000):
        write_csv(pages / f"page_{offset // 1000 + 1:04d}.csv", columns, all_rows[offset:offset + 1000])
    (directory / "phase1.html").write_text('<script>url:"/data/best/sqlid/s0002?output.fmt=dbgrid"</script>', encoding="utf-8")
    (directory / "count.json").write_text('{"total": 60000}\n', encoding="utf-8")
    meta = {
        "snapshot_id": snapshot_id, "kind": "S", "material_class": "synthetic-protocol-stress",
        "catalog": "ps1", "columns": columns, "row_count": 60000, "data_version": "synthetic@2026-10-11",
        "page_size": 1000, "sort_key": "ps1_source_id", "fetched_at": "2026-10-11",
        "query": {"catalog": "ps1", "ra": 180.0, "dec": 30.0, "radius_arcsec": 1800.0, "max_rows": 50000},
        "note": "确定性合成协议负载；用于客户端解析/50页截断压力，不代表BEST站点真实返回60000行。",
    }
    (directory / "snapshot.yaml").write_text(yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8")
    snapshot_manifest(directory)
    return {
        "case_id": "large_60000_rows", "category": "huge", "snapshot_id": snapshot_id,
        "main_metrics": ["M1", "M2", "M4", "M7"],
        "query": {"catalog": "ps1", "ra": 180.0, "dec": 30.0, "radius_arcsec": 1800.0,
                  "columns": columns, "sort": "ps1_source_id", "order": "asc",
                  "max_rows": 50000, "page_size": 1000},
        "expect": {"result_state": "rows"},
        "notes": "置换 huge_3700rows 槽。60,000 行、60 个1000行页的确定性合成压力数据；查询上限50,000，期望返回50页并报告total=60000/truncated=true。不得写成实站60,000行结果。",
        "replacement_slot": "huge_3700rows", "gold_focus": "60页全量真值、截断三元组与50页返回上限",
    }


def build_null_zero() -> dict:
    snapshot_id = "syn_null_zero_twins_20261011"
    directory = SNAPSHOTS / snapshot_id
    columns = ["ps1_source_id", "ps1_ra", "ps1_dec", "ps1_rpsf", "ps1_gpsf", "ps1_class_star"]
    rows = [
        {"ps1_source_id": "BEST_NZ_0001", "ps1_ra": "180.000100000", "ps1_dec": "30.000100000", "ps1_rpsf": "18.20", "ps1_gpsf": "-1004.0910078678945", "ps1_class_star": "0.990"},
        {"ps1_source_id": "BEST_NZ_0002", "ps1_ra": "180.000200000", "ps1_dec": "30.000200000", "ps1_rpsf": "", "ps1_gpsf": "-999.0", "ps1_class_star": ""},
        {"ps1_source_id": "BEST_NZ_0003", "ps1_ra": "180.000300000", "ps1_dec": "30.000300000", "ps1_rpsf": "17.90", "ps1_gpsf": "18.05", "ps1_class_star": "0.0"},
    ]
    directory.mkdir(parents=True, exist_ok=True)
    write_csv(directory / "rows_full.csv", columns, rows)
    write_csv(directory / "pages" / "page_0001.csv", columns, rows)
    (directory / "phase1.html").write_text('<script>url:"/data/best/sqlid/s0002?output.fmt=dbgrid"</script>', encoding="utf-8")
    (directory / "count.json").write_text('{"total": 3}\n', encoding="utf-8")
    meta = {"snapshot_id": snapshot_id, "kind": "S", "material_class": "synthetic-null-zero-twins",
            "catalog": "ps1", "columns": columns, "row_count": 3, "data_version": "synthetic@2026-10-11",
            "page_size": 1000, "sort_key": "ps1_source_id", "fetched_at": "2026-10-11",
            "query": {"catalog": "ps1", "ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0, "max_rows": 1000},
            "paired_cells": [{"column": "ps1_class_star", "null_key": "BEST_NZ_0002", "zero_key": "BEST_NZ_0003"}],
            "note": "同列ps1_class_star含原始空单元与字面0.0；保留CSV原始字节，语义双生夹具。"}
    (directory / "snapshot.yaml").write_text(yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8")
    snapshot_manifest(directory)
    return {
        "case_id": "null_zero_twins", "category": "missing_field", "snapshot_id": snapshot_id,
        "main_metrics": ["M2", "M5"],
        "query": {"catalog": "ps1", "ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0,
                  "columns": columns, "max_rows": 1000, "page_size": 1000},
        "expect": {"result_state": "rows"},
        "notes": "置换 sentinel_value 槽。ps1_class_star 的BEST_NZ_0002原始空值必须为null，BEST_NZ_0003的字面0.0必须保留为数值零；ps1_gpsf哨兵同时保留作第三语义类别。",
        "replacement_slot": "sentinel_value", "gold_focus": "NULL与0.0同列双向不冒充，哨兵独立分类",
    }


def main() -> None:
    SCENARIOS.mkdir(parents=True)
    SNAPSHOTS.mkdir(parents=True)
    GOLD.mkdir(parents=True)
    build_missing_snapshots()
    for scenario_file in sorted((GT / "scenarios").glob("*.yaml")):
        scenario = yaml.safe_load(scenario_file.read_text(encoding="utf-8"))
        if scenario["case_id"] in REPLACED:
            continue
        remap = {
            "boundary_pole_dec": "syn_pole_boundary",
            "single_exact": "syn_single_exact",
            "soft404_page": "syn_soft404",
            "missing_arg_catalog": "syn_no_request",
            "missing_arg_coords": "syn_no_request",
            "missing_arg_radius": "syn_no_request",
        }
        if scenario["case_id"] in remap:
            scenario["snapshot_id"] = remap[scenario["case_id"]]
        if scenario["case_id"] == "huge_batch_1000":
            scenario["snapshot_id"] = "syn_batch_proximity_1000"
            batch_dir = SNAPSHOTS / scenario["snapshot_id"]
            inputs = scenario["query"]["inputs"]
            columns = ["inputobjs_input_line", "inputobjs_input_ra", "inputobjs_input_dec",
                       "inputobjs_dist_arcsec", "ps1_source_id", "ps1_ra", "ps1_dec", "ps1_rpsf"]
            rows = [{"inputobjs_input_line": str(i + 1), "inputobjs_input_ra": str(point["ra"]),
                     "inputobjs_input_dec": str(point["dec"]), "inputobjs_dist_arcsec": "0.0",
                     "ps1_source_id": f"BATCH_SYN_{i:04d}", "ps1_ra": str(point["ra"]),
                     "ps1_dec": str(point["dec"]), "ps1_rpsf": f"{16 + (i % 100) / 100:.2f}"}
                    for i, point in enumerate(inputs)]
            build_small_fixture(scenario["snapshot_id"], columns, rows, "synthetic@2026-10-11",
                                "1000 synthetic one-to-one proximity matches; replaces a mismatched cone-search capture.")
            scenario["notes"] = "1000 synthetic input/match pairs, deterministic; the archived 1000-row cone snapshot was not a valid proximity truth set."
        if scenario["case_id"] == "boundary_page_exact":
            scenario["snapshot_id"] = "syn_exact_page_1000"
            scenario["query"].update({"catalog": "ps1", "ra": 180.0, "dec": 30.0,
                                      "radius_arcsec": 3600.0, "columns": ["ps1_source_id", "ps1_ra", "ps1_dec", "ps1_rpsf"],
                                      "sort": "ps1_ra", "order": "asc", "max_rows": 1500, "page_size": 1000})
            scenario["notes"] = "1000-row synthetic exact-full-page boundary; max_rows=1500 requires terminal empty page validation."
        if scenario["case_id"] == "single_exact":
            scenario["query"]["source_id"] = "SYNTHETIC_XMATCH_0001"
        if scenario["case_id"] == "soft404_page":
            scenario["query"]["catalog"] = "ps1"
            scenario["notes"] = "synthetic phase-1 HTTP 200 + {error: Not Found} response; catalog remains valid so client reaches the parser."
        (SCENARIOS / scenario_file.name).write_text(yaml.safe_dump(scenario, allow_unicode=True, sort_keys=False), encoding="utf-8")
        snapshot_id = scenario["snapshot_id"]
        if not (SNAPSHOTS / snapshot_id).exists() and (GT / "snapshots" / snapshot_id).is_dir():
            copy_snapshot(snapshot_id)
    replacements = [build_dense(), build_large(), build_null_zero()]
    for scenario in replacements:
        out = SCENARIOS / f"{scenario['case_id']}.yaml"
        out.write_text(yaml.safe_dump(scenario, allow_unicode=True, sort_keys=False), encoding="utf-8")
    files = sorted(SCENARIOS.glob("*.yaml"))
    if len(files) != 21:
        raise AssertionError(f"expected 21 scenarios, got {len(files)}")
    for directory in (p for p in SNAPSHOTS.rglob("*") if p.is_dir() and (p / "manifest.json").is_file()):
        snapshot_manifest(directory)
    print(json.dumps({"scenario_count": len(files), "scenario_ids": [yaml.safe_load(p.read_text(encoding='utf-8'))['case_id'] for p in files],
                      "snapshot_count": len(list(SNAPSHOTS.iterdir())), "replacements": [x['case_id'] for x in replacements]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
