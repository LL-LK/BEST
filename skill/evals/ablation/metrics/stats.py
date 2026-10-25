# -*- coding: utf-8 -*-
"""evals.ablation.metrics.stats — E5 的 T4 统计表 (docs/eval-E5-baseline-ablation.md §8/§12)。

职责: 把逐 run 的三门判定 (D/F/E) 压成**逐题二分类**, 再对每个系统与基线 B3 做
配对比较, 产出 T4 所需的全部数字:

  - **McNemar 精确检验** (配对二分类, 双尾二项精确 p; 不引 scipy, 纯标准库);
  - **差值 Wilson 95% CI** (通过率的区间估计, 小样本下优于正态近似);
  - **Holm 校正** (多重比较: 主分析族 8 次 = B0/B1/B2b + A1–A5; B2a 属附录族单独校正);
  - **bootstrap 10 000 次重抽题** (配对重抽, 给差值一个不依赖分布假设的 CI);
  - **效力声明** (§8: 30 题配对设计下真实差异 0.85 vs 0.60 时 McNemar 效力约 0.6–0.7)。

口径 (§8):
  - 逐题判定 = 该系统该题 **3 次重复的多数票** (≥2 次通过即通过);
  - 主指标 = ``ESR_full`` 的题级布尔 (D 类需 D∧F∧E 三门齐过, 非 D 类需 D∧E);
  - 配对 = 同一题在两个系统上的布尔差, 只统计**不一致对** (b, c)。

诚实边界: 本题集 30 条、配对设计, 效力有限; **出现"差异看着很大但 p>0.05"时必须扩到
60 题再下结论**, 不得直接写"两者无差异" (§8)。

白盒锚点: docs/eval-E5-baseline-ablation.md §8 (统计方法与效力声明) / §12 (T4 统计表)。
"""
from __future__ import annotations

import math
import random
from typing import Optional

# 主分析族 (§8): 与 B3 比 8 次, B2a 属附录族单独 Holm 校正
MAIN_FAMILY = ("B0", "B1", "B2b", "A1", "A2", "A3", "A4", "A5")
APPENDIX_FAMILY = ("B2a",)
BASELINE = "B3"

_BOOTSTRAP_N = 10_000   # 重抽次数: §8 明文 10 000
_BOOTSTRAP_SEED = 20261008  # 固定种子: 报告数字必须可复现
_RANGE_MC = 20_000      # 极差零假设的重抽次数 (2026-10-10): 经验 p 的分辨率需优于 0.005


def _range_under_exchangeability(n: int, p: float, rng) -> float:
    """**可交换零假设**下 3 轮比例的极差 (一次重抽)。

    为什么需要它 (2026-10-10): add-back 的旧判据是"逐 attempt 极差 ≤ 0.05"。这个门槛
    是拍出来的, 没有对着抽样分布看一眼 —— 在 n=30、p≈0.8 时单轮比例的标准差就有 0.07,
    于是即便数据**完全可交换**, 极差中位数也已经是 0.10。要判"极差是否异常", 必须拿
    它跟**它自己的零分布**比, 而不是跟一个与 n 无关的常数比。

    Args:
        n: 每轮的样本数 (各轮同分母)。
        p: 合并比例 p̂ (零假设下三轮同率)。
        rng: 固定种子的随机数发生器。

    Returns:
        3 轮比例 (每轮 n 次伯努利) 的极差。
    """
    rates = [sum(1 for _ in range(n) if rng.random() < p) / n for _ in range(3)]
    return max(rates) - min(rates)


def _pass_of(item: dict, run: dict, score_run) -> bool:
    """逐题布尔: 复用 composite.score_run 的三门, 按 D 类/知识类两种合成口径。"""
    scored = score_run(item, run)
    d_ok = bool(scored["D"]["pass"])
    e_ok = bool(scored["E"]["pass"])
    if str(item.get("id", "")).startswith("E5-D"):   # D 类: 决策对了但取数错, 对用户仍是失败
        f_ok = bool(scored["F"] and scored["F"]["pass"])
        return d_ok and f_ok and e_ok
    return d_ok and e_ok                               # 知识类无取数门


def per_task_booleans(runs: list[dict], items: list[dict], score_run) -> dict[str, dict[str, bool]]:
    """{系统: {题 id: 多数票通过}} —— 3 次重复取多数 (≥2 次通过即通过)。"""
    by_item = {str(i.get("id")): i for i in items}
    votes: dict[str, dict[str, list[bool]]] = {}
    for run in runs:
        item = by_item.get(str(run.get("item")))
        if item is None:
            continue
        votes.setdefault(str(run.get("system")), {}).setdefault(str(run.get("item")), []).append(
            _pass_of(item, run, score_run))
    return {system: {tid: sum(v) * 2 >= len(v) for tid, v in per.items()}
            for system, per in votes.items()}


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 95% 通过率区间 (小样本下优于正态近似)。"""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def mcnemar_exact(b: int, c: int) -> float:
    """McNemar 精确检验 (双尾): 只看不一致对 b/c, 用二项精确分布。"""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def holm(pvalues: dict[str, float], alpha: float = 0.05) -> dict[str, dict]:
    """Holm 校正: 按 p 升序, 第 i 个与 alpha/(m-i) 比, 一旦不显著其后全不显著。"""
    ordered = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(ordered)
    out: dict[str, dict] = {}
    still = True
    for i, (name, p) in enumerate(ordered):
        threshold = alpha / (m - i)
        reject = still and p <= threshold
        if not reject:
            still = False
        out[name] = {"p": p, "threshold": threshold, "reject": reject}
    return out


def bootstrap_diff_ci(base: list[bool], other: list[bool], n: int = _BOOTSTRAP_N,
                      seed: int = _BOOTSTRAP_SEED) -> tuple[float, float]:
    """配对 bootstrap: 重抽题目, 给通过率差值一个不依赖分布假设的 95% CI。"""
    if not base:
        return (0.0, 0.0)
    rng = random.Random(seed)  # noqa: S311 -- 固定种子: 同一批数据两次跑必须同值
    size = len(base)
    diffs = []
    for _ in range(n):
        idx = [rng.randrange(size) for _ in range(size)]
        b = sum(base[i] for i in idx) / size
        o = sum(other[i] for i in idx) / size
        diffs.append(b - o)                        # 基线减对照: 正 = 基线更好
    diffs.sort()
    lo = diffs[int(0.025 * n)]
    hi = diffs[int(0.975 * n) - 1]
    return (lo, hi)


def t4_table(per_task: dict[str, dict[str, bool]], baseline: str = BASELINE) -> dict:
    """T4 主表: 每个系统 vs 基线的 McNemar / Wilson CI / 差值 CI / 家族归属。"""
    base = per_task.get(baseline) or {}
    shared = sorted(base)                          # 只用两系统都有的题: 缺题不得当"失败"算进配对
    rows: dict[str, dict] = {}
    pvals_main, pvals_appendix = {}, {}
    for system, per in per_task.items():
        if system == baseline:
            continue
        common = [t for t in shared if t in per]
        if not common:
            continue
        b_list = [base[t] for t in common]
        o_list = [per[t] for t in common]
        b_hat, o_hat = sum(b_list) / len(common), sum(o_list) / len(common)
        # McNemar 的两个不一致格: b = 基线过而对照没过; c = 基线没过而对照过
        b_cell = sum(1 for x, y in zip(b_list, o_list) if x and not y)
        c_cell = sum(1 for x, y in zip(b_list, o_list) if not x and y)
        p = mcnemar_exact(b_cell, c_cell)
        lo, hi = bootstrap_diff_ci(b_list, o_list)
        bl_lo, bl_hi = wilson_ci(sum(b_list), len(common))
        ol_lo, ol_hi = wilson_ci(sum(o_list), len(common))
        rows[system] = {
            "n_paired": len(common),
            "baseline_rate": b_hat, "system_rate": o_hat, "delta": o_hat - b_hat,
            "mcnemar_b": b_cell, "mcnemar_c": c_cell, "p_raw": p,
            "baseline_wilson": (bl_lo, bl_hi), "system_wilson": (ol_lo, ol_hi),
            "delta_bootstrap_ci": (lo, hi),
            "family": "main" if system in MAIN_FAMILY else "appendix",
        }
        (pvals_main if system in MAIN_FAMILY else pvals_appendix)[system] = p
    holm_main = holm(pvals_main)
    holm_appendix = holm(pvals_appendix)
    for system, row in rows.items():
        adj = holm_main.get(system) or holm_appendix.get(system) or {}
        row["holm_threshold"] = adj.get("threshold")
        row["p_holm"] = "reject" if adj.get("reject") else "not_reject"
    return {"baseline": baseline, "rows": rows,
            "families": {"main": list(MAIN_FAMILY), "appendix": list(APPENDIX_FAMILY)},
            "power_note": ("30 题配对设计下, 真实差异 0.85 vs 0.60 时 McNemar 效力约 "
                           "0.6–0.7, 存在漏检风险; 出现'差异看着大但 p>0.05'时必须扩到 "
                           "60 题再下结论, 不得直接写'两者无差异' (§8)")}


def render_t4(table: dict) -> str:
    """T4 的 Markdown 渲染 (供 report.py 拼进 REPORT.md)。"""
    lines = [
        "## 表 4 · 统计表 (T4: 逐系统 vs 基线 B3 的配对检验)",
        "",
        f"基线 = **{table['baseline']}**；逐题判定取 3 次重复多数票；配对只看两系统"
        "都采到的题。主分析族 8 次 (B0/B1/B2b + A1–A5) 与附录族 1 次 (B2a) **各自** "
        "Holm 校正，不混成一族。",
        "",
        "| 系统 | 配对题数 | 基线率 | 系统率 | Δ | 基线 Wilson 95% | 系统 Wilson 95% | "
        "不一致对 (b/c) | McNemar p | Δ bootstrap 95% CI | Holm 门槛 | Holm 判定 | 族 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for system, r in sorted(table["rows"].items(), key=lambda kv: kv[1]["delta"]):
        lines.append(
            f"| {system} | {r['n_paired']} | {r['baseline_rate']:.3f} | {r['system_rate']:.3f} "
            f"| {r['delta']:+.3f} | [{r['baseline_wilson'][0]:.3f}, {r['baseline_wilson'][1]:.3f}] "
            f"| [{r['system_wilson'][0]:.3f}, {r['system_wilson'][1]:.3f}] "
            f"| {r['mcnemar_b']}/{r['mcnemar_c']} | {r['p_raw']:.4f} "
            f"| [{r['delta_bootstrap_ci'][0]:+.3f}, {r['delta_bootstrap_ci'][1]:+.3f}] "
            f"| {r['holm_threshold']:.4f} | {r['p_holm']} | {r['family']} |")
    lines += ["", f"> **效力声明**: {table['power_note']}", ""]
    return "\n".join(lines)


def build_t4(runs: list[dict], items: list[dict]) -> dict:
    """从逐 run 轨迹构建 T4 (编排入口, report.py 调它)。"""
    # 本地: 三门判定 (与 aggregate 同一份实现, 不另写第二套)
    from evals.ablation.metrics.composite import score_run

    per_task = per_task_booleans(runs, items, score_run)
    return t4_table(per_task)


def addback_check(runs: list[dict], items: list[dict], baseline: str = BASELINE,
                  tol: float = 0.05) -> dict:
    """add-back 恢复检验 (§4)。

    **定性必须说清 (2026-10-08)**: 在当前装配体系里，"把拆掉的零件装回去"得到的
    装配**就是 B3** —— §3.1 的 A1–A5 定义即"B3 缺一个组件"，装回该组件等于还原 B3。
    所以这个检验**测不出"恢复"**（那在装配层是恒等式），它实际测的是基线的
    **采样稳定性**：逐 attempt 算基线分数，看极差是否 ≤ ``tol``。
    极差超限 ⇒ 该批次采样噪声大到无法支撑任何消融归因（此时 A1–A5 的 Δ 全部不可信）。

    为什么仍要做: §4 要求"掉分可归因、可恢复"。在无法构造"部分装回"装配的前提下，
    能给出的最强证据就是"基线自身在采样间稳不稳" —— 它把"消融结论是否可信"这个
    问题落到一个可判定的数上，而不是留一句"未检验"。

    **容差必须标定, 不能拍一个 0.05 (2026-10-10 修)**: 原实现拿固定 ``tol=0.05`` 比
    逐 attempt 极差。实测标定 (``temp/e5_addback_calib.py``, 20 000 次蒙特卡洛) 表明
    这个门槛在 n=30 下**统计上不可达**: 即便数据**完全可交换**, 极差的**中位数**就是
    0.100 (D 通道) / 0.133 (E 通道) —— 也就是说, 固定 0.05 会在毫无问题的数据上以
    **超过一半**的概率误判"超限"。原判据实际测的主要是二项噪声, 不是系统稳定性。

    现改为**按通道标定**: 用合并比例 ``p̂`` 与每轮样本数 ``n`` 生成"可交换零假设下
    3 轮极差"的分布, 取实测极差的经验 p 值; ``p >= 0.05`` 即该通道不构成超限。
    保留 ``tolerance=0.05`` 仅作**历史口径参照**, 不再驱动判定。

    **为什么要分通道**: 决定性差异只落在表述门。实测 attempt 1 严格最高的系统数:
    D 门 2/11 (p=0.11, 与随机一致)、F 门 0/1 (p=1.00, 轮次间几乎逐字相同)、
    E 门 7/7 (p=4.6e-04)。故 D/F 通道的消融归因**由可交换数据支撑**, 只有 E 通道
    不可归因 —— 原实现把 E 混进 composite, 于是"全部消融降级"这个结论过宽。
    """
    # 本地: 三门判定 (与 T4 同一份实现)
    from evals.ablation.metrics.composite import score_run

    by_item = {str(i.get("id")): i for i in items}
    # 逐通道收集布尔: D 决策 / F 取数 / E 表述 / composite 合成 (D 类要三门齐过)
    chan: dict[str, dict[str, list[bool]]] = {}
    for run in runs:
        if str(run.get("system")) != baseline:   # 只看基线: add-back 装配 ≡ 基线
            continue
        item = by_item.get(str(run.get("item")))
        if item is None:
            continue
        scored = score_run(item, run)                              # 三门一次算完, 四通道共用
        attempt = str(run.get("attempt") or 1)                     # 轮次键统一成字符串
        d_ok = bool(scored["D"]["pass"])                           # 决策通道
        e_ok = bool(scored["E"]["pass"])                           # 表述通道
        f_block = scored["F"]                                      # 取数通道 (无工具面时为 None = N/A)
        f_ok = bool(f_block and f_block["pass"])
        is_data_item = str(item.get("id", "")).startswith("E5-D")  # D 类要三门齐过
        for name, value in (("D", d_ok),
                            ("F", f_ok if f_block else None),
                            ("E", e_ok),
                            ("composite", d_ok and e_ok and (f_ok if is_data_item else True))):
            if value is None:                                      # N/A 不进分母 (§6.5)
                continue
            chan.setdefault(name, {}).setdefault(attempt, []).append(bool(value))
    rng = random.Random(_BOOTSTRAP_SEED)  # noqa: S311 -- 固定种子: 报告数字必须可复现
    channels: dict[str, dict] = {}
    for name, by_attempt in sorted(chan.items()):
        rates = {a: (sum(v) / len(v) if v else None) for a, v in sorted(by_attempt.items())}
        vals = [r for r in rates.values() if r is not None]
        spread = (max(vals) - min(vals)) if len(vals) >= 2 else None
        n = len(next(iter(by_attempt.values()))) if by_attempt else 0        # 每轮样本数: 各轮同分母
        cnt = sum(len(v) for v in by_attempt.values())                       # 总样本数
        pooled = (sum(sum(v) for v in by_attempt.values()) / cnt) if cnt else None   # 合并比例 p̂
        p_value = None
        if spread is not None and n and pooled is not None and 0.0 < pooled < 1.0:
            null = [_range_under_exchangeability(n, pooled, rng) for _ in range(_RANGE_MC)]
            p_value = sum(1 for x in null if x >= spread - 1e-12) / len(null)         # 经验 p: 单侧
        # **退化判定必须独立于 p 值分支 (2026-10-10 修)**: 原先写成 elif, 于是 pooled 落在
        # (0,1) 开区间时永远走不到退化分支 —— 而"每轮期望成功数仅 1 次"的通道恰恰落在那里。
        # 判据: 期望成功数或期望失败数 < 2 即**分辨力不足** —— 极差统计分不出"稳不稳",
        # 此时极差恒 0 会被读成"稳", 那是塌缩不是稳定 (实测: 表述通道 pooled=0.036, n=28)。
        degenerate = bool(n and pooled is not None and (n * pooled < 2 or n * (1.0 - pooled) < 2))
        channels[name] = {"per_attempt": rates, "spread": spread, "n_per_attempt": n,
                          "pooled": (round(pooled, 4) if pooled is not None else None),
                          "tolerance": tol,                                    # 历史参照, 不驱动判定
                          "null_median_spread": (round(sorted(null)[len(null) // 2], 4)
                                                 if p_value is not None else None),
                          "p_value": (round(p_value, 4) if p_value is not None else None),
                          "degenerate": degenerate,                            # 全过/全不过/分辨力不足: 无稳定性信息
                          # 可用 = **有分辨力** 且 极差在零分布下不极端。两个条件缺一不可:
                          # 只看 p 会让"塌缩成一致失败"的通道拿到"可交换"的绿 (2026-10-10 实测踩到)。
                          "pass": (p_value is not None and p_value >= 0.05 and not degenerate)}
    comp = channels.get("composite") or {}                                 # 顶层键保持向后兼容
    return {
        "baseline": baseline,
        "per_attempt": comp.get("per_attempt") or {},                      # composite 通道的逐轮值
        "spread": comp.get("spread"),                                      # composite 极差
        "tolerance": tol,                                                  # 历史口径参照
        "p_value": comp.get("p_value"),
        "pass": bool(comp.get("pass")),
        "channels": channels,                                              # 逐通道标定结果
        "valid_channels": [k for k, v in channels.items() if v["pass"]],   # 可据以归因的通道
        "note": ("add-back ≡ 基线 (装回零件即还原 B3), 本项退化为**采样稳定性**检验; "
                 "判定按通道用可交换零假设下的极差分布标定 (p >= 0.05 即不构成超限), "
                 "固定 0.05 仅作历史参照 —— 它在 n=30 下统计上不可达"),
    }


def render_addback(result: dict) -> list[str]:
    """把 add-back 检验渲染成表 3 的行 (Markdown, 供 report.py 拼装)。

    逐通道出判定 (2026-10-10): 旧实现只出一行 composite 结论, 而实测显示稳定性
    **因通道而异** —— D/F 通道由可交换数据支撑, 只有 E 通道不可归因。只报一行会把
    "消融全部不可用"这个过宽的结论印在报告上。
    """
    per = "、".join(f"a{a}={v:.3f}" if v is not None else f"a{a}=N/A"
                    for a, v in result["per_attempt"].items()) or "无数据"
    spread = f"{result['spread']:.3f}" if result["spread"] is not None else "N/A"
    verdict = "✅ 稳定" if result["pass"] else "⚠️ 超限"
    rows = [
        f"| add-back 恢复检验 (装回该零件) | (装配 ≡ 基线 {result['baseline']}) "
        f"| 逐 attempt: {per} | 极差 {spread} (标定 p={result.get('p_value')}) → {verdict} |",
    ]
    channels = result.get("channels") or {}                    # 逐通道标定结果
    if channels:
        rows.append("| ⤷ 逐通道标定 (可交换零假设) | — | — "
                    "| " + "；".join(
                        f"{name} p={ch.get('p_value')} "
                        f"{'可用' if ch.get('pass') else '不可归因'}"
                        for name, ch in sorted(channels.items())) + " |")
    if not result["pass"]:
        valid = result.get("valid_channels") or []             # 仍可归因的通道
        # §4 明文: 恢复不了 ⇒ 怀疑随机波动, 该消融结论降级为「待复核」。但降级的**范围**
        # 必须写准: composite 不稳只说明合成口径不可用, 不等于所有通道都不可用。
        rows.append(
            "| ⤷ 超限后果 (§4) | — | — "
            f"| **composite 口径的 A1–A5 归因降级为「待复核」, 不进主表**; "
            f"仍由可交换数据支撑的通道: {('、'.join(valid) if valid else '无')} |")
    return rows


def exchangeability_check(runs: list[dict], items: list[dict]) -> dict:
    """探测采集表的重复轮次是否**可交换** (2026-10-10)。

    为什么要这道检查: 一切 repeat=3 的重复统计 (add-back 采样稳定性、T4 的多数票)
    都以「三次重复是同一系统的独立样本」为前提。实测 live 采集表
    (``temp/capture_live.json``) 违反该前提, 两个口径各自成立:

      * **连续量口径** (逐题"已陈述的 critical 断言占比"的均值): 11 个系统**无一例外**
        都是 attempt 1 最高 (B3: 0.847 / 0.733 / 0.749)。
      * **判据口径** (本函数实算的 E 门通过率, 全中才算过): 排除三轮读数**全等**的
        4 个系统 (B0/B1/B2b 三轮皆 0.000、B2a 三轮皆 0.033 —— 它们给不出次序证据)
        后, 剩余 **7 个有信息量的系统里 attempt 1 全部严格最高** (B3: 0.533 / 0.233 / 0.233)。

      两个口径一致的旁证: 三者的 route 分布与工具调用数几乎逐字相同
      (answer 230/230/229, tool_calls 0.69/0.69/0.68), 平均答案长度却是
      122.0 → 91.8 → 86.6 字符 —— **决策没变, 只有正文变短了**。

    在「三次重复可交换」的零假设下, 单个系统 attempt 1 严格最高的概率是 1/3;
    7 个有信息量系统全部如此的概率 ``(1/3)^7 ≈ 4.6e-4``。故这是**采集侧的轮次污染**,
    不是采样噪声。

    为什么它必须是阻断项而不是一句提示: 前提不成立时, add-back 的「极差 > 0.05」
    会被读成「采样噪声过大」, 而真实成因是轮次不可交换 —— 那等于把采集缺陷记到
    被测系统账上。与 E2 M7 的传输层域闸同一条道理: **归因要归对**。

    判据刻意避开平局: 只统计 attempt 1 **严格**高于其余各轮的系统数。替身批三轮
    逐字相同 ⇒ 计数为 0 ⇒ 恒判可交换, 不会误报。

    Args:
        runs: 逐 run 轨迹 (须含 system / item / attempt 三列)。
        items: 任务表 (取 assertions 判表述门)。

    Returns:
        ``{"exchangeable", "n_systems", "n_attempt1_strictly_max", "p_upper",
        "per_system", "note"}``。有效系统数 < 5 时 ``exchangeable=None``
        (样本太小, 不下结论, 也不阻断)。
    """
    # 本地: 三门判定 (与 aggregate / T4 同一份实现, 不另写第二套)
    from evals.ablation.metrics.composite import score_run

    by_item = {str(i.get("id")): i for i in items}
    # 逐门收集 (2026-10-10): 可交换性**因门而异**, 混成一份会把 D/F 的有效证据一起废掉。
    # 实测 attempt 1 严格最高的系统数: D 门 2/11 (p=0.11)、F 门 0/1 (p=1.00)、E 门 7/7 (p=4.6e-04)。
    acc: dict[str, dict[str, dict[str, list[bool]]]] = {}
    for run in runs:
        item = by_item.get(str(run.get("item")))
        if item is None:
            continue
        scored = score_run(item, run)                      # 三门一次算完, 逐门分槽
        system = str(run.get("system"))
        attempt = str(run.get("attempt") or 1)
        for gate in ("D", "F", "E"):
            block = scored.get(gate)
            if block is None:                              # 无工具面的系统 F 为 None: N/A 不进分母
                continue
            acc.setdefault(gate, {}).setdefault(system, {}).setdefault(attempt, []).append(
                bool(block.get("pass")))
    gates = {gate: _exchange_one(grouped) for gate, grouped in sorted(acc.items())}
    e_gate = gates.get("E") or {}                          # 顶层键沿用 E 门: 向后兼容既有消费方
    non_exchangeable = [g for g, v in gates.items() if v.get("exchangeable") is False]
    return {
        "exchangeable": e_gate.get("exchangeable"),
        "n_systems": e_gate.get("n_systems"),
        "n_attempt1_strictly_max": e_gate.get("n_attempt1_strictly_max"),
        "p_upper": e_gate.get("p_upper"),
        "per_system": e_gate.get("per_system"),
        "gates": gates,                                    # 逐门判定: 决定"哪些通道的结论可用"
        "non_exchangeable_gates": non_exchangeable,
        "note": ("attempt 1 在多数系统上某门通过率严格最高 ⇒ 该门的重复轮次不是独立样本, "
                 "依赖它的 repeat 类统计 (add-back 采样稳定性 / T4 多数票) 前提不成立; "
                 "该缺陷属采集侧, 不得记到被测系统账上。**按门判**: 只有被点名的门受影响, "
                 "其余门的结论仍由可交换数据支撑"),
    }


def _exchange_one(grouped: dict[str, dict[str, list[bool]]]) -> dict:
    """单门的可交换性判定 (逐系统 attempt 1 是否严格最高)。"""
    per_system = {s: {a: (round(sum(v) / len(v), 4) if v else None) for a, v in sorted(by.items())}
                  for s, by in sorted(grouped.items())}
    # 只认满三轮且三轮都有读数的系统: 缺轮的进不了这个判据
    eligible = {s: r for s, r in per_system.items()
                if len(r) >= 3 and all(v is not None for v in r.values())}
    # **有信息量**的子集才是判据的分母 (2026-10-10 实测修正): 三轮读数全等的系统给不出
    # 任何次序证据 —— 替身批全等是常态, 而实测里 B0/B1/B2b 三轮都是 0.000 (表述门全不过),
    # B2a 三轮都是 0.033, 它们**既不能支持也不能否证**可交换性。把它们算进分母会把
    # 7/7 的信号稀释成 7/11, 从而漏报。故分母 = "三轮不全等"的系统。
    informative = {s: r for s, r in eligible.items() if len(set(r.values())) > 1}
    strictly_max = [s for s, r in informative.items()
                    if r["1"] > max(v for a, v in r.items() if a != "1")]   # 严格 >: 平局(替身批)不计
    n, k = len(informative), len(strictly_max)
    p_upper = (1.0 / 3.0) ** k if k else 1.0     # 每系统"attempt1 严格最高"的零假设概率为 1/3
    if n < 4:                                     # 有信息量的系统太少: 不下结论也不阻断 (None 不进放行判定)
        exchangeable: Optional[bool] = None
    else:
        # 两个条件同时成立才判污染: 覆盖面够广 (≥80% 有信息量的系统) 且巧合概率够小 (p < 0.01)
        exchangeable = not (k >= max(3, int(0.8 * n)) and p_upper < 0.01)
    return {"exchangeable": exchangeable, "n_systems": n, "n_attempt1_strictly_max": k,
            "p_upper": p_upper, "per_system": per_system}
