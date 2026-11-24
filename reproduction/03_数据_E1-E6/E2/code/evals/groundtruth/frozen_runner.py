# -*- coding: utf-8 -*-
"""E2 v2 frozen-lane runner, kept separate from the live-gate runner.

能力边界: 编排件 — 对每个场景把被测客户端接到 SnapshotTransport (回放,
rate_limit=0.0), 跑真实查询路径, 收集规范化结果与信封/provenance/请求计数,
调 metrics 对账, 汇总报告。边界: 一律离线回放 (零真实站点请求); 退出码
沿用 eval_runner 约定 (0 全过 / 1 有 fail)。

白盒锚点: docs/eval-E2-groundtruth.md §9 (执行流程与产物) / §10 (阻断项);
evals/groundtruth/transport.py (回放接线, E2 §3.3)。
"""
from __future__ import annotations

# 标准库: 参数/JSON/hash/路径
import argparse
import hashlib
import json
import sys
from pathlib import Path

# 本地: 中立载体 + canonical/transport/metrics。
# 脚本直跑 (`python evals/groundtruth/run_e2.py`) 时 sys.path[0] 只含本目录 —
# 同时挂 skill 根 (供 evals.* 命名空间包) 与 evals/ (供 paths 兄弟裸导入)。
_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))   # evals/ (paths 兄弟裸导入)
sys.path.insert(0, str(_HERE.parents[2]))   # skill 根 (evals.* 命名空间包)
from paths import load_yaml_file  # noqa: E402

from evals.groundtruth.canonical import (  # noqa: E402
    from_query_result,
)
from evals.groundtruth.metrics import compare_case, metascore  # noqa: E402
from evals.groundtruth.frozen_transport import QueryAwareTransport  # noqa: E402

PROTOCOL_VERSION = "E2-FROZEN-v2-2026-10-11"
ACTIVE_TRACE: list[dict] = []

GT_DIR = Path(__file__).resolve().parent
SNAPSHOTS_DIR = GT_DIR / "snapshots"
SCENARIOS_DIR = GT_DIR / "scenarios"
GOLD_DIR = GT_DIR / "gold"


def _sha256_obj(obj) -> str:
    """对象的确定性 sha256 (排序键 JSON; data_hash 的口径)。"""
    return "sha256:" + hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def load_scenario(path: Path) -> dict:
    """读场景 YAML (快照 id + 查询参数 + 期望状态)。"""
    scenario = load_yaml_file(path)
    for key in ("case_id", "snapshot_id", "query"):
        if key not in scenario:
            raise ValueError(f"场景缺必需字段 {key}: {path}")
    return scenario


def wire_client(snap_dir: Path):
    """被测客户端接快照回放 (E2 §3.3: rate_limit 必须归零, 否则回放睡死)。

    默认用 ``QueryAwareTransport`` (查询语义模拟): 场景自带查询参数, 按
    表单键对 rows_full 独立执行 — 快照冻结查询与场景查询不一致时对账仍成立。
    """
    from src.client import BestClient

    transport = QueryAwareTransport(snap_dir)
    client = BestClient(base_url="http://snapshot.local", rate_limit=0.0)
    client.session.get = transport.get
    client.session.post = transport.post
    return client, transport


def _snapshot_data_version(snap_dir: Path) -> str | None:
    """读快照的 data_version (M6 版本对账的 actual 侧来源)。"""
    meta = snap_dir / "snapshot.yaml"
    if not meta.is_file():
        return None
    data = load_yaml_file(meta)
    return data.get("data_version")


def _consumed_pages(pages: list[list[dict]], returned_count: int) -> list[list[dict]]:
    """Page evidence for rows accepted by the client; raw page bytes remain hash-traced."""
    remaining = max(0, int(returned_count))
    consumed = []
    for page in pages:
        if remaining <= 0:
            break
        accepted = [dict(row) for row in page[:remaining]]
        if accepted:
            consumed.append(accepted)
            remaining -= len(accepted)
    return consumed


def run_scenario_once(scenario: dict) -> dict:
    """回放跑一次查询, 返回规范化结果 + 信封 + provenance + 请求计数。

    查询翻译 (场景 YAML → client.query 实参):
      - ``source_id`` 且无 ra/dec → 转 equal 列约束 (BEST 无按 id 取源端点,
        E1 已确立; 列名按 ``{catalog}_source_id`` 拼真实投影列);
      - 期望 result_state=error 的场景: 客户端抛错即被测行为本身 —
        捕获后转成 ERROR 态信封 (M5 判据: 拒绝必须显式, 不得降级空结果)。
    """
    snap_dir = SNAPSHOTS_DIR / scenario["snapshot_id"]
    client, transport = wire_client(snap_dir)
    query = scenario.get("query") or {}
    catalog = query.get("catalog", "ps1")
    constraints = list(query.get("constraints") or [])
    if query.get("source_id") and not query.get("ra"):
        constraints.append({
            "name": query.get("source_id_column") or f"{catalog}_source_id",
            "op": "equal",
            "value": str(query["source_id"]),
        })
    manifest = snap_dir / "manifest.json"
    snapshot_fingerprint = ("sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()
                            if manifest.is_file() else "sha256:manifest-missing")
    provenance = {
        "snapshot_id": snapshot_fingerprint,
        "data_version": _snapshot_data_version(snap_dir),
        "catalog": catalog,
        "endpoint": f"/data/best/{catalog}/q",
    }
    try:
        if query.get("inputs"):
            # 批量匹配场景: inputs → crossmatch_batch (服务端 proximity 一次提交)
            inputs = query["inputs"]
            result = client.crossmatch_batch(
                ra_list=[float(i["ra"]) for i in inputs],
                dec_list=[float(i["dec"]) for i in inputs],
                catalog=catalog,
                radius_arcsec=float(query.get("radius_arcsec", 3.0)),
                columns=query.get("columns"),
                max_rows=int(query.get("max_rows", 50000)),
            )
        else:
            result = client.query_result(
                catalog=catalog,
                constraints=constraints,
                ra=query.get("ra"),
                dec=query.get("dec"),
                radius_arcsec=query.get("radius_arcsec"),
                max_rows=int(query.get("max_rows", 50000)),
                columns=query.get("columns"),
                sort=query.get("sort"),
                order=query.get("order", "asc"),
            )
    except Exception as exc:  # 期望 error 的场景: 异常即被测行为
        ACTIVE_TRACE.append({"case_id": scenario["case_id"], "snapshot_id": scenario["snapshot_id"],
                             "requests": list(transport.events), "error": repr(exc)})
        return {
            "rows": [],
            "envelope": {"success": False, "error_code": _error_code(exc),
                         "total_count": None, "returned_count": None,
                         "truncated": None},
            "provenance": provenance,
            "observed_http_requests": transport.call_count,
            "declared_http_requests": transport.call_count,
            "mode": "replay", "transport_error": False,
        }
    rows, envelope = from_query_result(result)
    ACTIVE_TRACE.append({"case_id": scenario["case_id"], "snapshot_id": scenario["snapshot_id"],
                         "requests": list(transport.events),
                         "response_snapshot_sha256": snapshot_fingerprint,
                         "rows_sha256": _sha256_obj(rows), "envelope": envelope})
    return {
        "rows": rows,
        "batch_keys": bool(query.get("inputs")),
        "envelope": envelope,
        "pages": ([] if query.get("inputs") else _consumed_pages(transport.page_rows, len(rows))),
        "terminal_empty_page_seen": any("query-aware-empty-page" in e.get("route", "")
                                         or e.get("route") == "empty-terminal-page"
                                         for e in transport.events),
        "provenance": provenance,
        "observed_http_requests": transport.call_count,
        "declared_http_requests": transport.call_count,
        "mode": "replay", "transport_error": False,
    }


def _error_code(exc: Exception) -> str:
    """异常 → 稳定错误码 (契约前缀优先; 否则按类型归常见码)。

    对齐 contracts/error-codes.contract.yaml 的五码: E_INVALID_INPUT /
    E_SOFT_404 / E_NAME_UNRESOLVED / E_NO_SQLID / E_BACKEND。
    """
    message = str(exc)
    for code in ("E_SOFT_404", "E_NO_SQLID", "E_NAME_UNRESOLVED",
                 "E_INVALID_INPUT", "E_BACKEND"):
        if code in message:
            return code
    from src.protocol import Soft404Error

    if isinstance(exc, Soft404Error):
        return "E_SOFT_404"
    if isinstance(exc, ValueError):
        return "E_INVALID_INPUT"
    return "E_BACKEND"


def run_scenario(scenario: dict, repeat: int = 3) -> dict:
    """跑一个场景 (repeat 次, 主结果取首次, data_hashes 供 M7 判确定性)。"""
    hashes, first, states = [], None, []
    for repeat_index in range(max(1, repeat)):
        trace_start = len(ACTIVE_TRACE)
        outcome = run_scenario_once(scenario)
        for event in ACTIVE_TRACE[trace_start:]:
            event["repeat_index"] = repeat_index + 1
            event["attempt_id"] = f"{scenario['case_id']}-r{repeat_index + 1}-a1"
        hashes.append(_sha256_obj(outcome["rows"]))
        states.append({"repeat_index": repeat_index + 1,
                       "success": bool((outcome.get("envelope") or {}).get("success", True)),
                       "transport_error": False})
        first = first or outcome
    first["data_hashes"] = hashes
    first["repeat_states"] = states
    return first


def load_gold(case_id: str) -> dict | None:
    """读金标准 (不存在返回 None — 调用方记 missing, 不静默打 0)。"""
    path = GOLD_DIR / f"{case_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def run(scenarios_dir: Path = SCENARIOS_DIR, repeat: int = 3) -> dict:
    """全量对账: 逐场景 run→compare, 汇总 case 结果 + 阻断项 + metascore。"""
    case_results, missing_gold, missing_snapshot = [], [], []
    ACTIVE_TRACE.clear()
    for path in sorted(scenarios_dir.glob("*.yaml")):
        scenario = load_scenario(path)
        case_id = scenario["case_id"]
        if not (SNAPSHOTS_DIR / scenario["snapshot_id"]).is_dir():
            missing_snapshot.append(case_id)
            continue
        gold = load_gold(case_id)
        if gold is None:
            missing_gold.append(case_id)
            continue
        actual = run_scenario(scenario, repeat=repeat)
        compared = compare_case(gold, actual)
        case_results.append({"case_id": case_id, **compared})
    n_pass = sum(1 for c in case_results if c["pass"])
    return {
        "protocol_version": PROTOCOL_VERSION,
        "cases": case_results,
        "n_cases": len(case_results),
        "n_pass": n_pass,
        "missing_gold": missing_gold,
        "missing_snapshot": missing_snapshot,
        "metascore": metascore(load_broken_results()),
        "trace_events": list(ACTIVE_TRACE),
        "pass": (n_pass == len(case_results)) and case_results
                and not missing_gold and not missing_snapshot,
    }


def load_broken_results() -> list:
    """反证夹具自证 (broken/ 下每个坏样本必须被判 FAIL)。"""
    from evals.groundtruth.broken import run_broken_selftest

    return run_broken_selftest()


def render_markdown(report: dict) -> str:
    """Markdown 报告 (人工复核面; 数字以 JSON 为准)。"""
    lines = [
        "# E2 查询结果与金标准一致性 跑批报告",
        "",
        f"- case 数: {report['n_cases']} (pass {report['n_pass']})",
        f"- 缺金标准: {', '.join(report['missing_gold']) or '无'}",
        f"- 缺快照: {', '.join(report['missing_snapshot']) or '无'}",
        f"- metascore (反证夹具): {report['metascore']:.2f} (必须 1.00)",
        f"- 判定: {'PASS' if report['pass'] else 'FAIL'}",
        "",
        "| case | 加权分 | 阻断项 |",
        "|------|--------|--------|",
    ]
    for case in report["cases"]:
        lines.append(f"| {case['case_id']} | {case['weighted']:.4f} "
                     f"| {', '.join(case['blockers']) or '—'} |")
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    """CLI: --repeat N --json out --md; 退出码 0 全过 / 1 有 fail。"""
    parser = argparse.ArgumentParser(description="E2 groundtruth runner")
    parser.add_argument("--scenarios", default=str(SCENARIOS_DIR))
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--json", default="")
    parser.add_argument("--md", action="store_true")
    args = parser.parse_args(argv)
    report = run(Path(args.scenarios), repeat=args.repeat)
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.md:
        print(render_markdown(report))
    else:
        print(json.dumps({k: v for k, v in report.items() if k != "cases"},
                         ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

