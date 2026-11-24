# -*- coding: utf-8 -*-
"""evals/repro/score_r1.py — E6 R1 路 (模型决策层) 自一致性评分。

读 14 条未覆盖任务的 5 轮模型决策, 算三个一致性面:

  - **TSC** 工具序列一致性: 5 轮的工具名序列是否全同 (对齐 E6 的 tsc_set 口径)
  - **PAC** 参数一致性: 同一工具名的参数是否逐轮全同 (对齐 pac_field 口径)
  - **FCC** 结论卡一致性: 卡的 (kind, key_entities) 是否逐轮全同
  - **RTE** 相对时间表述: 任务里的硬约束, 任何一轮出现即该任务记 RTE_FAIL

外加一项**正确性** (不是一致性): 首工具是否与任务标注的 expect_first_tool 相符。
一致 ≠ 正确 —— 5 轮全错也是自洽的 1.0, 两面必须分开读。

统计诚实声明: 每任务 5 轮, Wilson 区间按 14 个任务做分组重抽 (与 R0 同口径)。

素材分层 (铁律 3/4): 模型的**原始决策**是采集物, 留在 gitignored 的采集目录
(``--live-dir``, 默认 ``temp/live``); 本脚本产出的**计分结果**才是入库资产
(``--out``, 仓内既有实例见 ``evals/repro/live-2026-10-04.json``)。
"""
from __future__ import annotations

# 标准库: 参数解析/JSON/路径
import argparse
import json
import pathlib
import sys

# 路径锚与命名空间挂载: evals/repro → evals → 仓根, 故 parents[1] 是仓根
_HERE = pathlib.Path(__file__).resolve().parent          # evals/repro/
ROOT = _HERE.parents[1]                                  # 仓库根 (evals/repro → evals → 根)
sys.path.insert(0, str(ROOT / "evals"))                  # 挂 evals/ (paths 兄弟裸导入, 与 run_e6.py 同口径)
sys.path.insert(0, str(ROOT))                            # 挂仓根: evals.* 命名空间包

# 共享件: YAML 读取 (裸导入, 仓内既有约定; 不走 evals.* 以免被当成跨实验引用)
from paths import load_yaml_file  # noqa: E402

TASKS_DIR = _HERE / "tasks"                              # 任务标注目录 (32 份 REPRO-*.yaml)
DEFAULT_LIVE = ROOT / "temp" / "live"                    # 原始决策采集目录 (gitignored, 非入库资产)


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    """Wilson 95% 区间 (R0/R1 同口径: 小样本不做正态近似)。"""
    if n == 0:                                            # 空批: 区间退化为 [0,0], 不返回 None 让下游崩
        return [0.0, 0.0]
    p = k / n                                              # 观测比例
    d = 1 + z * z / n                                      # Wilson 方差修正因子
    center = (p + z * z / (2 * n)) / d                     # 区间中心 (含小样本收缩项)
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d   # 半宽
    return [round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)]


def load_tasks() -> dict:
    """读全部任务标注 (期望首工具就取自这里, 评分不自带答案)。"""
    return {i["id"]: i for i in
            (load_yaml_file(f) for f in sorted(TASKS_DIR.glob("REPRO-*.yaml")))}


def score(data: dict, tasks: dict) -> list[dict]:
    """逐任务算三个一致性面 + 首工具正确性。"""
    rows = []
    for task_id, runs in data.items():                    # 逐任务: 采集物按任务 id 组织
        task = tasks.get(task_id, {})                       # 标注缺失不静默: want 变 None, 正确性面自然判 0
        seqs = [tuple(c.get("tool") for c in (r.get("tool_calls") or [])) for r in runs]
        argmaps = [{c.get("tool"): json.dumps(c.get("args", {}), sort_keys=True, ensure_ascii=False)
                    for c in (r.get("tool_calls") or [])} for r in runs]
        cards = [(r.get("card", {}).get("kind"),
                  tuple(sorted(r.get("card", {}).get("key_entities") or []))) for r in runs]
        rte = [bool(r.get("card", {}).get("relative_time_expression")) for r in runs]
        want = task.get("expect_first_tool")
        firsts = [seq[0] if seq else "none" for seq in seqs]  # 空决策记 "none", 不当缺失抹掉
        rows.append({
            "id": task_id, "n_runs": len(runs),
            "tsc": float(len(set(seqs)) == 1),                  # 5 轮工具名序列全同才算 1
            "pac": float(len({json.dumps(a, sort_keys=True) for a in argmaps}) == 1),
            "fcc": float(len(set(cards)) == 1),
            "rte_any": any(rte),                                # 任一轮出现即该任务违规
            "want_first_tool": want,
            "first_tool_ok": float(all(f == want for f in firsts)),
            "first_tools_seen": sorted(set(firsts)),
            "card_kinds_seen": sorted({c[0] for c in cards}),
        })
    return rows


def summarize(rows: list[dict]) -> dict:
    """汇总: 比率一律带 Wilson 区间, 违规清单逐条点名 (不折成一句"有若干条")。"""
    n = len(rows) or 1                                     # 分母恒为任务数; 空批记 0/1 而不是抛错
    def rate(key: str) -> float:
        """某个布尔面的命中率 (分母恒为任务数, 空批时记 0 而不是抛错)。"""
        return round(sum(r[key] for r in rows) / n, 4)
    tsc_k = sum(r["tsc"] for r in rows)                     # 三面各自的成功数, 供 Wilson 用
    fcc_k = sum(r["fcc"] for r in rows)
    pac_k = sum(r["pac"] for r in rows)
    ft_k = sum(r["first_tool_ok"] for r in rows)
    return {
        "n_tasks": len(rows), "runs_per_task": 5,
        "TSC": rate("tsc"), "TSC_ci95": wilson(tsc_k, n),
        "PAC": rate("pac"), "PAC_ci95": wilson(pac_k, n),     # 补齐第三面的区间, 与 TSC/FCC 同口径
        "FCC": rate("fcc"), "FCC_ci95": wilson(fcc_k, n),
        "first_tool_correct": rate("first_tool_ok"),
        "first_tool_correct_ci95": wilson(ft_k, n),          # 正确性面也带区间: 14 个任务不足以报点值
        "RTE_violations": [r["id"] for r in rows if r["rte_any"]],
        "RTE_note": "相对时间表述是 E6 硬约束; 任务 yaml 里 relative_time_expression=true 的任务出现即为违规",
        "tsc_unstable": [r["id"] for r in rows if not r["tsc"]],
        "fcc_unstable": [r["id"] for r in rows if not r["fcc"]],
        "first_tool_mismatch": [r["id"] for r in rows if not r["first_tool_ok"]],
        "PAC_note": "PAC 无数值输出: 各任务的参数口径不同, 逐任务比才有意义 (见 rows)",
    }


def main(argv: list[str] | None = None) -> int:
    """主流程: 读原始决策 → 评分 → 落盘 + 打印。"""
    ap = argparse.ArgumentParser(description="E6 R1 自一致性评分")
    ap.add_argument("--live-dir", type=pathlib.Path, default=DEFAULT_LIVE,
                    help="原始决策采集目录 (默认 temp/live)")
    ap.add_argument("--out", type=pathlib.Path, default=None,
                    help="计分结果落盘路径 (默认写回采集目录; 入库资产请显式指定)")
    args = ap.parse_args(argv)                             # 参数: 采集目录与落盘路径

    src = args.live_dir / "e6_r1.json"                       # 采集物文件名固定: 换批次不换名
    if not src.is_file():                                  # 缺采集物即缺, 不拿别的批次凑
        print(f"[FAIL] 缺原始决策文件: {src} (不猜不代, 铁律 5 禁 fail-open)")
        return 1
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = score(data, load_tasks())                        # 先判逐条, 再汇总
    summary = summarize(rows)

    out = args.out or (args.live_dir / "e6_r1_scored.json")  # 未指定 --out 则写回采集目录
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n--- 逐条 (已落盘: {out}) ---")
    for r in rows:                                         # 逐条打印: 哪个任务不稳一眼可见
        print(f"  {r['id']:9} TSC={int(r['tsc'])} PAC={int(r['pac'])} FCC={int(r['fcc'])} "
              f"first_tool_ok={int(r['first_tool_ok'])} want={r['want_first_tool']:<16} "
              f"seen={r['first_tools_seen']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
