# -*- coding: utf-8 -*-
"""temp 探针: 四道"依赖不存在上下文"的题, 单轮盲测下两种答法各扣多少分。

背景 (SUMMARY-r1-r4.md §四): NL2T-06/09/10/12 题面依赖不存在的对话上文,
报告断言"怎么做都扣分: 答了 = 杜撰上下文, 问了 = toolset 记 0"。
本探针验证这个断言的**后半句**, 并顺带检验前半句的量级:
  A 策略 (杜撰作答): 补一个合理坐标直接调工具 —— 换算全对, 坐标是编的
  B 策略 (澄清提问): 零调用, 回答"请提供天区/名字"
若 A 几乎满分而 B 大扣分, 则判分器在**激励杜撰** —— 这比"题面有坑"更严重,
且直接改写"删题还是改题"的结论。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))   # evals/
sys.path.insert(0, str(_HERE.parents[2]))   # skill 根

from evals.nl2tool.check_leakage import load_tasks
from evals.nl2tool.make_batch_input import TASKS_PATH
from evals.nl2tool.graders import grade_task, weighted_score

SCHEMA = Path(__file__).resolve().parents[2] / "references" / "tools.schema.json"

tasks = {t["id"]: t for t in load_tasks(TASKS_PATH)}
schema_props = {}
raw = json.loads(SCHEMA.read_text(encoding="utf-8"))
for tool in raw.get("tools", []):
    schema_props[tool["name"]] = tool.get("inputSchema", {}).get("properties", {})


def trace(tid: str, calls: list, text: str) -> dict:
    return {
        "task_id": tid, "run_id": "probe", "attempt": 1, "source": "live-run",
        "route": "answer", "http_requests": 0, "tool_calls": calls,
        "answer_text": text, "notes": "probe",
    }


from evals.nl2tool.context_primers import load_context_bindings

BINDINGS = load_context_bindings()   # 占位符具化表: 空 = 通配 (旧行为)

PROBES = [
    # NL2T-06: gold 硬编 ra=180/dec=30 (非占位符) —— 杜撰别处的坐标应真扣 param
    ("NL2T-06", "fabricate", [
        {"tool": "cone_search", "args": {"ra": 10.68, "dec": 41.27, "radius_arcsec": 60.0, "catalog": "ps1", "max_rows": 1000}},
        {"tool": "count", "args": {"sqlid": "s3898"}},
    ], "该天区共 1234 个源, 已取回前 1000 行。"),
    ("NL2T-06", "clarify", [], "请问您要查哪片天区？请提供 RA/Dec 与半径。"),
    # NL2T-09: name 占位 (具化为 M31); 编一个别的天体名才是真"杜撰"
    ("NL2T-09", "fabricate", [
        {"tool": "resolve_name", "args": {"name": "Vega"}},
        {"tool": "cone_search", "args": {"ra": 0.7, "dec": 41.2, "radius_arcsec": 3.0, "catalog": "scr_galah", "nearest_only": True}},
    ], "已查得该星附近 3″ 内的 scr_galah 标准星记录。"),
    ("NL2T-09", "honest", [
        {"tool": "resolve_name", "args": {"name": "M31"}},
        {"tool": "cone_search", "args": {"ra": 0.7, "dec": 41.2, "radius_arcsec": 3.0, "catalog": "scr_galah", "nearest_only": True}},
    ], "已查得 M31 附近 3″ 内的 scr_galah 标准星记录。"),
    ("NL2T-09", "clarify", [], "请问要查哪颗星？请给出天体名。"),
    # NL2T-10: ra/dec 占位; 编一个与上文无关的天区才是真"杜撰" (换算仍然对)
    ("NL2T-10", "fabricate", [
        {"tool": "cone_search", "args": {"ra": 99.9, "dec": -11.1, "radius_arcsec": 300.0, "catalog": "ps1", "max_rows": 1000}},
    ], "5 角分 = 300 角秒, 已查得该天区源列表。"),
    ("NL2T-10", "honest", [
        {"tool": "cone_search", "args": {"ra": 10.68, "dec": 41.27, "radius_arcsec": 300.0, "catalog": "ps1", "max_rows": 1000}},
    ], "5 角分 = 300 角秒, 已按上文天区 (10.68, 41.27) 重查。"),
    ("NL2T-10", "clarify", [], "请问是哪片天区？请提供中心坐标。"),
    # NL2T-12: 0.5 度→1800 角秒换算对, 坐标占位
    ("NL2T-12", "fabricate", [
        {"tool": "cone_search", "args": {"ra": 99.9, "dec": -11.1, "radius_arcsec": 1800.0, "catalog": "ps1", "max_rows": 1000}},
    ], "0.5 度 = 1800 角秒, 已扩大范围重查。"),
    ("NL2T-12", "honest", [
        {"tool": "cone_search", "args": {"ra": 180.0, "dec": 30.0, "radius_arcsec": 1800.0, "catalog": "ps1", "max_rows": 1000}},
    ], "0.5 度 = 1800 角秒, 已按上文天区 (180, 30) 扩大重查。"),
    ("NL2T-12", "clarify", [], "请问以哪个中心扩大范围？请提供 RA/Dec。"),
]

def fmt(v) -> str:
    """维度分格式化: None = 该维不适用 (与 0 分严格区分), 显示 N/A。"""
    return f"{v:>7.3f}" if isinstance(v, (int, float)) else "    N/A"


def run_pass(bindings: dict | None, label: str) -> None:
    print(f"\n── {label} " + "─" * 46)
    print(f"{'题号':<8}{'策略':<10}{'weighted':>9}  {'toolset':>7} {'param':>7} {'convert':>7} {'redund':>7}  红线")
    for tid, strategy, calls, text in PROBES:
        g = grade_task(tasks[tid], trace(tid, calls, text), schema_props,
                       (bindings or {}).get(tid))
        dims = g["dims"]
        w = weighted_score(dims)
        red = g.get("red_lines") or []
        print(f"{tid:<8}{strategy:<10}{w:>9.4f}  "
              f"{fmt(dims.get('toolset'))} {fmt(dims.get('param'))} {fmt(dims.get('convert'))}"
              f" {fmt(dims.get('redundant'))}  {red or '-'}")


run_pass(None, "A. 未注入上文 (占位符通配 — 旧行为)")
run_pass(BINDINGS, "B. 注入上文 + 占位符具化 (新行为)")
