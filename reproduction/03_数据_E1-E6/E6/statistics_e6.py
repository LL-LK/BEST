"""E6 有依据的统计单位：每题实际重复、实际调用槽位与题号成组重抽。"""
# 标准库和第三方：数值区间、类别计数、固定种子重抽。
import math
from collections import Counter
import numpy as np

def wilson(k, n):
    """真实整数计数 Wilson；零样本返回缺失，不伪造分母100。"""
    if not isinstance(k, int) or not isinstance(n, int) or not 0 <= k <= n:
        raise ValueError("Wilson 需要有依据的实际整数计数")
    if n == 0:
        return None
    z = 1.959963984540054
    p, denom = k / n, 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [max(0, center - margin), min(1, center + margin)]

def modal(values, equal=None):
    """众数参考含并列、实际 n、pairwise；少于2次不能声称稳定。"""
    n = len(values)
    if not n:
        return {"point": None, "n": 0, "mode_count": 0, "pairwise": None, "wilson_95": None, "ref_index": None, "ties": []}
    equal = equal or (lambda a, b: a == b)
    counts = [sum(equal(v, reference) for v in values) for reference in values]
    k = max(counts)
    ref_index = counts.index(k)
    ties = [i for i, count in enumerate(counts) if count == k and not equal(values[i], values[ref_index])]
    pairs = [equal(values[i], values[j]) for i in range(n) for j in range(i + 1, n)]
    return {"point": k / n if n >= 2 else None, "n": n, "mode_count": k,
            "pairwise": sum(pairs) / len(pairs) if pairs else None, "pair_count": len(pairs),
            "wilson_95": wilson(k, n) if n >= 2 else None,
            "ref_index": ref_index, "ties": ties,
            "interval_limit": "数据选众数后的描述性Wilson，不是独立预指定二项试验或未来稳定率保证"}

def cluster_ci(values, seed=20261007):
    """题号为重抽单位；保持同题五次成组，不将160次视作160独立题。"""
    values = [float(v) for v in values if v is not None]
    if len(values) < 2:
        return {"point": float(np.mean(values)) if values else None, "task_units": len(values), "bootstrap_95": None}
    rng = np.random.default_rng(seed)
    sample = np.array(values)
    means = sample[rng.integers(0, len(values), size=(10000, len(values)))].mean(axis=1)
    return {"point": float(sample.mean()), "task_units": len(values), "bootstrap_95": [float(x) for x in np.quantile(means, [.025, .975])],
            "bootstrap_replicates": 10000, "seed": seed,
            "limit": "重抽题号反映任务集组成差异；全1时区间退化，不代表未来运行必然稳定"}

def alpha_nominal(units):
    """正确按同题重复构造名义α；无比较对或无类别方差返回缺失。"""
    units = [list(u) for u in units if len(u) >= 2]
    if not units:
        return {"alpha": None, "reason": "insufficient_pairs"}
    marginal = Counter(v for u in units for v in u)
    n = sum(marginal.values())
    observed = sum(sum(a != b for a in u for b in u) / (len(u) - 1) for u in units) / n
    expected = 1 - sum(c * (c - 1) for c in marginal.values()) / (n * (n - 1))
    return {"alpha": 1 - observed / expected if expected else None, "units": len(units), "observations": n,
            "reason": None if expected else "zero_category_variance"}
