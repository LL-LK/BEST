"""Recompute the numeric tables for the five-cohort writing handoff from sealed results."""

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().with_name('five-group-inputs')
ARCHIVE = ROOT / 'archive'
GROUPS = ('D0', 'D1', 'D2', 'P1', 'H1')
COMPARISONS = (('D1', 'D2'), ('P1', 'H1'), *((g, 'D0') for g in GROUPS[1:]))
ARMS = ('B0', 'B1', 'B2a', 'B2b', 'B3', 'A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'sham')
E1_WEIGHTS = dict(toolset=.30, param=.25, convert=.15, redundant=.10, clarify=.10, reject=.10)
SEED, N_BOOT, N_PERM = 20261118, 10_000, 100_000


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def pair_items(records, expected_count):
    common = set(records['D0'])
    if len(common) != expected_count or any(set(group) != common for group in records.values()):
        raise ValueError(f'Expected {expected_count} common item identifiers')
    items = sorted(common)
    return {g: np.array([[records[g][item][r] for r in (1, 2, 3)] for item in items], dtype=float)
            for g in GROUPS}


def estimate(totals, kind):
    num, den = totals[..., 0], totals[..., 1]
    ratios = np.divide(num, den, out=np.zeros_like(num), where=den > 0)
    if kind == 'E1':
        weights = np.array(list(E1_WEIGHTS.values())) * (den > 0)
        weighted = np.sum(ratios * weights, axis=-1) / np.sum(weights, axis=-1)
        return np.mean(weighted, axis=-1)
    rates = ratios[..., 0]
    return np.median(rates, axis=-1) if kind == 'SFA' else np.mean(rates, axis=-1)


def exact_binary_permutation(left, right):
    differences = np.rint((left - right)[..., 0].sum(axis=(1, 2))).astype(int)
    target = abs(int(differences.sum()))
    distribution = Counter({0: 1})
    for value in differences[differences != 0]:
        updated = Counter()
        for total, frequency in distribution.items():
            updated[total + value] += frequency
            updated[total - value] += frequency
        distribution = updated
    return sum(v for k, v in distribution.items() if abs(k) >= target) / sum(distribution.values())


def compare(arrays, kind):
    n = len(arrays['D0'])
    rng = np.random.default_rng(SEED)
    draw = rng.multinomial(n, np.full(n, 1 / n), size=N_BOOT)
    sums = {g: arr.sum(axis=0) for g, arr in arrays.items()}
    values = {g: float(estimate(a, kind)) for g, a in sums.items()}
    boots = {g: estimate((draw @ a.reshape(n, -1)).reshape(-1, *a.shape[1:]), kind)
             for g, a in arrays.items()}
    records = []
    for left, right in COMPARISONS:
        delta = values[left] - values[right]
        ci = np.quantile(boots[left] - boots[right], [.025, .975]).tolist()
        row = dict(left=left, right=right, n_tasks=n, n_keys=3*n, left_value=values[left],
                   right_value=values[right], delta=delta, ci95=ci, p=None, p_holm=None)
        if right != 'D0' and kind == 'binary':
            row['p'] = exact_binary_permutation(arrays[left], arrays[right])
        elif right != 'D0':
            outer = sums[left] + sums[right]
            difference = (arrays[left] - arrays[right]).reshape(n, -1)
            extreme = 0
            for _ in range(N_PERM // 2_000):
                switch = rng.integers(0, 2, size=(2_000, n))
                perm_left = sums[right] + (switch @ difference).reshape(-1, *outer.shape)
                perm_delta = estimate(perm_left, kind) - estimate(outer - perm_left, kind)
                extreme += np.count_nonzero(abs(perm_delta) >= abs(delta) - 1e-12)
            row['p'] = (int(extreme) + 1) / (N_PERM + 1)
        records.append(row)
    return {'estimates': values, 'contrasts': records}


def holm(rows):
    valid = sorted((row for row in rows if row['p'] is not None), key=lambda row: row['p'])
    bound = 0.0
    for i, row in enumerate(valid):
        bound = min(1.0, max(bound, (len(valid) - i) * row['p']))
        row['p_holm'] = bound


def e1(root, archive):
    report = root / 'results'
    grades = {g: defaultdict(dict) for g in GROUPS}
    histories = {}
    for rep in (1, 2, 3):
        histories[str(rep)] = read_json(archive / 'E1/v55_重新判分_20261020' / f'E1_sb{rep}.json')
        for grade in histories[str(rep)]['task_grades']:
            grades['D0'][grade['task_id']][rep] = grade['dims']
    summaries = {'D0': histories}
    for group in GROUPS[1:]:
        summaries[group] = read_json(report / f'{group}-E1-summary.json')['rounds']
        for row in read_csv(report / f'{group}-E1-vs-historical.csv'):
            _, task, _, repeat = row['pair_id'].split('/')
            grades[group][task].setdefault(int(repeat[1:]), {})[row['dimension']] = (
                float(row['new']) if row['new'] != '' else None)
    arrays = pair_items({g: {t: {r: [(d[k] or 0, int(d[k] is not None)) for k in E1_WEIGHTS]
                                  for r, d in rounds.items()}
                             for t, rounds in values.items()}
                         for g, values in grades.items()}, 28)
    result = compare(arrays, 'E1')
    for g in GROUPS:
        expected = np.mean([d['weighted'] for d in summaries[g].values()])
        if not np.isclose(result['estimates'][g], expected, atol=1e-10, rtol=0):
            raise ValueError(f'E1 report differs from authoritative summary for {g}')
    result['rounds'] = {g: {r: {k: value[k] for k in ('weighted', 'dims', 'dim_n', 'red_line_tasks')}
                            for r, value in rows.items()} for g, rows in summaries.items()}
    result['common_dimensions'] = []
    for a, b in COMPARISONS:
        for i, metric in enumerate(E1_WEIGHTS):
            left, right = arrays[a][:, :, i], arrays[b][:, :, i]
            common = (left[..., 1] > 0) & (right[..., 1] > 0)
            result['common_dimensions'].append(dict(left=a, right=b, dimension=metric,
                n_keys=int(common.sum()), delta=float((left[..., 0]-right[..., 0])[common].mean()) if common.any() else None))
    holm(result['contrasts'])
    return result


def e3(root):
    directory = root / 'results/E3/common-review/gpt-6-luna'
    rows = read_csv(directory / 'counts.csv')
    if len(rows) != 1080 or len({(r['cohort'], r['pair_id']) for r in rows}) != 1080:
        raise ValueError('Unexpected E3 shared review coverage')
    archived = read_json(directory / 'summary.json')
    result = {'fixture': {}, 'live': {}, 'live_tasks': [], 'pi_denominators': {},
              'within': {g: {k: archived[g]['fixture'][k] for k in ('sfa_difference', 'mcnemar')}
                         for g in GROUPS}}
    for cfg in ('S-A', 'S-B'):
        groups = {g: defaultdict(dict) for g in GROUPS}
        for row in rows:
            tier, item, config, repeat = row['pair_id'].split('/')
            if config == cfg and tier == 'E3_fixture':
                groups[row['cohort']][item][int(repeat[1:])] = [(int(row['critical_hit']), int(row['critical_total']))]
        result['fixture'][cfg] = compare(pair_items(groups, 32), 'SFA')
        for g in GROUPS:
            original = archived[g]['fixture']['systems'][cfg]['metrics']
            if not np.isclose(original['sfa']['median'], result['fixture'][cfg]['estimates'][g]):
                raise ValueError(f'E3 SFA differs from unified review for {g}/{cfg}')
        result['fixture'][cfg]['metrics'] = {g: archived[g]['fixture']['systems'][cfg] for g in GROUPS}
        result['live'][cfg] = {g: archived[g]['live'][cfg] for g in GROUPS}
    holm([row for cfg in result['fixture'].values() for row in cfg['contrasts']])
    equal = read_csv(root / 'results/E3/common-review/input-equivalence.csv')
    result['historical_live_diff_keys'] = [r['pair_id'] for r in equal if r['cohort']=='D0' and r['data']=='False']
    counts = defaultdict(lambda: [0, 0, 0])
    for row in rows:
        tier, item, cfg, _ = row['pair_id'].split('/')
        if tier == 'E3_live':
            entry = counts[(item, cfg, row['cohort'])]
            entry[0] += int(row['critical_hit'])
            entry[1] += int(row['critical_total'])
            entry[2] += row['pass'] == 'True'
    result['live_tasks'] = [dict(task=item, config=cfg, group=g, sfa_hit=v[0], sfa_total=v[1], passed=v[2])
                            for (item,cfg,g),v in sorted(counts.items())]
    pi = read_csv(directory/'P1-denominator-reconciliation.csv')
    if len(pi) != 216 or any(r['common_status'] != 'validated' for r in pi):
        raise ValueError('Incomplete Pi denominator ledger')
    for label, n, d in [('UNGR','unsourced_num','numbers_total'),('UCR','unsupported_claim','claims_total')]:
        result['pi_denominators'][label] = dict(
            archived=[sum(int(r[f'archived_{k}']) for r in pi) for k in (n,d)],
            common=[sum(int(r[f'common_{k}']) for r in pi) for k in (n,d)])
    return result


def e4(root):
    old = read_json(root/'archive-regression/E4/_复现/out/grade_r2.json')
    result = {}
    for category,key,roll,n in [('ordinary','P','main',35),('compound','C','compound',18)]:
        grades, summaries = {g: defaultdict(dict) for g in GROUPS}, {g: {} for g in GROUPS}
        for rep in (1,2,3):
            for g in GROUPS:
                if g=='D0':
                    rows = old[f'sb{rep}'][key]
                    summary = old[f'sb{rep}'][key+'_roll']
                else:
                    rows = read_json(root/f'results/E4/{g}/r{rep}.json')[category]
                    summary = read_json(root/f'results/E4/{g}/summary.json')[str(rep)][roll]
                if len(rows)!=n or any(not isinstance(r['disposal_ok'], bool) for r in rows):
                    raise ValueError(f'E4 coverage mismatch: {category}/{g}/r{rep}')
                if sum(r['disposal_ok'] for r in rows)!=summary['disposal_ok']:
                    raise ValueError(f'E4 result differs from authoritative summary: {category}/{g}/r{rep}')
                for r in rows:
                    grades[g][r['id']][rep] = [(int(r['disposal_ok']),1)]
                summaries[g][str(rep)] = summary
        arrays = pair_items(grades,n)
        values = compare(arrays,'binary') if category=='ordinary' else {
            'estimates':{g:float(estimate(a.sum(axis=0),'binary')) for g,a in arrays.items()}}
        if 'contrasts' in values:
            holm(values['contrasts'])
        values['rounds'] = summaries
        values['repeated_wrong'] = {g: {task:sum(1-cell[0][0] for cell in rounds.values())
                                       for task,rounds in data.items()
                                       if sum(1-cell[0][0] for cell in rounds.values())>=2}
                                    for g,data in grades.items()}
        result[category] = values
    return result


def e5(root, archive):
    result = {'arms':{},'by_class':{},'within':{},'tool_calls':{},'arm_definitions':{}}
    b3 = {g: defaultdict(dict) for g in GROUPS}
    for g in GROUPS:
        source = archive/'E5/scores.csv' if g=='D0' else root/f'results/E5/{g}/scores.csv'
        rows = read_csv(source)
        scores = {a:[] for a in ARMS}
        if len(rows)!=2016 or len({(r['task'],r['arm'],r['replicate']) for r in rows})!=2016:
            raise ValueError(f'E5 score matrix not unique: {g}')
        for row in rows:
            flag = row['e2e_success'].lower()
            if flag not in ('true','false'):
                raise ValueError(f'Non-binary E5 result: {g}')
            success = int(flag=='true')
            arm = row['arm']
            scores[arm].append((row['decision_class'],success,int(row['tool_calls'])))
            if arm=='B3':
                b3[g][row['task']][int(row['replicate'])] = [(success,1)]
        if any(len(v)!=168 for v in scores.values()):
            raise ValueError(f'Incomplete E5 arm {g}')
        result['arms'][g] = {a:sum(r[1] for r in v) for a,v in scores.items()}
        result['tool_calls'][g] = {a:{'mean':sum(r[2] for r in v)/len(v),'zero':sum(r[2]==0 for r in v)}
                                   for a,v in scores.items()}
        result['by_class'][g] = {a:{c:[sum(r[1] for r in scores[a] if r[0]==c),sum(r[0]==c for r in scores[a])]
                                   for c in sorted({row[0] for row in scores[a]})} for a in ('B2b','B3')}
        summary = read_json(root/('archive-regression/E5/historical-reanalysis.json' if g=='D0' else f'results/E5/{g}/analysis.json'))
        for a,name in [('B3','left_rate'),('B2b','right_rate')]:
            if not np.isclose(result['arms'][g][a]/168,summary['primary'][name]):
                raise ValueError(f'E5 primary rate differs from archived analysis: {g}/{a}')
        columns = ('delta','task_cluster_bootstrap_95_ci','p_exact_paired_sign_flip')
        length = summary['length_control_A2_minus_sham']
        result['within'][g] = dict(primary={k:summary['primary'][k] for k in columns},
            ablation={a:{**{k:r[k] for k in columns},'p_holm':r['holm']['p_holm']} for a,r in summary['ablation_holm_family'].items()},
            length_control={k:length[k] for k in columns},human_review=summary['human_review'])
    for a in ARMS:
        v = read_json(root/f'frozen-inputs/E5/arms/{a}.json')
        result['arm_definitions'][a] = {k:v[k] for k in ('allow','characters','guidance_blocks','token_exact_length_control')}
    result['cross_b3'] = compare(pair_items(b3,56),'binary')
    holm(result['cross_b3']['contrasts'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=ROOT)
    parser.add_argument('--archive', type=Path, default=ARCHIVE)
    parser.add_argument('--output', type=Path, default=Path('five-group-results.json'))
    args = parser.parse_args()
    root, archive = args.run, args.archive
    data = dict(seed=SEED,n_bootstrap=N_BOOT,n_permutation=N_PERM,e1=e1(root,archive),
                e3=e3(root),e4=e4(root),e5=e5(root,archive),
                coverage=[r for r in read_csv(root/'results/coverage.csv') if r['group'] in GROUPS[1:]],
                pi_metering=read_json(root/'results/P1-metering-summary.json'))
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(f'Wrote {args.output}; paired units E1=28, E3=32, E4=35, E5=56.')


if __name__=='__main__':
    main()
