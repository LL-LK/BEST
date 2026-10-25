# -*- coding: utf-8 -*-
"""
独立复算 E5 的全部预设对比与统计量（不依赖官方脚本结果，直接从 scores.json 重算）。
方法对齐 05_评审与验收\\BEST_v71_三项实验源头追查_20261023\\evidence\\confirmatory_stats.py：
  - 统计单位：题目；每题每臂先对三次重复取均值
  - 精确配对符号翻转：逐题整数成功数之差，按 |Σ| 统计量做精确置换
  - 题目聚类 bootstrap：10000 次，2.5%/97.5% 分位
  - 六项消融家族用 Holm 单调调整
输出：E5_对比与统计量独立复算.json
"""
import json, hashlib, random
from collections import defaultdict

SRC = r"<WORKSPACE>\04_实验数据\E5_消融\正式结果_2026-10-12\scores.json"
OUT = r"<WORKSPACE>\11_投稿包\_work\_复核\E5_对比与统计量独立复算.json"

ARMS = ('B0', 'B1', 'B2a', 'B2b', 'B3', 'A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'sham')


def paired_exact_p(integer_differences):
    """逐题整数差值的精确符号翻转检验；零差保留同等任务权重。"""
    distribution = {0: 1}
    for weight in map(abs, integer_differences):
        new = defaultdict(int)
        for total, mass in distribution.items():
            new[total + weight] += mass
            new[total - weight] += mass
        distribution = new
    observed = abs(sum(integer_differences))
    numerator = sum(mass for total, mass in distribution.items() if abs(total) >= observed)
    return numerator / float(sum(distribution.values()))


def holm(pvalues):
    """Holm 单调调整（与官方 holm() 同口径）。"""
    output = {}
    previous = 0.0
    for index, (name, value) in enumerate(sorted(pvalues.items(), key=lambda kv: kv[1])):
        previous = max(previous, min(1.0, (len(pvalues) - index) * value))
        output[name] = {'p_raw': value, 'p_holm': previous, 'reject_0_05': previous <= 0.05}
    return output


def main():
    raw = open(SRC, "rb").read()
    digest = hashlib.sha256(raw).hexdigest().upper()
    rows = json.loads(raw.decode("utf-8"))

    tasks = sorted({r["task"] for r in rows})
    counts = {a: defaultdict(int) for a in ARMS}
    for r in rows:
        counts[r["arm"]][r["task"]] += int(bool(r["e2e_success"]))
    classes = {r["task"]: r["decision_class"] for r in rows}

    def contrast(left, right, seed=20261012, resamples=10000):
        diffs = [counts[left][t] - counts[right][t] for t in tasks]
        rnd = random.Random(seed)
        n = len(diffs)
        boots = []
        for _ in range(resamples):
            s = 0
            for _ in range(n):
                s += diffs[rnd.randrange(n)]
            boots.append(s / 3.0 / n)
        boots.sort()
        lo = boots[int(0.025 * len(boots))]
        hi = boots[min(len(boots) - 1, int(0.975 * len(boots)))]
        return {
            'left': left, 'right': right, 'n_tasks': n,
            'left_rate': sum(counts[left][t] / 3.0 for t in tasks) / n,
            'right_rate': sum(counts[right][t] / 3.0 for t in tasks) / n,
            'delta_pp': sum(diffs) / 3.0 / n * 100.0,
            'task_cluster_bootstrap_95_ci_pp': [round(lo * 100, 2), round(hi * 100, 2)],
            'p_exact_paired_sign_flip': paired_exact_p(diffs),
            'nonzero_task_diffs': sum(1 for d in diffs if d != 0),
        }

    primary = contrast('B3', 'B2b')
    ablations = {a: contrast('B3', a) for a in ARMS if a.startswith('A')}
    adjusted = holm({a: r['p_exact_paired_sign_flip'] for a, r in ablations.items()})
    for a, r in ablations.items():
        r['holm'] = adjusted[a]
    baselines = {a: contrast('B3', a) for a in ('B0', 'B1', 'B2a')}
    length = contrast('A2', 'sham')

    # 描述性：各臂通过率、工具调用、输出 token
    usage = {}
    for a in ARMS:
        calls, outtok = [], []
        for r in rows:
            if r['arm'] != a:
                continue
            calls.append(r.get('tool_calls') or 0)
            outtok.append(sum((x.get('outputTokens') or 0) for x in (r.get('model_usage') or [])))
        usage[a] = {
            'mean_tool_calls': round(sum(calls) / len(calls), 4),
            'mean_output_tokens': round(sum(outtok) / len(outtok), 4),
        }

    b3c, b2bc = usage['B3']['mean_tool_calls'], usage['B2b']['mean_tool_calls']
    b3t, b2bt = usage['B3']['mean_output_tokens'], usage['B2b']['mean_output_tokens']

    # 分层：按 decision_class 的各臂通过率
    strata = {}
    for cat in sorted(set(classes.values())):
        subset = [t for t in tasks if classes[t] == cat]
        strata[cat] = {
            'n_tasks': len(subset),
            'rates': {a: round(sum(counts[a][t] / 3.0 for t in subset) / len(subset), 6) for a in ARMS},
        }

    result = {
        'source_file': SRC,
        'source_sha256': digest,
        'method': {
            'unit': 'task; three repetitions first averaged within task and arm',
            'sign_flip': 'exact paired sign-flip on per-task integer count differences, |sum| statistic, zero differences retain equal task weight',
            'bootstrap': 'task-cluster bootstrap, 10000 resamples, seed=20261012, percentile 2.5/97.5',
            'multiplicity': 'Holm monotone adjustment over the 6-ablation family (A1-A6); primary B3-B2b and length control excluded from the family',
        },
        'primary_B3_minus_B2b': primary,
        'baselines_B3_vs': baselines,
        'ablations_B3_vs': ablations,
        'length_control_A2_minus_sham': length,
        'descriptive_rates': {a: round(sum(counts[a][t] / 3.0 for t in tasks) / len(tasks), 6) for a in ARMS},
        'descriptive_usage': usage,
        'headline_reduction_checks': {
            'tool_calls_B3_minus_B2b_pct': round((b2bc - b3c) / b2bc * 100, 4),
            'output_tokens_B3_minus_B2b_pct': round((b2bt - b3t) / b2bt * 100, 4),
        },
        'by_decision_class': strata,
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        'primary_B3_minus_B2b': primary,
        'ablations_p_and_holm': {a: {'p_raw': r['p_exact_paired_sign_flip'],
                                      'p_holm': r['holm']['p_holm'],
                                      'delta_pp': round(r['delta_pp'], 4),
                                      'ci_pp': r['task_cluster_bootstrap_95_ci_pp']}
                                  for a, r in ablations.items()},
        'baselines': {a: {'delta_pp': round(r['delta_pp'], 4), 'p': r['p_exact_paired_sign_flip']} for a, r in baselines.items()},
        'A5_vs_B3_check': contrast('A5', 'B3'),
        'headline_reduction_checks': result['headline_reduction_checks'],
        'descriptive_usage': usage,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
