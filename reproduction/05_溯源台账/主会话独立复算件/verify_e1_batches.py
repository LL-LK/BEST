# -*- coding: utf-8 -*-
"""
E1 三批评分结果的独立复算与 v72 论文呈现值比对。
目标：判定 v72 稿件 main.tex:273/291 的
      三组加权分 0.9429 / 0.9607 / 0.9554、均值 0.9530、样本标准差 0.0092、
      六维均值 0.9405/0.9659/1.0000/0.9881/0.8333/0.9722、
      中位汇总 0.9750（工具集合 0.9643、参数 1.0000）
是否可从归档证据复现。
证据：<WORKSPACE>\\04_实验数据\\E1_自然语言到工具调用\\实验产物\\07-答案键三批\\{3333,4444,5555}\\*_grade_result.json
"""
import json, os, hashlib, statistics

BASE = r"<WORKSPACE>\04_实验数据\E1_自然语言到工具调用\实验产物\07-答案键三批"
OUT = r"<WORKSPACE>\11_投稿包\_work\_复核\E1_独立复算与口径核对.json"
WEIGHTS = {'toolset': 0.30, 'param': 0.25, 'convert': 0.15,
           'redundant': 0.10, 'clarify': 0.10, 'reject': 0.10}
DIMS = list(WEIGHTS)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest().upper()


def load(batch):
    p = os.path.join(BASE, batch, batch + '_grade_result.json')
    raw = open(p, 'rb').read()
    j = json.loads(raw.decode('utf-8'))
    return j, sha256(p), len(raw)


def main():
    out = {'weights': WEIGHTS, 'batches': {}}

    # 1) 复现各批的逐维均值与加权总分
    per_task_by_dim = {}   # (batch, task, dim) -> score
    batch_summary = {}
    for b in ('3333', '4444', '5555'):
        j, digest, nbytes = load(b)
        out['batches'][b] = {'file': os.path.join(BASE, b, b + '_grade_result.json'),
                              'sha256': digest, 'bytes': nbytes,
                              'archived_weighted': j['summary']['weighted'],
                              'archived_dims': j['summary']['dims'],
                              'archived_dim_n': j['summary']['dim_n'],
                              'archived_pass': j['summary']['pass'],
                              'archived_warn': j['summary']['warn'],
                              'archived_red_line_tasks': j['summary']['red_line_tasks'],
                              'n_tasks': j['summary']['n_tasks']}
        batch_summary[b] = j['summary']
        for t in j['per_task']:
            tid = t.get('task') or t.get('task_id') or t.get('id')
            dims = t.get('dims') or {}
            for d in DIMS:
                if d in dims and dims[d] is not None:
                    per_task_by_dim[(b, tid, d)] = dims[d]

    # 2) 三组加权分与均值/标准差（复算）
    weighted_vals = []
    for b in ('3333', '4444', '5555'):
        s = batch_summary[b]
        recomputed = sum(WEIGHTS[d] * s['dims'][d] for d in DIMS)
        weighted_vals.append(s['weighted'])
        out['batches'][b]['recomputed_weighted'] = recomputed
        out['batches'][b]['matches_archive'] = abs(recomputed - s['weighted']) < 1e-9

    out['three_batch_weighted'] = weighted_vals
    out['mean_of_three'] = sum(weighted_vals) / 3
    out['sample_stdev_of_three'] = statistics.stdev(weighted_vals)
    out['paper_claims'] = {
        'per_batch': [0.9429, 0.9607, 0.9554],
        'mean': 0.9530, 'sample_stdev': 0.0092,
        'dim_means': {'toolset': 0.9405, 'param': 0.9659, 'convert': 1.0000,
                      'redundant': 0.9881, 'clarify': 0.8333, 'reject': 0.9722},
        'median_aggregation_weighted': 0.9750,
        'median_aggregation_dims': {'toolset': 0.9643, 'param': 1.0000},
    }
    out['verdict_per_batch'] = [
        {'batch': b, 'archive': round(weighted_vals[i], 4), 'paper': v,
         'match': abs(weighted_vals[i] - v) < 5e-5}
        for i, (b, v) in enumerate(zip(('3333', '4444', '5555'), out['paper_claims']['per_batch']))
    ]
    out['verdict_mean'] = {
        'archive_mean': out['mean_of_three'],
        'paper_mean': 0.9530,
        'match': abs(out['mean_of_three'] - 0.9530) < 5e-5,
        'note': '归档三批均值 0.9208；论文 0.9530 与之不符，且落在维度分数-3333答案-20261007.md '
                '所述「带 primer 估计 ≈0.95–0.97」的估计区间内',
    }

    # 3) 六维跨批均值（论文口径：三组回答的六维得分均值）
    dim_means = {}
    for d in DIMS:
        vals = []
        for b in ('3333', '4444', '5555'):
            vals.append(batch_summary[b]['dims'][d])
        dim_means[d] = sum(vals) / 3
    out['recomputed_dim_means_across_batches'] = dim_means
    out['verdict_dims'] = {
        d: {'archive': round(dim_means[d], 4), 'paper': out['paper_claims']['dim_means'][d],
            'match': abs(dim_means[d] - out['paper_claims']['dim_means'][d]) < 5e-5}
        for d in DIMS
    }

    # 4) 中位汇总口径：同题同维对三批取中位数，再按维度汇总并加权
    tasks = sorted({t for (b, t, d) in per_task_by_dim})
    median_dims = {}
    median_task_scores = {}
    for d in DIMS:
        per_task_median = []
        for t in tasks:
            vals = [per_task_by_dim[(b, t, d)] for b in ('3333', '4444', '5555')
                    if (b, t, d) in per_task_by_dim]
            if vals:
                per_task_median.append(statistics.median(vals))
        median_dims[d] = (sum(per_task_median) / len(per_task_median)) if per_task_median else None
        median_task_scores[d] = per_task_median
    median_weighted = sum(WEIGHTS[d] * median_dims[d] for d in DIMS if median_dims[d] is not None)
    out['median_aggregation'] = {
        'method': '同题同维对三批取中位数，再按维度汇总并按权重折算',
        'dims': median_dims,
        'weighted': median_weighted,
        'paper_weighted': 0.9750,
        'match': abs(median_weighted - 0.9750) < 5e-5,
        'paper_toolset': 0.9643,
        'recomputed_toolset': median_dims.get('toolset'),
    }

    # 5) 路由对齐率（维度分数报告口径）
    out['route_alignment_claimed'] = {'3333': '23/28 (82.1%)', '4444': '19/28 (67.9%)'}

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps({
        'three_batch_weighted': [round(v, 6) for v in weighted_vals],
        'mean_of_three': out['mean_of_three'],
        'sample_stdev_of_three': out['sample_stdev_of_three'],
        'paper_mean': 0.9530,
        'verdict_per_batch': out['verdict_per_batch'],
        'recomputed_dim_means_across_batches': {k: round(v, 6) for k, v in dim_means.items()},
        'verdict_dims': out['verdict_dims'],
        'median_aggregation': {'dims': {k: (round(v, 6) if v is not None else None) for k, v in median_dims.items()},
                                'weighted': median_weighted, 'paper_weighted': 0.9750,
                                'match': out['median_aggregation']['match']},
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
