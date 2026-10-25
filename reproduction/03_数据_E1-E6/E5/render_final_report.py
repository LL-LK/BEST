"""只在独立评分与完整封存存在后生成报告、待人工复核清单及公开复现包。"""
from pathlib import Path
from collections import Counter
import csv,hashlib,json,shutil,zipfile

HERE=Path(__file__).parent
ROOT=Path(r'<WORK_ROOT>')
RESULT=ROOT/'evidence/confirmatory-v51-results'
PUBLIC=ROOT/'public/confirmatory-v51'
PRIVATE=ROOT/'private/confirmatory-v51'
ARMS=['B0','B1','B2a','B2b','B3','A1','A2','A3','A4','A5','A6','sham']
def load(path):return json.loads(path.read_text('utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    sealed=ROOT/'evidence/confirmatory-v51-sealed'
    marker=load(sealed/'SEALED-COMPLETE.json');assert marker['logical_e5_units']==2016 and marker['verification']['ok']
    scores=load(RESULT/'scores.json');a=load(RESULT/'analysis.json');receipt=load(RESULT/'scorer-receipt.json')
    assert len(scores)==2016 and receipt['identity'].lower().endswith('\\e5scorerv4') and receipt['sealed_input_hash_verified']
    report_dir=HERE.parent/'E5_正式结果_2026-10-12';report_dir.mkdir(exist_ok=False)
    for name in ('scores.json','scores.csv','analysis.json','glmm-sensitivity.json','scorer-receipt.json'):
        shutil.copy2(RESULT/name,report_dir/name)
    failures=Counter(k for r in scores for k,v in r['checks'].items() if not v)
    primary=a['primary'];low,high=primary['task_cluster_bootstrap_95_ci']
    lines=['# E5 正式运行结果','',
      '已完成并封存56题×12臂×3重复，共2016个真实Harness单元。以下是预注册机械代理评分；人工审核仍待完成。',
      '',f"主比较 B3−B2b：差值 **{primary['delta']*100:+.2f}个百分点**，95%任务bootstrap CI [{low*100:+.2f}, {high*100:+.2f}]，精确配对符号翻转 p={primary['p_exact_paired_sign_flip']:.6g}。",
      '', '不把未通过显著性检验的原始率差写成已证实提升；本语料任务bootstrap不表示所有科研任务的总体效果。',
      '', '| 实验臂 | 规则判定通过格 / 168 | 规则通过率 |','|---|---:|---:|']
    for arm in ARMS:
        n=sum(r['e2e_success'] for r in scores if r['arm']==arm)
        lines.append(f'| {arm} | {n}/168 | {a["descriptive_rates"][arm]*100:.2f}% |')
    lines += ['', '| 比较 | 差值（百分点） | 95%任务CI | p | Holm p |','|---|---:|---|---:|---:|']
    for arm in ['A1','A2','A3','A4','A5','A6']:
        c=a['ablation_holm_family'][arm];ci=c['task_cluster_bootstrap_95_ci']
        lines.append(f'| B3−{arm} | {c["delta"]*100:+.2f} | [{ci[0]*100:+.2f}, {ci[1]*100:+.2f}] | {c["p_exact_paired_sign_flip"]:.6g} | {c["holm"]["p_holm"]:.6g} |')
    c=a['length_control_A2_minus_sham'];ci=c['task_cluster_bootstrap_95_ci']
    lines += [f'| A2−sham（独立比较） | {c["delta"]*100:+.2f} | [{ci[0]*100:+.2f}, {ci[1]*100:+.2f}] | {c["p_exact_paired_sign_flip"]:.6g} | 不属于六项家族 |',
      '', '运行统一为Harness CLI0.2.0-rc.2、实际Claude Science受限预设与opencode-go/deepseek-v4.1-flash。实际LLM决策使用匹配的公开冻结响应，生产ToolBox/BestClient不改写；这不是每格重新向NADC联网，也不是脚本答案回填。',
      '', '三次重复先按题和臂取均值；主检验以56题配对。GLMM只是预设敏感性，详见glmm-sensitivity.json。',
      '', '需要保留的解释限制：A2仅去除额外指导，公共schema仍含部分语义；sham只匹配字符数，未提供真实V4.1 tokenizer，不能称token精确长度控制；A6同时去除信封指导并改变布局，不能归因为纯布局效果。D07的每页2行要求包含首次查询，不豁免原子工具的1000行bootstrap。机械规则可能有假阳性和假阴性，规则通过率不是已经由人工确认的科研任务成功率；需后续人工复核，没有伪造双盲/仲裁/一致性记录。语料中部分任务有相近意图，当前CI按任务聚类，未额外按语义家族聚类。',
      '', '运行前ASAR哈希读取失败受理数为0，v5.1重新冻结；运行中对作者收集器作逐格ZIP打包的性能修复；模型完成2016格后，收集器在最后一轮因结束标记与扫描时序错位停在2015格，随后验证既有2015份包并收取最后一份已完成来源证据。没有新增、重跑或替换实验单元；旧账本、原始停止标记及两份操作说明保留，题库/臂/模型/评分/统计未修改。',
      '', '封存后的独立评分启动器遇到旧PowerShell命令/子进程回执兼容问题，改用等价.NET哈希与显式进程退出回执。冻结评分器未变，失败入口没有生成评分结果。评分器无条件枚举worker回执目录，而573个单元无该目录，其中564个没有模型工具调用、9个有调用事件但无worker回执。存储兼容层在作者核验原始DONE及无回执文件、真实导出逐字节一致后，将这些目录枚举为空；实际模型调用、错误、引用检查仍由原评分器逐项评估。原生tool/call的arguments为JSON字符串，兼容层只解码为评分器预期对象，不改字段或值。未改sealed文件、任务条件或评分规则。全部操作记录附于复现包。',
      '', f'冻结协议SHA256：`{marker["protocol_sha256"]}`。来源compressed session逐格保存SHA256，公开导出不含隐藏推理。独立评分身份为`{receipt["identity"]}`。',
      '', '提供者usage逐格保留；temperature/top_p/revision/fingerprint和真实账单cost未提供时为null，不冒称0费用或确定温度。',
      '', '高频未通过条件（仅描述，不改变评分）：']
    lines += [f'- {name}: {count}' for name,count in failures.most_common(15)]
    lines += ['', '人工复核请填写human-review-pending.csv；私有gold仍留在本机受保护private/confirmatory-v51，未加入公开复现包；评分代码、兼容层和操作记录已包含在包内。公开包提供代码、数据和会话证据；重新运行需匹配Harness安装包与合法模型凭据，独立复核评分还需作者授权的gold。']
    (report_dir/'E5_结果报告.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    with (report_dir/'human-review-pending.csv').open('w',encoding='utf-8-sig',newline='') as f:
        keys=['task','arm','replicate','cell_id','session_id','mechanical_success','failed_checks','human_verdict','human_comment']
        writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader()
        writer.writerows({**{k:r[k] for k in keys[:5]},'mechanical_success':r['e2e_success'],
                         'failed_checks':';'.join(k for k,v in r['checks'].items() if not v),'human_verdict':'','human_comment':''} for r in scores)
    # Scientific standalone figure; actual task contrasts and intervals only.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,(left,right)=plt.subplots(1,2,figsize=(12,5),layout='constrained')
    left.bar(ARMS,[a['descriptive_rates'][arm]*100 for arm in ARMS],color=['#365f8d' if arm=='B3' else '#9baebd' for arm in ARMS])
    left.set_ylim(0,100);left.set_ylabel('Preregistered rule pass rate (%)');left.tick_params(axis='x',rotation=45)
    left.set_title('56 tasks, 3 independent repetitions per arm')
    contrasts=[primary]+[a['ablation_holm_family'][arm] for arm in ['A1','A2','A3','A4','A5','A6']]+[a['length_control_A2_minus_sham']]
    for i,c in enumerate(contrasts):
        lo,hi=c['task_cluster_bootstrap_95_ci'];mean=c['delta']
        right.plot([lo*100,hi*100],[i,i],color='#365f8d');right.plot(mean*100,i,'o',color='#365f8d')
    right.set_yticks(range(8),[c['left']+' - '+c['right'] for c in contrasts]);right.invert_yaxis();right.axvline(0,color='gray',lw=.8)
    right.set_xlabel('Task mean difference (percentage points)');right.set_title('95% paired task bootstrap intervals')
    fig.savefig(report_dir/'E5_results.png',dpi=200);fig.savefig(report_dir/'E5_results.pdf');plt.close(fig)
    package=report_dir/'E5_public_reproduction.zip'
    with zipfile.ZipFile(package,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in report_dir.iterdir():
            if p.is_file() and p!=package:z.write(p,'results/'+p.name)
        for name in ('tasks.json','arms.json','schedule.json','protocol.md','freeze-public.json','plan-template.json','plan.json'):
            z.write(PUBLIC/name,'preregistration/'+name)
        for p in (ROOT/'public/e5-confirmatory-host').glob('*'):
            if p.is_file():z.write(p,'host/'+p.name)
        for prefix in ('runtime','data'):
            for p in (ROOT/'public/e5-candidate-02'/prefix).rglob('*'):
                if p.is_file():z.write(p,prefix+'/'+p.relative_to(ROOT/'public/e5-candidate-02'/prefix).as_posix())
        for name in ('domain_gateway.py','domain_worker.py','frozen_backend.py'):
            z.write(HERE/name,'worker/'+name)
        for name in ('confirmatory_stats.py','scorer.py'):
            z.write(PRIVATE/name,'scoring/'+name)
        z.write(ROOT/'evidence/observer-amendment-v51-packed.json','operations/observer-amendment.json')
        z.write(ROOT/'evidence/observer-recovery-v51-final-drain.json','operations/observer-final-drain-recovery.json')
        z.write(ROOT/'evidence/scorer-launcher-operational-amendment-v51.json','operations/scorer-launcher-amendment.json')
        z.write(ROOT/'evidence/scorer-empty-calls-storage-amendment.json','operations/scorer-empty-calls-storage-amendment.json')
        z.write(ROOT/'evidence/scorer-empty-calls-storage-amendment-v2.json','operations/scorer-empty-calls-storage-amendment-v2.json')
        z.write(ROOT/'evidence/author-qualified-empty-calls.json','operations/author-qualified-empty-calls.json')
        z.write(ROOT/'evidence/scorer-empty-call-storage-adapter-receipt.json','operations/scorer-empty-calls-storage-receipt.json')
        z.write(ROOT/'public/scorer_empty_calls_storage_adapter.py','scoring/scorer_empty_calls_storage_adapter.py')
        z.write(ROOT/'evidence/scorer-native-event-normalization-amendment.json','operations/scorer-native-event-normalization-amendment.json')
        z.write(ROOT/'evidence/scorer-native-event-normalization-receipt.json','operations/scorer-native-event-normalization-receipt.json')
        for p in (sealed/'cells').rglob('*'):
            if p.is_file():z.write(p,'evidence/cells/'+p.relative_to(sealed/'cells').as_posix())
        for acquisition in ('public-recapture-01','public-followup-capture-01'):
            for p in (HERE/acquisition).rglob('*'):
                if p.is_file():z.write(p,'acquisition/'+acquisition+'/'+p.relative_to(HERE/acquisition).as_posix())
        z.write(sealed/'artifact-hashes.json','evidence/artifact-hashes.json')
        z.write(sealed/'SEALED-COMPLETE.json','evidence/SEALED-COMPLETE.json')
    hashes={p.name:sha(p) for p in report_dir.iterdir() if p.is_file()}
    (report_dir/'SHA256.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
    (HERE/'FINAL-DELIVERY.json').write_text(json.dumps({'logical_e5_units':2016,'report_directory':str(report_dir),'human_review':'pending','hashes':hashes},indent=2),encoding='utf-8')
    print(json.dumps({'report_directory':str(report_dir),'logical_e5_units':2016,'human_review':'pending'}))

if __name__=='__main__':main()
