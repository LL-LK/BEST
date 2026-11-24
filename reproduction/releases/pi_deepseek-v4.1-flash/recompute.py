"""Recompute the principal results from the archived score records."""

from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parent
WEIGHTS = {'toolset': .30, 'param': .25, 'convert': .15, 'redundant': .10, 'clarify': .10, 'reject': .10}


def records(path):
    with (ROOT / path).open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def document(path):
    return json.loads((ROOT / path).read_bytes())


def ratio(a, b):
    return a / b if b else None


def e1():
    rows = document('E1/grades.json')
    if len({row['pair_id'] for row in rows}) != len(rows) or len(rows) != 84:
        raise ValueError('E1 grade keys do not cover 84 units')
    points = []
    for repeat in (1, 2, 3):
        sample = [r for r in rows if r['repeat'] == repeat]
        if len(sample) != 28:
            raise ValueError('Incomplete E1 round')
        values = {metric: [r['dims'][metric] for r in sample if r['dims'][metric] is not None]
                  for metric in WEIGHTS}
        points.append(sum(WEIGHTS[k] * mean(v) for k, v in values.items() if v)
                      / sum(WEIGHTS[k] for k, v in values.items() if v))
    return {'weighted_by_round': points, 'weighted_mean': mean(points)}


def e3():
    rows = records('E3/counts.csv')
    if len({row['pair_id'] for row in rows}) != len(rows) or len(rows) != 216:
        raise ValueError('E3 grade keys do not cover 216 units')
    results = {}
    for tier, n in (('E3_fixture', 32), ('E3_live', 4)):
        for setting in ('S-A', 'S-B'):
            by_round = defaultdict(list)
            for r in rows:
                scope, _, condition, rep = r['pair_id'].split('/')
                if scope == tier and condition == setting:
                    by_round[rep].append(r)
            if set(by_round) != {'r1', 'r2', 'r3'} or any(len(part) != n for part in by_round.values()):
                raise ValueError('Incomplete E3 setting or replication')
            parts = [e3_rates(by_round[rep]) for rep in ('r1', 'r2', 'r3')]
            if tier == 'E3_live':
                combined = e3_rates([r for rep in by_round.values() for r in rep])
            else:
                series = {k: [v[k] for v in parts] for k in parts[0]}
                combined = {k: median(series[k]) if None not in series[k] else None for k in series}
            results[f'{tier}/{setting}'] = {'rounds': parts, **combined}
    return results


def e3_rates(rows):
    counts = {key: sum(int(row[key]) for row in rows) for key in (
        'critical_hit', 'critical_total', 'unsourced_num', 'numbers_total', 'unsupported_claim', 'claims_total')}
    return {'sfa': ratio(counts['critical_hit'], counts['critical_total']),
            'strict_pass': sum(row['pass'] == 'True' for row in rows) / len(rows),
            'ungr': ratio(counts['unsourced_num'], counts['numbers_total']),
            'ucr': ratio(counts['unsupported_claim'], counts['claims_total'])}


def e4():
    rows = document('E4/grades.json')
    if len({row['pair_id'] for row in rows}) != len(rows) or len(rows) != 159:
        raise ValueError('E4 grade keys do not cover 159 units')
    results = {}
    for key, n in (('ordinary', 105), ('compound', 54)):
        use = [r for r in rows if r['part'] == key]
        if len(use) != n:
            raise ValueError('Incomplete E4 section')
        results[key] = {'correct': sum(r['disposal_ok'] for r in use), 'n': n}
    return results


def e5():
    rows = records('E5/scores.csv')
    if len({(r['task'], r['arm'], r['replicate']) for r in rows}) != len(rows) or len(rows) != 2016:
        raise ValueError('E5 grade keys do not cover 2,016 units')
    values = defaultdict(dict)
    for r in rows:
        values[r['arm']][(r['task'], r['replicate'])] = r['e2e_success'].lower() == 'true'
    expected_arms = {'B0', 'B1', 'B2a', 'B2b', 'B3', 'A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'sham'}
    reference = set(values['B2b'])
    if set(values) != expected_arms or len(reference) != 168 or any(set(v) != reference for v in values.values()):
        raise ValueError('E5 arms do not share 168 cells')
    paired = defaultdict(int)
    for task, repeat in reference:
        paired[task] += values['B3'][(task, repeat)] - values['B2b'][(task, repeat)]
    counts = Counter({0: 1})
    for value in paired.values():
        swapped = Counter()
        for subtotal, frequency in counts.items():
            swapped[subtotal + value] += frequency
            swapped[subtotal - value] += frequency
        counts = swapped
    observed = abs(sum(paired.values()))
    return {'arms': {arm: {'passed': sum(v.values()), 'n': len(v)} for arm, v in sorted(values.items())},
            'B3_minus_B2b': sum(paired.values()) / 168,
            'B3_minus_B2b_exact_p': sum(n for s, n in counts.items() if abs(s) >= observed) / sum(counts.values())}


def main():
    result = {'E1': e1(), 'E3': e3(), 'E4': e4(), 'E5': e5()}
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
