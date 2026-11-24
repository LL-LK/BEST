"""固定 56×12×3 的任务均值、精确配对符号翻转及任务聚类 bootstrap。"""
from collections import Counter, defaultdict
from functools import lru_cache
import json
import math
from pathlib import Path
import numpy as np

ARMS=('B0','B1','B2a','B2b','B3','A1','A2','A3','A4','A5','A6','sham')
SEED=20261012

def paired_exact_p(integer_differences):
    """对每题三次成功数之差做精确符号翻转；零差保留同等任务权重。"""
    distribution={0:1}
    for weight in map(abs,integer_differences):
        new=defaultdict(int)
        for total,mass in distribution.items():
            new[total+weight]+=mass
            new[total-weight]+=mass
        distribution=new
    observed=abs(sum(integer_differences))
    numerator=sum(mass for total,mass in distribution.items() if abs(total)>=observed)
    return numerator/sum(distribution.values())

def holm(pvalues):
    """六项消融家族的单调 Holm 调整 p；主比较与长度比较不混入。"""
    output={};previous=0.0
    for index,(name,value) in enumerate(sorted(pvalues.items(),key=lambda pair:pair[1])):
        previous=max(previous,min(1.0,(len(pvalues)-index)*value))
        output[name]={'p_raw':value,'p_holm':previous,'reject_0_05':previous<=.05}
    return output

def contrast(left,right,task_order,counts,seed=SEED):
    differences=np.asarray([counts[left][task]-counts[right][task] for task in task_order],dtype=int)
    rng=np.random.default_rng(seed)
    bootstrap=differences[rng.integers(0,len(task_order),(10000,len(task_order)))].mean(axis=1)/3
    low,high=np.quantile(bootstrap,[.025,.975],method='linear')
    return {'left':left,'right':right,'n_tasks':len(task_order),'replicates_per_task_arm':3,
            'left_rate':float(np.mean([counts[left][t]/3 for t in task_order])),
            'right_rate':float(np.mean([counts[right][t]/3 for t in task_order])),
            'delta':float(differences.mean()/3),'task_cluster_bootstrap_95_ci':[float(low),float(high)],
            'p_exact_paired_sign_flip':paired_exact_p(differences.tolist()),
            'task_differences':{t:float(d/3) for t,d in zip(task_order,differences)}}

def analyze(records,classes):
    """只接受完整的新矩阵；缺格、重复或历史来源均拒绝分析。"""
    tasks=sorted(classes)
    if len(tasks)!=56 or len(records)!=2016:raise ValueError('incomplete 56x12x3 matrix')
    seen=set();counts={arm:Counter() for arm in ARMS}
    for row in records:
        if row.get('origin')!='harness-live-confirmatory-v5':raise ValueError('historical/scripted origin rejected')
        key=(row['task'],row['arm'],row['replicate'])
        if key in seen or row['task'] not in classes or row['arm'] not in ARMS or row['replicate'] not in (1,2,3):
            raise ValueError('duplicate or invalid logical cell')
        if type(row['e2e_success']) is not bool:raise ValueError('score must be explicit boolean')
        seen.add(key);counts[row['arm']][row['task']]+=int(row['e2e_success'])
    expected={(task,arm,rep) for task in tasks for arm in ARMS for rep in (1,2,3)}
    if seen!=expected:raise ValueError('matrix coverage mismatch')
    primary=contrast('B3','B2b',tasks,counts)
    ablations={arm:contrast('B3',arm,tasks,counts) for arm in ARMS if arm.startswith('A')}
    adjusted=holm({arm:row['p_exact_paired_sign_flip'] for arm,row in ablations.items()})
    for arm,row in ablations.items():row['holm']=adjusted[arm]
    length=contrast('A2','sham',tasks,counts)
    strata={}
    for category in sorted(set(classes.values())):
        subset=[task for task in tasks if classes[task]==category]
        strata[category]={'n_tasks':len(subset),'rates':{arm:float(np.mean([counts[arm][t]/3 for t in subset])) for arm in ARMS}}
    return {'schema':'e5-confirmatory-task-paired-analysis-v5','logical_cells':2016,'task_count':56,
            'unit':'task; three repetitions first averaged within task and arm',
            'primary':primary,'ablation_holm_family':ablations,'length_control_A2_minus_sham':length,
            'descriptive_rates':{arm:float(np.mean([counts[arm][t]/3 for t in tasks])) for arm in ARMS},
            'by_class':strata,'human_review':'pending post-run',
            'inference_assumptions':['paired-arm task aggregates are exchangeable under the sharp null',
              'task bootstrap describes resampling uncertainty on this corpus; no general population claim'],
            'sources':['https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html',
                       'https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html']}

def mixed_effects_sensitivity(records):
    """预设敏感性：Bayesian logistic 模型，随机任务截距；不替代主估计量。"""
    import pandas as pd
    import statsmodels
    from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM
    data=pd.DataFrame({'success':int(r['e2e_success']),'arm':r['arm'],'task':r['task']} for r in records)
    np.random.seed(SEED)
    model=BinomialBayesMixedGLM.from_formula("success ~ C(arm, Treatment(reference='B2b'))",
                                            {'task':'0 + C(task)'},data,vcp_p=.5,fe_p=2)
    fit=model.fit_vb(minim_opts={'maxiter':2000})
    return {'schema':'e5-preregistered-glmm-sensitivity-v5','method':'BinomialBayesMixedGLM variational Bayes',
            'statsmodels_version':statsmodels.__version__,'n_records':len(records),'task_random_intercept':True,
            'reference_arm':'B2b','prior_fe_sd':2,'prior_log_random_sd':.5,
            'optimizer_success':bool(fit.optim_retvals.get('success',False)),
            'optimizer_message':str(fit.optim_retvals.get('message','')),
            'fixed_effect_log_odds':{name:{'posterior_mean':float(mean),'posterior_sd':float(sd),
              'approx_95_posterior_interval':[float(mean-1.96*sd),float(mean+1.96*sd)]}
              for name,mean,sd in zip(model.exog_names,fit.fe_mean,fit.fe_sd)},
            'random_intercept_log_sd_posterior_mean':float(fit.vcp_mean[0]),
            'scope':'model-dependent sensitivity only; mean-field posterior intervals, not primary task-rate differences or Holm inference',
            'source':'https://www.statsmodels.org/v0.14.6/generated/statsmodels.genmod.bayes_mixed_glm.BinomialBayesMixedGLM.html'}

@lru_cache(maxsize=20000)
def _power_distribution(n1,n2,n3):
    """仿真加速用浮点概率；正式推断上方使用整数精确计数。"""
    distribution=np.array([1.0])
    for n,weight in ((n1,1),(n2,2),(n3,3)):
        factor=np.zeros(2*n*weight+1)
        factor[::2*weight]=[math.comb(n,k)/(2**n) for k in range(n+1)]
        distribution=np.convolve(distribution,factor)
    offset=n1+2*n2+3*n3
    tail=np.array([distribution[np.abs(np.arange(len(distribution))-offset)>=threshold].sum()
                   for threshold in range(offset+1)])
    return tail

def power_simulation(nsim=1000):
    """固定预算的假设情景，不估计真实任务难度，也不调整样本量。"""
    rng=np.random.default_rng(SEED)
    results=[]
    for baseline in (.5,.75):
        for icc in (0,.25,.5):
            correlations=(0,) if icc==0 else (0,.5,1)
            for between in correlations:
                if icc:
                    scale=1/icc-1
                    first=rng.beta(baseline*scale,(1-baseline)*scale,(nsim,56))
                    independent=rng.beta(baseline*scale,(1-baseline)*scale,(nsim,56))
                    shared=rng.random((nsim,56))<between
                    second=np.where(shared,first,independent)
                else:first=np.full((nsim,56),baseline);second=first.copy()
                # Mean shift is calibrated before drawing any binomial outcomes.
                reference=np.clip(second,1e-12,1-1e-12)
                logits=np.log(reference/(1-reference))
                for delta in ((0,.05,.10,.15,.20,.25,.30) if baseline==.5 else (0,.05,.10,.15,.20)):
                    if delta:
                        low,high=0.0,30.0
                        for _ in range(30):
                            mid=(low+high)/2
                            if np.mean(1/(1+np.exp(-(logits+mid))))<baseline+delta:low=mid
                            else:high=mid
                        treated=1/(1+np.exp(-(logits+(low+high)/2)))
                    else:treated=second
                    diffs=rng.binomial(3,treated)-rng.binomial(3,first)
                    absdiff=np.abs(diffs)
                    multiplicities=np.stack([(absdiff==w).sum(axis=1) for w in (1,2,3)],axis=1)
                    observed=np.abs(diffs.sum(axis=1))
                    pvalues=np.array([_power_distribution(*map(int,counts))[int(stat)] for counts,stat in zip(multiplicities,observed)])
                    results.append({'baseline_probability':baseline,'within_arm_task_icc':icc,
                        'between_arm_task_propensity_correlation':between if icc else None,
                        'target_delta':delta,'realized_probability_delta':float(np.mean(treated-first)),
                        'primary_power_alpha_0_05':float(np.mean(pvalues<=.05)),
                        'ablation_worst_holm_power_alpha_0_05_over_6':float(np.mean(pvalues<=.05/6))})
    groups={}
    for row in results:
        key=(row['baseline_probability'],row['within_arm_task_icc'],row['between_arm_task_propensity_correlation'])
        groups.setdefault(key,[]).append(row)
    mde=[]
    for key,rows in groups.items():
        reached=[r['target_delta'] for r in rows if r['target_delta']>0 and r['primary_power_alpha_0_05']>=.8]
        mde.append({'baseline':key[0],'icc':key[1],'between_arm_correlation':key[2],
                    'first_grid_delta_at_80pct_power':min(reached) if reached else None,
                    'max_evaluated_delta':max(r['target_delta'] for r in rows)})
    return {'schema':'e5-fixed-budget-power-simulation-v5','logical_e5_units':0,'seed':SEED,
            'n_tasks':56,'replicates':3,'nsim':nsim,'max_monte_carlo_standard_error':.5/math.sqrt(nsim),
            'assumption':'beta task propensities; common-versus-independent mixture controls between-arm correlation; calibrated logit treatment shift; conditional independent Bernoulli repeats',
            'scope':'hypothetical design sensitivity, not actual power or task difficulty; no expansion permitted',
            'results':results,'mde_grid':mde}

if __name__=='__main__':
    output=Path(__file__).parent/'power-simulation-v5.json'
    if output.exists():raise SystemExit('refuse overwrite of preregistration simulation')
    output.write_text(json.dumps(power_simulation(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(str(output))
