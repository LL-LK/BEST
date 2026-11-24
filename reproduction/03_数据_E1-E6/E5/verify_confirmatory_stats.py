"""用非题库测试向量核验统计口径；不落盘虚构的实验矩阵。"""
from pathlib import Path
import json
import numpy as np
from scipy.stats import permutation_test
from confirmatory_stats import ARMS,analyze,paired_exact_p,holm

checks=[]
for vector in ([3,3,3,3],[3,-1,2,0],[0,0,0,0],[-3,-3,-3,-3]):
    scipy=float(permutation_test((np.array(vector),),lambda x,axis:np.sum(x,axis=axis),
        vectorized=True,permutation_type='samples',n_resamples=np.inf,alternative='two-sided').pvalue)
    own=paired_exact_p(vector)
    checks.append({'name':'paired-exact-versus-SciPy','vector':vector,'pass':abs(own-scipy)<1e-12})
tasks={f'fixture-{n:03d}':'technical_fixture' for n in range(56)}
records=[{'task':task,'arm':arm,'replicate':rep,'origin':'harness-live-confirmatory-v5',
          'e2e_success':arm=='B3' and rep==1} for task in tasks for arm in ARMS for rep in (1,2,3)]
result=analyze(records,tasks)
checks.append({'name':'one-success-in-three-is-one-third-not-majority-vote','pass':abs(result['primary']['delta']-1/3)<1e-12})
checks.append({'name':'ablation-family-includes-A6-only','pass':set(result['ablation_holm_family'])=={f'A{i}' for i in range(1,7)}})
for label,invalid in [('missing',records[:-1]),('duplicate',records[:-1]+[records[0]]),
                      ('historical', [{**records[0],'origin':'scripted'}]+records[1:])]:
    try:analyze(invalid,tasks);denied=False
    except ValueError:denied=True
    checks.append({'name':label+'-matrix-rejected','pass':denied})
adjusted=holm({'a':.01,'b':.02,'c':.03})
checks.append({'name':'Holm-adjusted-p-monotone','pass':[adjusted[x]['p_holm'] for x in ('a','b','c')]==[.03,.04,.04]})
assert all(c['pass'] for c in checks),checks
report={'schema':'e5-statistics-qualification-v5','logical_e5_units':0,
        'scope':'synthetic test vectors in memory only; no experimental records exported',
        'checks':checks,'all_pass':True}
(Path(__file__).parent/'statistics-qualification-v5.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,indent=2))
