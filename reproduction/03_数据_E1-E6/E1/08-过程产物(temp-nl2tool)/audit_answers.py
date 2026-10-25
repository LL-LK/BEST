# -*- coding: utf-8 -*-
"""答案件体检: 判分器没管的那一层 (值域/枚举/必填/自洽/串题痕迹)。

判分器的 load_schema_props 明写"幻觉判定只比名字, 不比类型与取值" —
所以 tool 名与参数名合法是判过的, 但**取值**没人查。本件补这一层,
外加判分器完全不看的三件事: 必填缺失、文字与调用是否自洽、http_requests 是否离谱。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "temp" / "nl2tool" / "traces-live-2026-10-06"
SCHEMA = json.loads((ROOT / "references" / "tools.schema.json").read_text(encoding="utf-8"))
TOOLS = {t["name"]: t.get("inputSchema", {}) for t in SCHEMA.get("tools", [])}

FINDINGS: list[tuple[str, str, str]] = []   # (级别, 题号, 说明)


def note(level: str, tid: str, msg: str) -> None:
    FINDINGS.append((level, tid, msg))


def check_call(tid: str, call: dict) -> None:
    tool = call.get("tool", "")
    sch = TOOLS.get(tool)
    if sch is None:
        note("P0", tid, f"工具名不存在于 schema: {tool}")
        return
    args = call.get("args") or {}
    props = sch.get("properties", {})
    for req in sch.get("required") or ():
        if req not in args or args.get(req) is None:
            note("P1", tid, f"{tool} 缺必填参数 `{req}`")
    for key, val in args.items():
        spec = props.get(key)
        if spec is None:
            note("P1", tid, f"{tool} 出现 schema 外参数 `{key}`")
            continue
        if "enum" in spec and val not in spec["enum"]:
            note("P1", tid, f"{tool}.{key} 取值 {val!r} 不在 enum 里")
            continue
        types = spec.get("type")
        if types == "number" and not isinstance(val, (int, float)):
            note("P1", tid, f"{tool}.{key} 应为数字, 实际 {type(val).__name__}")
            continue
        if types == "integer" and not isinstance(val, int):
            note("P1", tid, f"{tool}.{key} 应为整数, 实际 {type(val).__name__}")
            continue
        if types == "array" and not isinstance(val, list):
            note("P1", tid, f"{tool}.{key} 应为数组, 实际 {type(val).__name__}")
            continue
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            lo, hi = spec.get("minimum"), spec.get("maximum")
            if lo is not None and val < lo:
                note("P1", tid, f"{tool}.{key}={val} 低于下限 {lo}")
            if hi is not None and val > hi:
                note("P1", tid, f"{tool}.{key}={val} 高于上限 {hi}")
        if isinstance(val, list) and "maxItems" in spec and len(val) > spec["maxItems"]:
            note("P1", tid, f"{tool}.{key} 数组长度 {len(val)} 超过 maxItems {spec['maxItems']}")


BAND_COL = re.compile(r"\b(?:ps1|gaia_dr3_18|splus_dr4|stripe82|jplus_dr3|smss_dr4|landolt|uss_dr1|scr_galah|scr_lamost|xpsp|dr3xpcorr)_[a-z0-9_]+")


def check_consistency(tid: str, tr: dict) -> None:
    calls = tr.get("tool_calls") or []
    text = tr.get("answer_text") or ""
    http = tr.get("http_requests", 0)

    # 1) 零调用却报了 http 请求数
    if not calls and http > 0:
        note("P1", tid, f"没有任何工具调用, 却声明 http_requests={http}")
    # 2) 有调用却报零请求 (除了纯元数据工具)
    zero_cost = {"list_catalogs", "describe_catalog", "resolve_name"}
    if calls and http == 0 and all(c["tool"] in zero_cost for c in calls):
        pass  # 元数据工具确实是零请求
    elif calls and http == 0:
        note("P1", tid, "发了数据面调用却声明 http_requests=0")

    # 3) 文字里提到的列名, 有没有真的写进调用的 columns
    mentioned = set(BAND_COL.findall(text))
    call_cols = set()
    for c in calls:
        for col in (c.get("args") or {}).get("columns") or ():
            call_cols.add(col)
    if mentioned and calls and not call_cols & mentioned:
        note("P2", tid, f"文字点名了列 {sorted(mentioned)}, 但调用的 columns 里没有")

    # 4) 提到了 catalog 却没在调用里出现
    for c in calls:
        cat = (c.get("args") or {}).get("catalog")
        if cat and cat not in text and "splus" not in text.lower():
            note("P2", tid, f"调用用了 catalog={cat}, 文字里没提 (可能是笔误)")


def main() -> int:
    traces = {}
    for p in sorted(SRC.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        traces[d["task_id"]] = d

    for tid in sorted(traces):
        tr = traces[tid]
        for call in tr.get("tool_calls") or []:
            check_call(tid, call)
        check_consistency(tid, tr)

    # 串题 / 泄漏痕迹: 答案里出现别的题号, 或出现标注层的行话
    leak_words = ["NL2T-", "expect_tools", "anti_pattern", "reason_code", "must_not_call",
                  "tasks.yaml", "graders.py", "REPORT.md", "context_primers"]
    for tid in sorted(traces):
        text = traces[tid].get("answer_text") or ""
        for w in leak_words:
            if w in text:
                note("P0", tid, f"答案正文出现评测/标注层字样: {w!r} — 疑似看到标注")

    order = {"P0": 0, "P1": 1, "P2": 2}
    for lv in ("P0", "P1", "P2"):
        rows = [f for f in FINDINGS if f[0] == lv]
        rows.sort(key=lambda r: r[1])
        print(f"\n── {lv} ({len(rows)} 条) ──")
        if not rows:
            print("  (无)")
        for _, tid, msg in rows:
            print(f"  {tid}: {msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
