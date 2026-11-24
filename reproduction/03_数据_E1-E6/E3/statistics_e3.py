"""E3 审核后的统计：成对题号bootstrap、精确McNemar和人机一致性。"""
from __future__ import annotations

# 标准库：精确二项概率和重复结果中位数。
import math
from statistics import median

# 第三方：本轮唯一数值依赖，用于矩阵与成组抽样。
import numpy as np


def ratio(numerator: float, denominator: float):
    """零分母明确返回缺测，不把没有样本解释为完美表现。"""
    return numerator / denominator if denominator else None


def agreement(a: list, b: list) -> dict:
    """计算配对有序评分一致性与残差ANOVA的ICC；常量指标记缺测。"""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(a) != len(b):
        raise ValueError("两组评分长度不一致")
    if len(pairs) < 2:
        return {"n": len(pairs), "p0": None, "kappa": None, "ac1": None,
                "weighted_kappa": None, "alpha_interval": None, "alpha_ordinal": None,
                "icc": None, "spearman": None, "mad": None, "note": "完整评分对不足2个"}
    x, y = np.asarray(pairs, dtype=float).T
    n = len(x)
    p0 = float(np.mean(x == y))
    binary = set(x) | set(y) <= {0.0, 1.0}
    result = {"n": n, "p0": p0, "kappa": None, "ac1": None}
    if binary:
        pa, pb = float(x.mean()), float(y.mean())
        expected = pa * pb + (1-pa)*(1-pb)
        result["kappa"] = ratio(p0-expected, 1-expected)
        q = (pa+pb)/2
        pe = 2*q*(1-q)
        result["ac1"] = (p0-pe)/(1-pe)
    values = sorted(set(x) | set(y))
    categories = {v: i for i, v in enumerate(values)}
    expected_mse = float(np.mean((x[:, None] - y[None, :])**2))
    observed_mse = float(np.mean((x-y)**2))
    result["weighted_kappa"] = None if expected_mse == 0 else 1-observed_mse/expected_mse
    combined = np.concatenate([x, y])
    expected_delta = float(np.sum((combined[:, None]-combined[None, :])**2)/(2*n*(2*n-1)))
    result["alpha_interval"] = None if expected_delta == 0 else 1-observed_mse/expected_delta
    # 有序α采用累计类别频数距离，中间类别全计、端点计一半。
    counts = {v: int(np.sum(combined == v)) for v in values}
    def ordinal_distance(u, v):
        """按Krippendorff的类别频数距离计算有序差异平方。"""
        if u == v:
            return 0.0
        lo, hi = sorted((categories[u], categories[v]))
        return (sum(counts[values[i]] for i in range(lo, hi+1))
                - (counts[u]+counts[v])/2)**2
    od = sum(ordinal_distance(u, v) for u, v in pairs)/n
    ed = sum(ordinal_distance(u, v) for u in combined for v in combined)/(2*n*(2*n-1))
    result["alpha_ordinal"] = None if ed == 0 else 1-od/ed
    matrix = np.column_stack([x, y])
    grand = matrix.mean()
    row, col = matrix.mean(axis=1), matrix.mean(axis=0)
    msr = float(2*np.sum((row-grand)**2)/(n-1))
    msc = float(n*np.sum((col-grand)**2))
    residual = matrix-row[:, None]-col[None, :]+grand
    mse = float(np.sum(residual**2)/(n-1))
    result["icc"] = ratio(msr-mse, msr+mse+2*(msc-mse)/n)
    def ranks(data):
        """为并列数据分配平均秩，用于Spearman相关。"""
        return np.array([sum(data < v)+(sum(data == v)+1)/2 for v in data])
    rx, ry = ranks(x), ranks(y)
    result["spearman"] = (None if rx.std() == 0 or ry.std() == 0
                          else float(np.corrcoef(rx, ry)[0, 1]))
    result["mad"] = float(np.mean(abs(x-y)))
    result["note"] = "退化分布下未定义统计量记null；人机ICC按固定评阅者绝对一致ICC(A,1)解释"
    return result


def metrics(rows: list[dict], slr_ids: list[str]) -> dict:
    """从逐项计数计算单个系统一次重复的主指标及原始分母。"""
    fields = ("critical_hit", "critical_total", "qualifier_hit", "qualifier_total", "numbers_total",
              "unsourced_num", "claims_total", "unsupported_claim", "fatal_num")
    counts = {field: sum(r["counts"][field] for r in rows) for field in fields}
    timing = [r for r in rows if r["item_id"] in slr_ids]
    return {"sfa": ratio(counts["critical_hit"], counts["critical_total"]),
            "ungr": ratio(counts["unsourced_num"], counts["numbers_total"]),
            "ucr": ratio(counts["unsupported_claim"], counts["claims_total"]),
            "slr": ratio(sum(r["counts"]["static_as_lc"] for r in timing), len(timing)),
            "rqc": ratio(counts["qualifier_hit"], counts["qualifier_total"]),
            "pass_rate": ratio(sum(r["counts"]["pass"] for r in rows), len(rows)),
            "counts": counts, "n_items": len(rows), "slr_denominator": len(timing)}


def mcnemar(a: list[bool], b: list[bool]) -> dict:
    """对同题三次多数合格判定进行双侧精确McNemar检验。"""
    if len(a) != len(b) or not a:
        raise ValueError("McNemar需要非空配对题集")
    n10 = sum(x and not y for x, y in zip(a, b))
    n01 = sum(y and not x for x, y in zip(a, b))
    n = n10+n01
    p = min(1.0, 2*sum(math.comb(n, k) for k in range(min(n10, n01)+1))/2**n) if n else 1.0
    return {"n_items": len(a), "a_only_pass": n10, "b_only_pass": n01, "p_exact_two_sided": p}


def summarize(rows: list[dict], item_ids: list[str], slr_ids: list[str], bootstrap_n=10000) -> dict:
    """仅对完整主测计算汇总；题号成组重抽保留配对和重复结构。"""
    lookup = {(r["group"], r["item_id"], r["repeat"]): r for r in rows}
    needed = {(g, item, repeat) for g in ("S-A", "S-B") for item in item_ids for repeat in (1, 2, 3)}
    if len(lookup) != len(rows) or set(lookup) != needed:
        raise ValueError("主测评分重复或不完整，禁止出正式主指标")
    result = {"systems": {}, "n_independent_items": len(item_ids), "bootstrap_resamples": bootstrap_n}
    for group in ("S-A", "S-B"):
        repeats = [metrics([lookup[(group, item, repeat)] for item in item_ids], slr_ids) for repeat in (1, 2, 3)]
        summary = {}
        for field in ("sfa", "ungr", "ucr", "slr", "rqc", "pass_rate"):
            values = [r[field] for r in repeats]
            complete = all(v is not None for v in values)
            summary[field] = {"median": median(values) if complete else None,
                              "range": [min(values), max(values)] if complete else None,
                              "per_repeat": values, "note": None if complete else "至少一次重复分母为0"}
        result["systems"][group] = {"metrics": summary, "per_repeat": repeats}
    passes = [[sum(lookup[(g, i, r)]["counts"]["pass"] for r in (1, 2, 3)) >= 2 for i in item_ids]
              for g in ("S-A", "S-B")]
    result["mcnemar"] = mcnemar(*passes)
    # SFA按题聚合计数；每个抽样同时取两组与三次结果，再算三次差的中位数。
    arrays = {}
    for g in ("S-A", "S-B"):
        arrays[g] = np.array([[[lookup[(g, i, r)]["counts"][f] for f in ("critical_hit", "critical_total")]
                               for i in item_ids] for r in (1, 2, 3)], dtype=float)
    rng = np.random.default_rng(20261006)
    indices = rng.integers(0, len(item_ids), size=(bootstrap_n, len(item_ids)))
    sample_scores = {}
    for g, data in arrays.items():
        totals = data[:, indices, :].sum(axis=2)
        sample_scores[g] = np.median(totals[:, :, 0]/totals[:, :, 1], axis=0)
    delta = sample_scores["S-A"]-sample_scores["S-B"]
    result["sfa_difference"] = {"point": result["systems"]["S-A"]["metrics"]["sfa"]["median"]-
                                          result["systems"]["S-B"]["metrics"]["sfa"]["median"],
                                "bootstrap_95": np.quantile(delta, [0.025, 0.975]).tolist(), "unit": "paired_item"}
    result["by_axis"] = {axis: {g: [metrics([lookup[(g, i, r)] for i in item_ids if i[3] == axis], slr_ids)
                                       for r in (1, 2, 3)] for g in ("S-A", "S-B")}
                         for axis in "ABCDEFG"}
    return result
