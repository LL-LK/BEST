# -*- coding: utf-8 -*-
"""evals.ablation.metrics.taxonomy — E5 的 T5 错误谱系与归因表 (docs/eval-E5-baseline-ablation.md §12)。

职责: 把逐 run 的**失败案例**按错误类型聚类, 再归因到"缺哪个组件" ——
§12 称它是"最有说服力的一张：把分数拆回设计缺口"。

判定链分两段, **刻意分开**:

1. **打类型** (L2 盲评): 对失败案例逐条给一个错误类型, **脱标识**(不看 system/item)。
   本仓无人类专家, 按 E5 的 LLM-only 口径由子代理产出, 且**必须在报告里披露**
   (§11 阻断项 8: 未披露 LLM-only 即 FAIL)。盲评产物落在 temp/(运行时物, 不入库)。
2. **归因** (本模块): 类型 → 缺哪个组件, 走 :data:`COMPONENT_MAP` 的固定映射,
   **不在打类型阶段做归因** —— 否则盲评员会照着"缺哪个组件"倒推类型, 失去盲性。

诚实边界: 抽样 20% (§12), 类型分布是**代理指标**, 只用于"失败长什么样"的定性描述;
绝对结论以 E3 为准 (E5 §6.4)。

白盒锚点: docs/eval-E5-baseline-ablation.md §12 (T5 定义) / §7 (L2 判定分层)。
"""
from __future__ import annotations

from typing import Optional

# 错误类型 → 缺哪个组件。这张映射是 T5 的落点: 它把"答案错在哪"翻成"设计缺什么"。
# 归因到 A1–A5 五零件的项, 与 §4 的消融设计一一对应; 另两类是结构性/通用成因,
# **不得**硬塞给某个组件 (B0/B1 的失败不是"缺某个零件", 是"没有工具面")。
COMPONENT_MAP = {
    "param_hallucination": "参数校验 (A1)",
    "band_mapping": "字段语义说明 (A2)",
    "hard_execute": "能力边界与拒绝规则 (A3)",
    "wrong_route": "能力边界与拒绝规则 (A3)",
    "no_provenance": "来源与版本信息 (A4)",
    "sentinel_as_value": "结果后验证 (A5)",
    "fabrication": "— (模型自身知识边界, 非组件缺失)",
    "no_tool": "— (结构性: 无工具面, 非组件缺失)",
    "other": "— (未归类)",
}


def build_t5(cases: list[dict], verdicts: dict, top_n: int = 3) -> dict:
    """按系统聚合盲评结论, 产出 T5 数据。

    Args:
        cases: 失败案例清单 (``temp/t5_cases.json`` 的内容; 每条带 anon_id/system/item)。
        verdicts: ``{anon_id: 错误类型}`` (盲评产物)。
        top_n: 每系统列前几大错误类型。

    Returns:
        ``{"rows": [...], "type_totals": {...}, "n_cases": n, "coverage": rate}``。
    """
    by_system: dict[str, dict[str, int]] = {}
    type_totals: dict[str, int] = {}
    matched = 0
    for case in cases:
        anon = str(case.get("anon_id"))
        kind = verdicts.get(anon)
        if kind is None:                     # 盲评漏了这条: 不计入, 由 coverage 如实暴露
            continue
        matched += 1
        system = str(case.get("system"))
        by_system.setdefault(system, {})[kind] = by_system.setdefault(system, {}).get(kind, 0) + 1
        type_totals[kind] = type_totals.get(kind, 0) + 1
    rows = []
    for system in sorted(by_system):
        counts = by_system[system]
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        top = ordered[:top_n]
        # 主归因取第一大类型: 一条案例只打一个类型, 故"最主导成因"是确定的
        primary = ordered[0][0] if ordered else "other"
        rows.append({
            "system": system,
            "n_fail_sampled": sum(counts.values()),
            "top_types": top,                       # [(类型, 条数), ...]
            "primary_type": primary,
            "attributed_component": COMPONENT_MAP.get(primary, "— (未归类)"),
        })
    return {
        "rows": rows,
        "type_totals": dict(sorted(type_totals.items(), key=lambda kv: -kv[1])),
        "n_cases": len(cases),
        "coverage": (matched / len(cases)) if cases else 0.0,
    }


def render_t5(table: dict) -> str:
    """T5 的 Markdown 渲染 (供 runner 拼进 REPORT.md)。"""
    lines = [
        "## 表 7 · 错误谱系与归因 (T5: 失败案例 → 缺哪个组件)",
        "",
        f"抽样 {table['n_cases']} 条失败案例 (按系统分层 20%)，盲评覆盖 "
        f"{table['coverage']:.1%}。类型由**脱标识盲评**给出，归因走固定映射 —— "
        "**代理指标**，用于定性描述失败形态，绝对结论以 E3 为准 (§6.4)。",
        "",
        "| 系统 | 抽样失败数 | 主要错误类型 (前 3) | 归因组件 |",
        "|---|---|---|---|",
    ]
    for row in table["rows"]:
        top = "、".join(f"{k}×{v}" for k, v in row["top_types"]) or "—"
        lines.append(f"| {row['system']} | {row['n_fail_sampled']} | {top} "
                     f"| {row['attributed_component']} |")
    lines += ["", "**类型总分布**：" + "、".join(
        f"{k}×{v}" for k, v in table["type_totals"].items()), ""]
    lines += [
        "> **盲评口径披露 (§11 阻断项 8)**：本表为 `review_mode: llm-only (no human reviewer, no kappa)`"
        " —— 无人类复核、不报 κ/AC1。",
        "> **归因映射**：" + "；".join(f"`{k}` → {v}" for k, v in COMPONENT_MAP.items()),
        "",
    ]
    return "\n".join(lines)


def build_t5_from_files(cases_path: str, verdicts_path: str) -> dict:
    """从落盘文件构建 T5 (编排入口; 两文件都在 temp/, 是运行时物)。"""
    import json
    from pathlib import Path

    cases = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    verdicts = json.loads(Path(verdicts_path).read_text(encoding="utf-8"))
    return build_t5(cases, verdicts)
