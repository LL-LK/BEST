"""在完整采集和新鲜离线审计之后汇总交付；不发任何生成或评分请求。"""
import hashlib
import json
import time
from pathlib import Path
from common_e6 import HERE, read, write, now, fp

def newest(batch, folder, name):
    paths=list((batch/folder).glob('*/'+name))
    if not paths:
        raise RuntimeError('缺少审计：'+folder)
    return max(paths,key=lambda p:int(p.parent.name))

def link(path, label):
    return '['+label+'](<'+str(path.resolve())+'>)'

def number(value):
    return '缺失' if value is None else f'{value:.4f}'

def interval(metric):
    ci=metric.get('bootstrap_95')
    return number(metric['point'])+(' ['+', '.join(number(v) for v in ci)+']' if ci else '')+'；T='+str(metric['task_units'])

def deliver(batch):
    report=Path(read(batch/'latest-report.json')['directory'])
    summary=read(report/'summary.json')
    if not summary['collection_complete_required_lanes']:
        raise RuntimeError('计划采集尚未完成，禁止最终交付')
    delivery_path=newest(batch,'delivery-audits','audit.json')
    coverage_path=newest(batch,'coverage-audits','coverage.json')
    wire_path=newest(batch,'wire-semantics-audits','audit.json')
    audit,coverage,wire=map(read,(delivery_path,coverage_path,wire_path))
    for lane in ('R1','R3'):
        expected=summary['lanes'][lane]['audit']['terminated_attempts']
        if audit['totals'].get(lane+'_attempts')!=expected or coverage['lanes'][lane]['attempts']!=expected:
            raise RuntimeError('最终审计没有覆盖当前全部尝试：'+lane)
    if audit['credential_scan']['hits'] or audit['snapshot']['errors']:
        raise RuntimeError('凭据或快照来源完整性审计未通过')
    if any(r.get('frozen_input_errors') for r in audit['records']):
        raise RuntimeError('冻结输入或回放无网络审计发现错误')
    snapshot=read(batch/'snapshot_manifest.json')
    if audit['snapshot']['source_pointers_checked']!=sum(map(len,snapshot['sources'].values())):
        raise RuntimeError('快照来源指针未全部核验')
    lines=['# E6 本轮最终交付','',f'生成：{now()}；正式批次：`{batch.name}`。','',
           'R0、R1、R3计划采集已完成，原件、失败、成本与审计均归档。**原协议门禁 FAIL；综合分缺失，不宣称E6通过。** R2留待D+7人工执行，本轮没有创建自动任务。','',
           '| 路 | 已结束槽位 | 实际尝试 | 有效记录 | 失败尝试 | 满5有效题数 |',
           '|---|---:|---:|---:|---:|---:|']
    for lane in ('R0','R1','R3'):
        r=summary['lanes'][lane];a=r['audit'];s=r['score']
        lines.append(f"| {lane} | {a['terminated_slots']} | {a['terminated_attempts']} | {s['records']} | {a['failure_attempts']} | {s['coverage']['tasks_with_5_valid']}/32 |")
    api=summary['lanes']['R3']['audit']['model_api_failures']
    lines += ['', f"**R3有{api['insufficient_balance_attempts']}次尝试被供应商Insufficient Balance（HTTP402）终止**：19r2在一次已知usage回包和4元数据工具后失败，后68次在首个生成请求即失败、没有工具或答案。这是运营故障，不是BEST后端或科学能力失败。全部失败保留、不换模型、不补跑；未返回的usage未知。余额拒绝拉低全部尝试的耗时/请求中位数，不能解释为策略提效，后13题没有有效答案。", '', '实际agent轨迹时间：', '']
    for lane in ('R0','R1','R3'):
        lines.append('- '+lane+'：`'+json.dumps(summary['lanes'][lane]['audit']['actual_execution_dates'],ensure_ascii=False)+'`。')
    lines+=['','R0覆盖18个固化工具题（90记录）；R1/R3各32题×5槽位。R1一次外部中断仅该槽位追加一次新上下文，原未闭合轨迹不改，全部普通结束失败不重采。有效记录条件一致率与所有尝试可用性/成本分母分别保存。','',
            '| 路 | TSC | PAC_call | RDC | FCC核心语义 |',
            '|---|---:|---:|---:|---:|']
    for lane in ('R0','R1','R3'):
        a=summary['lanes'][lane]['score']['aggregate']
        lines.append('| '+lane+' | '+' | '.join(interval(a[k]) for k in ('TSC','PAC_call','RDC','FCC'))+' |')
    lines+=['','方括号为按题号成组、10,000次重抽的95%区间；主点估计以可估计有效题为条件。每题真实n和描述性Wilson区间见CSV/JSON：5/5仍为[0.5655,1]，零有效题保持null。160次不是160独立题，退化区间不证明未来必然稳定。无两个系统对照，不做McNemar。','',
            'RDC在线为规范行集/状态Jaccard，回放为L1内容指纹，并保留无数据及data-conditioned口径。FCC是当前助手和本地规则事后抽取核心事实，模型声明卡平行保留；未使用评分API，没有独立盲评。附加说明错误另列审阅，不以核心一致率证明全文科学准确。','',
            '| 路 | 协议请求合计 | 请求P50/P90 | agent单调计时P50/P90秒 | η观察下界 | EF3 | EF6零请求完成 |',
            '|---|---:|---:|---:|---:|---:|---:|']
    for lane in ('R1','R3'):
        e=summary['lanes'][lane]['efficiency'];h=e['http_requests'];w=e['EF2']['agent_monotonic_with_wait']
        lines.append(f"| {lane} | {e['EF1']['actual_session_requests']} | {h['p50']}/{h['p90']} | {w['p50']:.3f}/{w['p90']:.3f} | {number(e['EF1']['eta_ratio_of_sums'])} | {number(e['EF3']['point'])} | {number(e['EF6']['point'])} |")
    lines+=['','效率主分母包含所有实际尝试，失败也计入。η按已观测工具协议下界计算，不是独立任务最优策略；零请求0/0为null。R3上述请求是回放协议次数，真实BEST站点wire请求为0，生成模型API仍真实调用。EF3沿原协议只将重复cone/crossmatch计入分子；重复元数据工具另作诊断，低EF3不能证明没有调用循环。EF4显式重试策略代理及EF5实际分页详见效率JSON。','',
            'agent时间由time.monotonic实测（含等待），UTC跨度和扣除实测限速等待的时间另存；跨时钟差额原因未经确认，不能算作模型推理耗时。中断尝试全时间及尚未返回的usage未知null，已观察下界/已知部分保留。主成本表为R1/R3，pilot、准备预检和canary另存，不能当成整个API账单。价格与货币成本均null。','',
            '| 路 | 已知input token | 已知output token | 缺完整usage的尝试 | 无完整usage的模型请求 | 所有工具同参额外重复 |',
            '|---|---:|---:|---:|---:|---:|']
    for lane in ('R1','R3'):
        e=summary['lanes'][lane]['efficiency'];t=e['EF7']
        lines.append(f"| {lane} | {t['tokens_in_observed_sum']} | {t['tokens_out_observed_sum']} | {t['missing_usage_runs']} | {t['model_requests_without_complete_usage']} | {e['EF3']['all_tools_exact_repeat_count']} |")
    lines+=['','| 路 | U1 | U2 | U3 | U4 | U5步骤比值 | U6 | U7 |','|---|---:|---:|---:|---:|---:|---:|---|']
    for lane in ('R1','R3'):
        u=summary['lanes'][lane]['usability']['summary']
        values=[number(u[k]['point'])+' (n='+str(u[k]['observations'])+')' for k in ('U1','U2','U3','U4','U5','U6')]
        lines.append('| '+lane+' | '+' | '.join(values)+' | 缺失，0评阅人 |')
    lines+=['','U3是缺维/选项存在性，U4是标识/单位/URI/untrusted标注存在性，U6是肯定降级标签证据代理；不代替完整科学真值判定。U5仅对独立可知步骤预算估计，未知/0预算null；未把工具步数与HTTP数混为一谈。','',
            f"原12项反证夹具全部检出：pass={summary['original_counterexample_selftest']['pass']}，metascore={summary['original_counterexample_selftest']['metascore']}。临时设施反例检查最近64通过，日志另附。",'',
            f"冻结快照：{len(snapshot['bank'])}键，{audit['snapshot']['source_pointers_checked']}来源指针全部核验，0来源错误；指纹 `{snapshot['fingerprint']}`。按首次观测选响应；原外部中断未闭合trace排除、原件保留。未知分支使整个尝试无效，不补live响应、不返回伪造空表。有效R3指标存在分支选择偏差。绑定SQLID的s前缀被冻结request_key抹去，完整wire语义保真受限；最终同键两前缀已观测组数={wire['observed_keys_with_both_prefix_styles']}。",'',
            f"全部正式轨迹及失败均审计，冻结prompt/schema/参数检查通过；R3没有live BEST fallback。真实凭据及解码响应/重定向字节扫描0命中。HTTP200软错被成功空表信封掩盖的证据数={wire['soft_error_success_wraps']}，原信封保留并独立影响U1/归因；不能单因归于SQLID前缀。",'',
            '场景覆盖按实际调用核验：原题缺坐标、同日相对时间、原29成功解析而非哨兵失败、27的174行不足默认1000页上限等限制保留。真实协议诊断另含哨兵-1000、指定路径HTTP200 NotFound、page1/page2各5行；两页有重叠，不能称10个唯一源，也不算新agent任务成绩。攻击文本仅出现在用户描述时，不能算真实后端注入已测试。','',
            '冻结材料本身含360倍角度换算错误（应3600）及将官网Download栏25G/1.4T等误解为星数；回答重复上游数字不证明科学正确。事后[官网目录](https://nadc.china-vo.org/data/best/doc/system-en/catalog)核验未进入SUT或快照库；源数、测光口径及其他附加缺陷详见助手审阅。','',
            '协议阻断及偏离：','']
    lines.extend('- '+b for b in summary['blockers'])
    lines+=['','R1前、恢复前、后五表canary精确原始行指纹一致，五表count为174/3/0/0/0；这只证明这些探针稳定，不证明全站不漂移。指纹/有效状态见精确审计；R1中断和跨时钟差额均公开。','',
            f"R2：**{summary['R2']['due_date_Asia_Shanghai']}（Asia/Shanghai）**人工复跑32×5。复查模型权限/实际模型、冻结代码材料任务schema参数、前后五表canary+count；权重opaque及全部尝试披露，发现漂移移交E7。本轮不执行R2、不等待七天、不创建automation。",'',
            '交付入口：','']
    for path,label in [(report/'REPORT.md','完整统计报告'),(report/'summary.json','机器汇总'),(report/'scoring-manifest.json','实际评分代码指纹'),
                       (delivery_path,'全部轨迹及快照来源审计'),(coverage_path,'实际场景覆盖'),(wire_path,'原始软错及SQLID路径审计'),
                       (report/'canary-exact-rows-audit.json','精确canary指纹'),(batch/'run_manifest.json','冻结运行清单'),
                       (batch/'snapshot_manifest.json','快照库及来源'),(batch/'R2-CONDITIONS.json','R2准确日期和命令'),
                       (HERE/'ASSISTANT-REVIEW.md','逐项实际答案审阅'),(HERE/'formal-tests-64-model-balance-failures.log','64项设施反例检查')]:
        lines.append('- '+link(path,label))
    target=HERE/'FINAL-REPORT.md'
    with target.open('x') as f:f.write('\n'.join(lines)+'\n')
    artifacts=[target,report/'summary.json',report/'scoring-manifest.json',delivery_path,coverage_path,wire_path,batch/'snapshot_manifest.json']
    write(batch/'FINAL-DELIVERY.json',{'at':now(),'collection_complete':True,'protocol_gate':'FAIL','composite':None,
          'report':str(target),'scoring_report':str(report),'audits':list(map(str,(delivery_path,coverage_path,wire_path))),
          'artifacts_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts},
          'R2_due':summary['R2']['due_date_Asia_Shanghai'],'no_judge_api':True,'U7_raters':0,'builder_fp':fp(Path(__file__).read_text())})
    print(json.dumps({'final_report':str(target),'complete':True,'protocol_gate':'FAIL'}))
    return target

if __name__=='__main__':
    deliver(HERE/'batches'/read(HERE/'current.json')['batch'])
