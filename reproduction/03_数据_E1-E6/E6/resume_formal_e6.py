"""恢复本次外部中断的正式采集；不重采已结束失败，不改冻结采集器。"""
import argparse
import hashlib
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from common_e6 import HERE, config, fp, now, read, write
from model_e6 import ModelAPI
from run_e6_formal import load_tasks, run_once, run_lane, verify_frozen
from prepare_e6 import canary
from trace_e6 import validate
from snapshot_diagnostics_e6 import capture
from transport_e6 import freeze_bank
from report_e6 import generate

def preserve_interruption(path, parameters):
    """只写结果侧记；原始未闭合trace一字不改，结束时间/全墙钟未知。"""
    target = path.with_name(path.stem+'-result.json')
    if target.exists():
        return
    events = [json.loads(s) for s in path.read_text().splitlines()]
    start = events[0]
    calls = [e for e in events if e['type']=='tool_call']
    paired = {e['parent_seq']:e['payload'] for e in events if e['type']=='tool_result'}
    entries = [(c,paired[c['seq']]) for c in calls if c['seq'] in paired]
    responses = [e['payload'] for e in events if e['type']=='model_response']
    result = {'task_id':start['task_id'],'lane':start['payload']['lane'],
              'repeat':start['payload']['repeat'],'trace':path.name,
              'started_at':start['ts_utc'],'ended_at':None,'interruption_detected_at':now(),
              'completed':False,'outcome':'fail','failure_category':'interrupted_execution',
              'error':'进程已退出且trace未闭合；确切退出时刻/尚未返回的模型usage未知',
              'wall_s':None,'wall_s_observed_lower_bound':events[-1]['ts_mono'],
              'rate_limit_wait_s':sum(p.get('rate_limit_wait_s',0) for _,p in entries),
              'tool_calls':[{'tool':c['payload']['tool'],'args':c['payload']['args']} for c,_ in entries],
              'envelopes':[p['envelope'] for _,p in entries],
              'usage_raw':[r.get('usage') for r in responses],
              'returned_models':[r['returned_model'] for r in responses if r.get('returned_model')],
              'cost':{'http_requests':sum(p['observed_session_requests'] for _,p in entries),
                      'elapsed_s':sum(p['cost']['elapsed_s'] for _,p in entries),
                      'rows_returned':sum(len(p['envelope']['data'].get('rows',[])) for _,p in entries),
                      'observation':'known_completed_tool_results_only'},
              'snapshot_misses':[m for _,p in entries for m in p.get('snapshot_misses',[])],
              'validation_errors':validate(events,parameters),'events_fp':fp(events),
              'original_trace_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
              'interruption_recovery_requires_one_new_context':True}
    write(target,result)
    print(json.dumps({'stage':'interruption_preserved','trace':str(path),'at':now()}),flush=True)

def resume_r1(batch, api):
    """同上海日恢复缺失槽位；仅外部中断允许一次新上下文。"""
    manifest = verify_frozen(batch,api)
    tasks = load_tasks()
    originals = sorted((batch/'lanes/R1').glob('*/repeat-*/attempt-*.jsonl'))
    first = json.loads(originals[0].read_text().splitlines()[0])
    original_before = first['payload']['manifest']['actual_online_canary_before']
    original_date = datetime.fromisoformat(first['ts_utc']).astimezone(__import__('zoneinfo').ZoneInfo('Asia/Shanghai')).date()
    ident = 'resume-'+str(time.time_ns())
    write(batch/'resumption-audits'/f'{ident}.json',{'at':now(),'reason':'原进程不在运行，79槽位结束＋1未闭合trace；保存中断，接续剩余，不重试已结束格式/工具失败。',
          'orchestrator_fp':fp(Path(__file__).read_text()),'frozen_collector_unchanged':True,
          'original_online_date':original_date.isoformat(),'original_before':original_before})
    for path in originals:
        preserve_interruption(path,api.parameters())
    before = canary(batch/'canary/R1'/f'{ident}-before')
    segment_manifest = {**manifest,'actual_online_canary_before':before,'resumption_audit':ident}
    print(json.dumps({'stage':'R1_resumed','before':before,'at':now()}),flush=True)
    counts = {}
    for task_id,task in sorted(tasks.items()):
        for repeat in range(1,6):
            directory = batch/'lanes/R1'/task_id/f'repeat-{repeat}'
            results = [read(p) for p in directory.glob('attempt-*-result.json')]
            if (directory/'success.json').exists() or any(r.get('failure_category')!='interrupted_execution' for r in results):
                continue
            if datetime.fromisoformat(now()).date()!=original_date:
                raise RuntimeError('恢复跨上海日界；保留中断，不冒充同日R1')
            status = run_once(batch,'R1',task_id,repeat,task,api,segment_manifest)
            counts[status] = counts.get(status,0)+1
            print(json.dumps({'at':now(),'lane':'R1','task':task_id,'repeat':repeat,'status':status,'resumed':True}),flush=True)
    after = canary(batch/'canary/R1'/f'{ident}-after')
    confirm = canary(batch/'canary/R1'/f'{ident}-confirm') if original_before['fingerprint']!=after['fingerprint'] else None
    write(batch/'canary/R1'/f'{ident}-gate.json',{'before':original_before,'after':after,'resumed_before':before,
          'rerun':confirm,'drift_state':'STABLE' if original_before['fingerprint']==after['fingerprint'] else 'DRIFTED',
          'all_probes_valid':original_before['all_valid'] and before['all_valid'] and after['all_valid']})
    results = [read(p) for p in (batch/'lanes/R1').glob('*/repeat-*/attempt-*-result.json')]
    slots = len({(r['task_id'],r['repeat']) for r in results})
    write(batch/'sessions'/f'R1-{ident}.json',{'started_at':first['ts_utc'],'resumed_at':read(batch/'resumption-audits'/f'{ident}.json')['at'],
          'ended_at':now(),'counts_in_resumed_segment':counts,'lane':'R1','selected':sorted(tasks),'terminated_slots':slots,
          'actual_attempts':len(results),'interruption_disclosed':True,'same_Asia_Shanghai_date':datetime.fromisoformat(now()).date()==original_date})
    if slots!=160:
        raise RuntimeError('正式R1槽位未全结束')
    finish = datetime.fromisoformat(now())
    if not (batch/'R2-CONDITIONS.json').exists():
        write(batch/'R2-CONDITIONS.json',{'r1_completed_at':finish.isoformat(),'due_date_Asia_Shanghai':(finish.date()+timedelta(days=7)).isoformat(),
              'timezone':'Asia/Shanghai','repeat':5,'tasks':32,'automation':False,
              'requirements':['复查实际模型/权限/冻结参数；weights opaque','代码/材料/原32题/schema指纹一致','前后五星表canary+count；漂移移交E7','本R1含外部中断及一次恢复，比较须披露全部尝试'],
              'command':f'temp/e3-e6/venv/bin/python temp/e6-formal/run_e6_formal.py --batch {batch.name} --lane R2'})

def main(batch):
    api = ModelAPI(config())
    resume_r1(batch,api)
    diagnostic = capture(batch)
    pilot = HERE/'batches'/read(batch/'pilot-source.json')['batch']
    paths = sorted((pilot/'lanes/pilot').glob('*/repeat-*/attempt-*.jsonl'))+sorted((batch/'lanes/R1').glob('*/repeat-*/attempt-*.jsonl'))+[diagnostic]
    freeze_bank(paths,batch/'snapshot_manifest.json')
    snapshot = read(batch/'snapshot_manifest.json')
    write(batch/'R3-frozen-manifest.json',{**read(batch/'run_manifest.json'),'snapshot':{'id':batch.name+'-actual-request-bank',
          'fingerprint':snapshot['fingerprint'],'entries':len(snapshot['bank']),'source_traces':[str(p) for p in paths],'freeze_at':now()}})
    print(json.dumps({'stage':'R3_start','batch':batch.name,'at':now()}),flush=True)
    run_lane(batch,'R3')
    out = generate(batch)
    write(batch/'COLLECTION-COMPLETE.json',{'at':now(),'report':str(out),'R2':'D+7_manual_not_collected',
          'collection_complete':True,'record_validity_and_protocol_pass':'see_audits_and_blockers','resumption_disclosed':True})
    print(json.dumps({'stage':'complete','batch':batch.name,'report':str(out),'at':now()}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--batch',required=True)
    main(HERE/'batches'/parser.parse_args().batch)
