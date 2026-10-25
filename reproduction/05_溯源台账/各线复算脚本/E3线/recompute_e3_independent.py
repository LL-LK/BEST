# -*- coding: utf-8 -*-
"""
E3 独立重算（只读原始归档；所有产物写入 <WORKSPACE>\\11_投稿包\\_work\\E1E2E3\\）
不复用 05_评审与验收 的脚本输出，只从 original-evidence.tar.gz + 当前结果 CSV 重算。
"""
from pathlib import Path
from collections import defaultdict, Counter
import json, csv, statistics, hashlib, tarfile, io, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

E3 = Path(r'<WORKSPACE>\04_实验数据\E3_科学忠实性\实验产物')
ARC = E3 / '05_原始实验归档'
CUR = E3 / '01_当前结果'
WORK = Path(r'<WORKSPACE>\11_投稿包\_work\E1E2E3')
DIAG = WORK / '_work_diag'
DIAG.mkdir(parents=True, exist_ok=True)


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def load(p):
    return json.loads(Path(p).read_text('utf-8-sig'))


# ---------- 1. 载入归档 ----------
bundle = load(ARC / 'bundle.json')
items = {x['id']: x for x in bundle['items']}
SLR_IDS = set(bundle['slr_ids'])
MAIN_IDS = [x['id'] for x in bundle['items'] if x['tier'] == 'fixture']
print('slr_ids (n=%d):' % len(SLR_IDS), sorted(SLR_IDS))
print('bundle fixture items (n=%d):' % len(MAIN_IDS))
answers, scores, score_hashes = {}, {}, {}
tar_members = {}
with tarfile.open(ARC / 'original-evidence.tar.gz', 'r:gz') as z:
    for n in z.getnames():
        tar_members[n] = None
        if n.endswith('.json') and ('/answers/' in n or '/scores/' in n):
            raw = z.extractfile(n).read()
            a = json.loads(raw)
            if '/answers/' in n:
                answers[a['key']] = a
            else:
                scores[a['key']] = a
                score_hashes[a['key']] = hashlib.sha256(raw).hexdigest()

print('bundle items:', len(items), '| archive answers:', len(answers), '| archive scores:', len(scores))
print('tier counter:', Counter(a['tier'] for a in answers.values()))

# ---------- 2. 逐回答台账（fixture = 离线主测 192 份） ----------
ledger = []
for key, a in answers.items():
    if a['tier'] != 'fixture':
        continue
    s = scores[key]
    c = s['counts']
    assert c['unsupported_claim'] == sum(x['classification'] == 'unsupported' for x in s['score']['claims'])
    assert c['claims_total'] == len(s['score']['claims'])
    ledger.append({
        'key': key, 'group': a['group'], 'item_id': a['item_id'], 'repeat': a['repeat'],
        'claims_total': c['claims_total'], 'unsupported_claim': c['unsupported_claim'],
        'critical_hit': c['critical_hit'], 'critical_total': c['critical_total'],
        'qualifier_hit': c['qualifier_hit'], 'qualifier_total': c['qualifier_total'],
        'numbers_total': c['numbers_total'], 'unsourced_num': c['unsourced_num'],
        'fatal_num': c['fatal_num'], 'static_as_lc': c['static_as_lc'],
        'pass': c['pass'],
    })

# ---------- 3. 每组每重复的六指标 ----------
metrics = {}
for group in ['S-A', 'S-B']:
    rs = [r for r in ledger if r['group'] == group]
    per_repeat = []
    for rep in (1, 2, 3):
        xs = [r for r in rs if r['repeat'] == rep]
        agg = lambda f: sum(f(x) for x in xs)
        crit_hit, crit_tot = agg(lambda r: r['critical_hit']), agg(lambda r: r['critical_total'])
        qual_hit, qual_tot = agg(lambda r: r['qualifier_hit']), agg(lambda r: r['qualifier_total'])
        num_tot, uns_num = agg(lambda r: r['numbers_total']), agg(lambda r: r['unsourced_num'])
        cl_tot, cl_uns = agg(lambda r: r['claims_total']), agg(lambda r: r['unsupported_claim'])
        fatal = agg(lambda r: r['fatal_num'])
        timing = [r for r in xs if r['item_id'] in SLR_IDS]
        static_lc = sum(r['static_as_lc'] for r in timing)
        per_repeat.append({
            'repeat': rep, 'answers': len(xs),
            'critical_hit': crit_hit, 'critical_total': crit_tot, 'sfa': crit_hit / crit_tot,
            'qualifier_hit': qual_hit, 'qualifier_total': qual_tot, 'rqc': qual_hit / qual_tot,
            'numbers_total': num_tot, 'unsourced_num': uns_num, 'ungr': uns_num / num_tot,
            'claims_total': cl_tot, 'unsupported_claim': cl_uns, 'ucr': cl_uns / cl_tot,
            'fatal_num': fatal, 'slr_denominator': len(timing),
            'static_as_lc_sum': static_lc, 'slr': static_lc / len(timing),
            'pass_rate': sum(r['pass'] for r in xs) / len(xs),
        })
    med = lambda k: statistics.median(p[k] for p in per_repeat)
    metrics[group] = {
        'per_repeat': per_repeat,
        'median': {k: med(k) for k in ['sfa', 'rqc', 'ungr', 'ucr', 'slr', 'pass_rate']},
        'pooled_ucr_diagnostic_only': sum(p['unsupported_claim'] for p in per_repeat) / sum(p['claims_total'] for p in per_repeat),
        'answers_with_unsupported_claim': sum(r['unsupported_claim'] > 0 for r in rs),
        'passed_answers': sum(r['pass'] for r in rs),
        'passed_with_unsupported_claim': sum(r['pass'] and r['unsupported_claim'] > 0 for r in rs),
        'n_answers': len(rs),
    }

print('\n--- 每组每重复 ---')
for g in ['S-A', 'S-B']:
    for p in metrics[g]['per_repeat']:
        print(f"{g} r{p['repeat']}: SFA={p['critical_hit']}/{p['critical_total']}={p['sfa']:.6%} "
              f"UCR={p['unsupported_claim']}/{p['claims_total']}={p['ucr']:.6%} "
              f"UNGR={p['unsourced_num']}/{p['numbers_total']}={p['ungr']:.6%} "
              f"RQC={p['qualifier_hit']}/{p['qualifier_total']}={p['rqc']:.6%} "
              f"SLR={p['fatal_num']}/{p['slr_denominator']}={p['slr']:.6%} "
              f"pass={p['pass_rate']:.4%}")
    m = metrics[g]['median']
    print(f"{g} MEDIAN: SFA={m['sfa']:.4%} UCR={m['ucr']:.6%} UNGR={m['ungr']:.4%} "
          f"RQC={m['rqc']:.4%} SLR={m['slr']:.4%} pass={m['pass_rate']:.4%} | "
          f"pooled UCR(diag)={metrics[g]['pooled_ucr_diagnostic_only']:.6%}")
    print(f"{g} 三重复计数: 有无支撑主张={metrics[g]['answers_with_unsupported_claim']} "
          f"pass={metrics[g]['passed_answers']} pass且仍含无支撑={metrics[g]['passed_with_unsupported_claim']}")

# ---------- 3b. 配对题号自助法 95% 区间 + 精确 McNemar（按 statistics_e3.py 同种子同算法复算） ----------
import numpy as np
import math

lookup = {(r['group'], r['item_id'], r['repeat']): r for r in ledger}
assert set(lookup) == {(g, i, rep) for g in ('S-A', 'S-B') for i in MAIN_IDS for rep in (1, 2, 3)}
arrays = {}
for g in ('S-A', 'S-B'):
    arrays[g] = np.array([[[lookup[(g, i, rep)]['critical_hit'], lookup[(g, i, rep)]['critical_total']]
                           for i in MAIN_IDS] for rep in (1, 2, 3)], dtype=float)
rng = np.random.default_rng(20261006)
indices = rng.integers(0, len(MAIN_IDS), size=(10000, len(MAIN_IDS)))
sample_scores = {}
for g, data in arrays.items():
    totals = data[:, indices, :].sum(axis=2)
    sample_scores[g] = np.median(totals[:, :, 0] / totals[:, :, 1], axis=0)
delta = sample_scores['S-A'] - sample_scores['S-B']
boot = {'point': metrics['S-A']['median']['sfa'] - metrics['S-B']['median']['sfa'],
        'bootstrap_95': (np.quantile(delta, [0.025, 0.975]) * 100).tolist(), 'unit': 'paired_item',
        'bootstrap_resamples': 10000, 'seed': 20261006}


def mcnemar(a, b):
    n01 = sum(y and not x for x, y in zip(a, b))
    n10 = sum(x and not y for x, y in zip(a, b))
    n = n10 + n01
    p = min(1.0, 2 * sum(math.comb(n, k) for k in range(min(n10, n01) + 1)) / 2 ** n) if n else 1.0
    return {'n_items': len(a), 'a_only_pass': n10, 'b_only_pass': n01, 'p_exact_two_sided': p}


passes = [[sum(lookup[(g, i, r)]['pass'] for r in (1, 2, 3)) >= 2 for i in MAIN_IDS]
          for g in ('S-A', 'S-B')]
mcn = mcnemar(*passes)
print(f"\n配对题号自助法 SFA 差值 95%区间 = {boot['bootstrap_95'][0]:.2f} ~ {boot['bootstrap_95'][1]:.2f} 个百分点"
      f"（点估计 {boot['point']*100:.2f}）")
print(f"严格合格率精确 McNemar: n_items={mcn['n_items']} S-A仅通过={mcn['a_only_pass']} "
      f"S-B仅通过={mcn['b_only_pass']} p={mcn['p_exact_two_sided']}")

# ---------- 4. 与当前结果 CSV 逐项核对 ----------
cur_sum = {}
with (CUR / 'E3-指标汇总.csv').open(encoding='utf-8-sig', newline='') as f:
    for r in csv.DictReader(f):
        cur_sum[(r['分析'], r['组别'], r['指标'])] = r
name_map = {'sfa': 'sfa', 'ungr': 'ungr', 'ucr': 'ucr', 'slr': 'slr', 'rqc': 'rqc', 'pass_rate': 'pass_rate'}
cmp_rows = []
for (ana, grp, met), r in cur_sum.items():
    if ana != '原始主测32题' or met not in name_map:
        continue
    mine = metrics[grp]['median'][met]
    rep_vals = [str(p[met]) for p in metrics[grp]['per_repeat']]
    ok = (abs(float(r['中位数']) - mine) < 1e-12
          and abs(float(r['重复1']) - float(rep_vals[0])) < 1e-12
          and abs(float(r['重复2']) - float(rep_vals[1])) < 1e-12
          and abs(float(r['重复3']) - float(rep_vals[2])) < 1e-12)
    cmp_rows.append({'分析': ana, '组别': grp, '指标': met, 'CSV中位数': float(r['中位数']),
                     '重算中位数': mine, '一致': ok})
print('\n--- 与 E3-指标汇总.csv 对照（原始主测32题）---')
for c in cmp_rows:
    print(f"  {c['组别']:4s} {c['指标']:9s} CSV={c['CSV中位数']:.12f} 重算={c['重算中位数']:.12f} 一致={c['一致']}")
assert all(c['一致'] for c in cmp_rows), '指标汇总.csv 与重算不一致'

# 逐回答计数 CSV 对照
cur_counts = {}
with (CUR / 'E3-逐回答计数.csv').open(encoding='utf-8-sig', newline='') as f:
    for r in csv.DictReader(f):
        cur_counts[r['key']] = r
mismatch = []
for r in ledger:
    c = cur_counts.get(r['key'])
    if c is None:
        mismatch.append((r['key'], 'missing'))
        continue
    if int(c['claims_total']) != r['claims_total'] or int(c['unsupported_claim']) != r['unsupported_claim']:
        mismatch.append((r['key'], c['claims_total'], c['unsupported_claim'], r['claims_total'], r['unsupported_claim']))
print(f"\n逐回答计数.csv 对照: archive={len(ledger)} csv={len(cur_counts)} 不一致={len(mismatch)}")
if mismatch:
    print(mismatch[:10])

# ---------- 5. 496 条无支撑主张归档核对 ----------
V71 = Path(r'<WORKSPACE>\05_评审与验收\BEST_v71_三项实验源头追查_20261023')
with (V71 / 'e3_unsupported_claims.csv').open(encoding='utf-8-sig', newline='') as f:
    v71_claims = list(csv.DictReader(f))
archive_claims = []
for key, s in scores.items():
    a = answers.get(key)
    if a is None or a['tier'] != 'fixture':
        continue
    for cl in s['score']['claims']:
        if cl['classification'] == 'unsupported':
            archive_claims.append({'key': key, 'group': a['group'], 'item_id': a['item_id'],
                                   'repeat': a['repeat'], 'quote': cl['quote'],
                                   'archived_reason': cl['reason'], 'source': cl['source'],
                                   'score_sha256': score_hashes[key]})
print(f"\n无支撑主张: 归档={len(archive_claims)}  v71 CSV={len(v71_claims)}")
arch_by = Counter((c['key'], c['quote']) for c in archive_claims)
csv_by = Counter((c['key'], c['quote']) for c in v71_claims)
print('  归档与v71 CSV 逐条(键+引文)一致:', arch_by == csv_by)
missing_in_csv = arch_by - csv_by
extra_in_csv = csv_by - arch_by
print('  归档有而CSV无:', sum(missing_in_csv.values()), ' CSV有而归档无:', sum(extra_in_csv.values()))
# 字段完整性
blank_reason = [c for c in v71_claims if not (c['archived_reason'] or '').strip()]
blank_quote = [c for c in v71_claims if not (c['quote'] or '').strip()]
blank_source = [c for c in v71_claims if not (c['source'] or '').strip()]
blank_sha = [c for c in v71_claims if not (c['score_sha256'] or '').strip()]
print(f"  完整性: quote空={len(blank_quote)} reason空={len(blank_reason)} source空={len(blank_source)} sha空={len(blank_sha)}")
print('  source 非空样例:', [c['source'] for c in v71_claims if (c['source'] or '').strip()][:3])
# sha 是否与归档 score 文件哈希一致
sha_ok = sum(1 for c in v71_claims if c['score_sha256'] == score_hashes.get(c['key']))
print(f"  score_sha256 与归档原始 score 文件一致: {sha_ok}/{len(v71_claims)}")
# quote 是否真出现在回答正文中
not_in_answer = []
for c in v71_claims:
    a = answers.get(c['key'])
    if a and c['quote'] and c['quote'] not in a['answer']:
        not_in_answer.append((c['key'], c['quote'][:40]))
print(f"  quote 可在原始回答正文中定位: {len(v71_claims)-len(not_in_answer)}/{len(v71_claims)}；未定位 {len(not_in_answer)}")
if not_in_answer:
    print('  未定位样例:', not_in_answer[:5])
# 按组分布
print('  按组:', Counter(c['group'] for c in v71_claims))

# ---------- 6. 判定者身份 / 独立性 ----------
man = load(ARC / 'manifest.json')
prov = {'primary_judge': man['protocol']['primary_judge'],
        'self_rating_risk': man['protocol']['self_rating_risk'],
        'design': man['protocol']['design'],
        'limitations': man['protocol'].get('limitations')}
tsum = load(E3 / '02_教师反馈' / 'teacher-review-summary.json')

# ---------- 7. 证据文件 SHA256 ----------
ev_files = [
    ARC / 'original-evidence.tar.gz', ARC / 'bundle.json', ARC / 'manifest.json',
    ARC / 'finalization-manifest.json', ARC / 'final-audit.json', ARC / 'agreement.json',
    ARC / 'judge-selftest.json', ARC / 'expert-package-status.json', ARC / 'PROTOCOL.md',
    ARC / 'ANNOTATION-NOTES.md', ARC / 'rating-revision-audit.json', ARC / 'prescreen.json',
    ARC / 'report.json', ARC / 'paired-bootstrap-all-metrics.json', ARC / 'source-checks.json',
    CUR / 'E3-指标汇总.csv', CUR / 'E3-主测分母.csv', CUR / 'E3-逐回答计数.csv',
    CUR / 'E3-main-recomputed.json', CUR / 'E3-online-ancillary.json',
    CUR / 'E3-sensitivity-exclude-E04.json', CUR / 'FINAL-RESULTS.json',
    E3 / '02_教师反馈' / 'teacher-review-summary.json', E3 / '02_教师反馈' / 'teacher-review-records.json',
    E3 / '02_教师反馈' / 'review-audit.json', E3 / '02_教师反馈' / 'teacher-issues.json',
    E3 / '02_教师反馈' / 'E3-老师审核表-修复版.xlsx',
    E3 / '04_匿名审核材料' / 'E3-全量匿名审核表.xlsx', E3 / '04_匿名审核材料' / 'E3-匿名审核简表.xlsx',
    E3 / '03_四条核验' / 'four-entry-verification.json', E3 / '03_四条核验' / 'verification-audit.json',
    E3 / '辅助程序' / 'scoring.py', E3 / '辅助程序' / 'statistics_e3.py',
    E3 / '辅助程序' / 'prepare.py', E3 / '辅助程序' / 'review.py',
    V71 / 'e3_unsupported_claims.csv', V71 / 'e3_answer_counts.csv',
    V71 / 'e3_recomputed.json', V71 / 'e3_score_validation.json',
    V71 / 'evidence' / 'E3_B03_r2_original.json',
    V71 / 'scripts' / 'validate_e3_scores.py', V71 / 'scripts' / 'trace_sources.py',
    Path(r'<WORKSPACE>\10_脱敏复现包\BEST_v72_图2嵌入正文确认_20261023\source\main.tex'),
    Path(r'<WORKSPACE>\10_脱敏复现包\BEST_v72_图2嵌入正文确认_20261023\source\supplementary_material.tex'),
    Path(r'<WORKSPACE>\10_脱敏复现包\BEST_v72_图2嵌入正文确认_20261023\evaluation_materials\E3_main_32.json'),
    Path(r'<WORKSPACE>\10_脱敏复现包\BEST_v72_图2嵌入正文确认_20261023\evaluation_materials\E3_online_4.json'),
]
shas = [{'path': str(p), 'bytes': p.stat().st_size, 'sha256': sha(p)}
        for p in ev_files if p.exists()]
missing_ev = [str(p) for p in ev_files if not p.exists()]

out = {
    'generated_by': 'E1E2E3证据官 独立重算（只读归档）',
    'slr_ids': sorted(SLR_IDS),
    'main_ids_n': len(MAIN_IDS),
    'ledger_n': len(ledger),
    'metrics': metrics,
    'bootstrap_sfa_diff': boot,
    'mcnemar_strict_pass': mcn,
    'metric_summary_cmp': cmp_rows,
    'claims_archive_n': len(archive_claims),
    'claims_v71_csv_n': len(v71_claims),
    'claims_key_quote_match': arch_by == csv_by,
    'claims_blank_quote': len(blank_quote), 'claims_blank_reason': len(blank_reason),
    'claims_blank_source': len(blank_source), 'claims_blank_sha': len(blank_sha),
    'claims_sha_match_archive': sha_ok,
    'claims_quote_locate_ok': len(v71_claims) - len(not_in_answer),
    'claims_quote_locate_fail': not_in_answer[:20],
    'claims_by_group': dict(Counter(c['group'] for c in v71_claims)),
    'rating_provenance': prov,
    'teacher_review_status': tsum['status'],
    'teacher_review_counts': {k: tsum.get(k) for k in
                               ['expected_materials', 'materials_matched', 'real_answers_expected',
                                'real_answers_with_feedback', 'raw_ticks', 'raw_comments',
                                'agreement', 'protocol_complete', 'full_scorecards_imported']},
    'teacher_reviewer_metadata': tsum['reviewer_metadata'],
    'evidence_sha256': shas,
    'evidence_missing': missing_ev,
}
(DIAG / 'e3_recompute_v1.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf8')
print('\n证据文件 SHA256 已写入:', DIAG / 'e3_recompute_v1.json')
print('缺失:', missing_ev)
print('全部断言通过 ✓')
