"""独立 R3 充值后补测：固定全量槽位、保留失败、不改原批次。"""
import argparse
import hashlib
import json
import os
import shutil
import time
from collections import Counter
from pathlib import Path

from common_e6 import HERE, config, fp, now, read, write
from model_e6 import ModelAPI
from run_e6_formal import load_tasks, run_once, verify_frozen
from audit_delivery_e6 import audit, check_snapshot_sources
from report_e6 import collect, model_api_failures
from metrics_e6 import score_lane, score_task
from efficiency_usability_e6 import efficiency, usability
from wire_semantics_audit_e6 import wire_failures

ORIGINAL = 'E6-20261007-1791350994158084000'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(batch):
    return {str(p.relative_to(batch)): digest(p) for p in sorted(batch.rglob('*')) if p.is_file()}


def quota_or_auth_failure(events):
    """永久认证或余额错误立即停止整个批次，避免重复消耗。"""
    return next((e['payload']['http_status'] for e in events
                 if e['type'] == 'model_response' and
                 e['payload'].get('http_status') in (401, 402, 403)), None)


def terminal_slots(batch):
    """所有已终止槽位都跳过，包括科学、格式、工具失败。"""
    return {(read(p)['task_id'], read(p)['repeat']) for p in
            (batch/'lanes/R3').glob('*/repeat-*/attempt-*-result.json')}


def prepare():
    api = ModelAPI(config())
    source = HERE/'batches'/ORIGINAL
    verify_frozen(source, api)
    probes = sorted((HERE/'preflight').glob('probe-*.json'))
    probe = read(probes[-1]) if probes else {}
    if not probe.get('passed') or probe.get('request_parameters') != api.parameters():
        raise ValueError('新配置需要通过匹配参数的真实工具闭环探针')
    snapshot = read(source/'snapshot_manifest.json')
    errors, pointers = check_snapshot_sources(snapshot)
    if errors:
        raise ValueError('原快照来源核验失败；不发起正式采集')
    batch = HERE/'batches'/('E6-R3-supplement-'+now()[:10].replace('-', '')+'-'+str(time.time_ns()))
    batch.mkdir(parents=True, mode=0o700)
    shutil.copytree(source/'frozen', batch/'frozen')
    shutil.copyfile(source/'snapshot_manifest.json', batch/'snapshot_manifest.json')
    manifest = read(source/'run_manifest.json')
    manifest['execution'] = {**manifest['execution'], 'prepared_at': now(),
                             'lanes': ['R3'], 'R2': 'not_applicable_to_R3_only_supplement',
                             'original_batch': ORIGINAL, 'supplementary_cohort': True}
    write(batch/'run_manifest.json', manifest)
    pilot_source = read(source/'pilot-source.json')
    write(batch/'pilot-source.json', {**pilot_source, 'purpose': '仅沿用原校准参考，不计作本批次新采集'})
    write(batch/'SUPPLEMENT-PROTOCOL.json', {
        'frozen_at': now(), 'original_batch': ORIGINAL, 'lane': 'R3',
        'tasks': 32, 'repeat': 5, 'planned_slots': 160,
        'selection': 'all_original_tasks_not_only_previously_failed',
        'maximum_execution_attempts_per_slot': 1,
        'model_http_transient_retry': 'unchanged_original_maximum_3_requests',
        'resume_policy': 'skip_all_terminated_slots_including_failures; unclosed_trace_blocks_resume',
        'quota_auth_stop': [401, 402, 403],
        'snapshot_source_batch': ORIGINAL, 'snapshot_fp': snapshot['fingerprint'],
        'snapshot_entries': len(snapshot['bank']), 'source_pointers_checked': pointers,
        'model_and_input_unchanged': True, 'credential_rotated': True,
        'probe': str(probes[-1]), 'judge_api_used': False,
        'cohort_combination': 'separate_report_no_pooling_with_original_R3',
        'R1': 'original_160_slots_already_terminated; failures_retained_not_retried',
        'R2': read(source/'R2-CONDITIONS.json'), 'U7': 'missing_independent_raters',
        'provider_weights_snapshot': 'opaque',
        'posthoc_supplement': True, 'protocol_deviations': manifest['protocol_deviations'],
        'runner_fp': fp(Path(__file__).read_text())})
    write(batch/'ORIGINAL-INVENTORY.json', {'source': str(source), 'files': inventory(source)})
    write(HERE/'supplement-current.json', {'batch': batch.name}, exclusive=False)
    verify_frozen(batch, api)
    print(json.dumps({'stage': 'prepared', 'batch': batch.name, 'planned_slots': 160,
                      'snapshot_entries': len(snapshot['bank']), 'at': now()}), flush=True)
    return batch


def report(batch):
    """只报告本批次 R3；旧 R1/R3 和未来 R2 明确分开。"""
    config()
    out = batch/'reports'/str(time.time_ns())
    out.mkdir(parents=True)
    grouped, runs, traces, collection = collect(batch, 'R3')
    score = score_lane(grouped, 'R3')
    task_ids = sorted(load_tasks())
    score['missing_valid_tasks'] = [t for t in task_ids if not grouped.get(t)]
    for t in task_ids:
        score['per_task'].setdefault(t, score_task([], 'R3'))
    paths = sorted((batch/'lanes/R3').glob('*/repeat-*/attempt-*-result.json'))
    all_runs = [read(p) for p in paths]
    all_traces = [[json.loads(s) for s in (p.parent/r['trace']).read_text().splitlines()]
                  for p, r in zip(paths, all_runs)]
    for r, ev in zip(all_runs, all_traces):
        r['native_tool_call_count'] = sum(e['type'] == 'tool_call' for e in ev)
        r['wire_semantic_failures'] = wire_failures(ev)
    identity = read(batch/'run_manifest.json')['best_data']['fingerprint_before']
    ef, u = efficiency(all_runs, all_traces), usability(all_runs, identity)
    ef['valid_records_only'] = efficiency(runs, traces)
    u['valid_records_only'] = usability(runs, identity)
    ef['denominator_policy'] = u['denominator_policy'] = 'all_actual_attempts_including_failures'
    declared = score_lane({t: [{k:v for k,v in r.items() if k != 'reviewed_card'} for r in rs]
                           for t,rs in grouped.items()}, 'R3')
    provenance = read(batch/'ORIGINAL-INVENTORY.json')
    old_preserved = inventory(Path(provenance['source'])) == provenance['files']
    audit_path = audit(batch)/'audit.json'
    delivery_audit = read(audit_path)
    errors = [r for r in delivery_audit['records'] if r.get('validation_errors') or r.get('frozen_input_errors')]
    safe = not errors and not delivery_audit['credential_scan']['hits'] and not delivery_audit['snapshot']['errors']
    completed = collection['terminated_slots'] == 160
    payload = {'generated_at': now(), 'batch': batch.name, 'scope': 'independent_R3_only_posthoc_supplement',
               'original_batch': ORIGINAL, 'planned_slots': 160, 'collection_complete': completed,
               'all_records_valid': completed and score['records'] == 160,
               'consistency': score, 'collection_audit': collection, 'efficiency': ef, 'usability': u,
               'generation_api_failures': model_api_failures(all_runs, all_traces),
               'returned_models': dict(Counter(e['payload'].get('returned_model') for ev in all_traces
                                              for e in ev if e['type']=='model_response')),
               'original_files_preserved': old_preserved, 'integrity_audit_passed': safe,
               'integrity_audit': str(audit_path), 'judge_api_used': False,
               'independent_raters': 0, 'U7': None, 'formal_protocol_pass': False,
               'composite_score': None, 'R2': read(batch/'SUPPLEMENT-PROTOCOL.json')['R2'],
               'statistics': '10000 task-cluster bootstrap; valid records conditional; failure denominator all attempts',
               'limitations': read(batch/'run_manifest.json')['protocol_deviations']}
    write(out/'FINAL-RESULTS.json', payload)
    write(out/'R3-consistency.json', score)
    write(out/'R3-declared-card-consistency.json', declared)
    write(out/'R3-efficiency.json', ef)
    write(out/'R3-usability.json', u)
    write(out/'R3-semantic-cards.json', [{'task_id':r['task_id'],'repeat':r['repeat'],
          'answer':r['answer_text'],'declared_card':r['card'],'semantic_card':r['reviewed_card'],
          'diagnostics':r['review_diagnostics']} for r in runs])
    write(out/'scoring-manifest.json', {'judge_api_used':False,'independent_blind_review':False,
          'method':'current_assistant_and_local_core_semantic_rules',
          'code':{p.name:fp(p.read_text()) for p in HERE.glob('*.py')}})
    lines = ['# E6 R3 充值后独立补测结果', '', f'批次：`{batch.name}`；生成：{now()}。', '',
             '本批次采用原 32 题，每题 5 次独立上下文，使用原冻结输入、模型参数和实际 BEST 快照。'
             '属于事后补测，单独报告，不与 10 月 7 日原 R3 合并。原 69 次余额不足及所有其他失败均保留。', '',
             f"已终止 {collection['terminated_slots']}/160 槽位；有效 {score['records']}/160；"
             f"失败 {collection['failure_attempts']}；完整 5 次有效题 {score['coverage']['tasks_with_5_valid']}/32。", '',
             '| 指标 | 点估计 | 按题重抽 95% 区间 | 可估计题数 |', '|---|---:|---|---:|']
    for name in ('TSC','PAC_call','RDC','FCC'):
        row = score['aggregate'][name]
        lines.append(f"| {name} | {row['point']} | {row.get('bootstrap_95')} | {row.get('task_units')} |")
    lines += ['', '完整逐题分母、全部尝试效率与可用性、缺失 usage、实际回包模型及失败原因见同目录 JSON。'
              '一致率按有效记录计算；失败成本按全部尝试计算。FCC 是核心语义规则与当前助手复核，不能代表全文科学正确。', '',
              f'原件保留核验：{old_preserved}；输入、快照来源、轨迹及密钥审计通过：{safe}。', '',
              '原 R1 已结束 160 个计划槽位，其格式、工具及科学失败不重试至成功。'
              'D+7 R2 仍须在 **2026-10-14（Asia/Shanghai）** 使用原正式批次运行；本次 R3 补测不改变该日期。', '',
              '**E6 原协议整体通过：否。** U7 独立专家评分尚缺；温度未固定、相对时间题标记错误、'
              '部分场景未触发及原冻结材料错误继续披露。充值只能消除运营阻碍，不能将这些结果改为通过。', '',
              '## 逐题记录', '', '| 题号 | 有效重复 | TSC | PAC_call | RDC | FCC |', '|---|---:|---:|---:|---:|---:|']
    for task,row in sorted(score['per_task'].items()):
        lines.append(f"| {task} | {row['runs']} | " + ' | '.join(str(row[k]['point']) for k in ('TSC','PAC_call','RDC','FCC')) + ' |')
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    write(batch/'LATEST-REPORT.json', {'at':now(),'report':str(out/'REPORT.md'),'results':str(out/'FINAL-RESULTS.json')}, exclusive=False)
    print(json.dumps({'stage':'report','batch':batch.name,'report':str(out/'REPORT.md'),
          'complete':completed,'valid':score['records'],'failures':collection['failure_attempts'],
          'original_preserved':old_preserved,'integrity_passed':safe,'at':now()}),flush=True)
    return out


def run(batch):
    values = config()
    api = ModelAPI(values)
    manifest = verify_frozen(batch, api)
    protocol = read(batch/'SUPPLEMENT-PROTOCOL.json')
    if fp(Path(__file__).read_text()) != protocol['runner_fp']:
        raise ValueError('补测编排漂移，拒绝混批')
    snapshot = read(batch/'snapshot_manifest.json')
    if fp(snapshot['bank']) != snapshot['fingerprint']:
        raise ValueError('快照指纹漂移')
    for trace in (batch/'lanes/R3').glob('*/repeat-*/attempt-*.jsonl'):
        if not trace.with_name(trace.stem+'-result.json').exists():
            raise ValueError('存在未闭合尝试；先记录中断，禁止自动重采')
    manifest = {**manifest, 'eval_data': {**manifest['eval_data'], 'snapshot_status':'frozen',
        'snapshot_id':batch.name+'-actual-request-bank', 'snapshot_manifest_fp':snapshot['fingerprint']}}
    started = now()
    done = terminal_slots(batch)
    counts = Counter()
    stopped = None
    write(batch/'PROGRESS.json', {'at':now(),'pid':os.getpid(),'started_at':started,
          'terminated_slots':len(done),'planned_slots':160,'session_counts':{},
          'status':'running','permanent_api_stop':None}, exclusive=False)
    for task_id, task in sorted(load_tasks().items()):
        for repeat in range(1,6):
            if (task_id,repeat) in done:
                continue
            status = run_once(batch,'R3',task_id,repeat,task,api,manifest,snapshot['bank'])
            counts[status] += 1
            directory = batch/'lanes/R3'/task_id/f'repeat-{repeat}'
            trace = sorted(directory.glob('attempt-*.jsonl'))[-1]
            events = [json.loads(s) for s in trace.read_text().splitlines()]
            stopped = quota_or_auth_failure(events)
            write(batch/'PROGRESS.json', {'at':now(),'pid':os.getpid(),'started_at':started,
                  'terminated_slots':len(done)+sum(counts.values()),'planned_slots':160,
                  'session_counts':dict(counts),'last_task':task_id,'last_repeat':repeat,
                  'permanent_api_stop':stopped}, exclusive=False)
            print(json.dumps({'stage':'collect','at':now(),'task':task_id,'repeat':repeat,
                              'status':status,'terminated_slots':len(done)+sum(counts.values()),
                              'permanent_api_stop':stopped}),flush=True)
            if stopped:
                break
        if stopped:
            break
    write(batch/'sessions'/('R3-supplement-'+str(time.time_ns())+'.json'), {
          'started_at':started,'ended_at':now(),'counts':dict(counts),'stopped_http_status':stopped,
          'completed_slots':len(terminal_slots(batch)),'planned_slots':160,'lane':'R3'})
    report(batch)
    api.session.close()
    write(batch/'RUN-STATUS.json', {'at':now(),'status':'stopped_api' if stopped else 'collection_complete',
          'terminated_slots':len(terminal_slots(batch)),'planned_slots':160,
          'stopped_http_status':stopped}, exclusive=False)
    if stopped:
        raise SystemExit(2)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--batch')
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--report-only',action='store_true')
    args=parser.parse_args()
    batch=HERE/'batches'/args.batch if args.batch else prepare()
    if not batch.resolve().is_relative_to((HERE/'batches').resolve()):
        raise ValueError('批次路径越界')
    if args.report_only:
        report(batch)
    elif not args.prepare_only:
        run(batch)


if __name__=='__main__':
    main()
