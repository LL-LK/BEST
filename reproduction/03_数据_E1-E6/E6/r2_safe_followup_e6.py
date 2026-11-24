"""D+7 手动入口：保留原采集器，永久认证/余额拒绝即停止。"""
import argparse
import json
import os
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from common_e6 import HERE, config, fp, now, read, write
from model_e6 import ModelAPI
from run_e6_formal import load_tasks, run_once, verify_frozen
from prepare_e6 import canary
from report_e6 import exact_canary, generate


def require_due_date(batch, at=None):
    due=read(batch/'R2-CONDITIONS.json')['due_date_Asia_Shanghai']
    actual=(at or now())[:10]
    if actual != due:
        raise ValueError(f'R2 日期不符：仅允许上海日期 {due}，当前 {actual}；未调用 API')
    return due


def main(batch):
    due=require_due_date(batch)
    api=ModelAPI(config())
    manifest=verify_frozen(batch,api)
    ident='safe-followup-'+str(time.time_ns())
    for trace in (batch/'lanes/R2').glob('*/repeat-*/attempt-*.jsonl'):
        if not trace.with_name(trace.stem+'-result.json').exists():
            raise ValueError('R2 存在未闭合尝试，禁止自动重复采集；先保存中断审计')
    done={(read(p)['task_id'],read(p)['repeat']) for p in
          (batch/'lanes/R2').glob('*/repeat-*/attempt-*-result.json')}
    if len(done)==160:
        print(json.dumps({'R2_already_terminated':160,'api_requests_made':0}))
        return
    # 原题、参数、工具、上下文均不变，仅在整个批次层增加永久拒绝止损。
    write(batch/'R2-orchestrators'/(ident+'.json'), {
          'at':now(),'orchestrator_fp':fp(Path(__file__).read_text()),
          'permanent_api_stop':[401,402,403],'skip_all_terminated_slots':True,
          'original_frozen_collector_unchanged':True,'judge_api_used':False})
    before=canary(batch/'canary/R2'/(ident+'-before'))
    active={**manifest,'actual_online_canary_before':before}
    started=now()
    counts=Counter()
    stopped=None
    for task_id,task in sorted(load_tasks().items()):
        for repeat in range(1,6):
            if (task_id,repeat) in done:
                continue
            if now()[:10] != due:
                stopped='crossed_Asia_Shanghai_date'
                break
            status=run_once(batch,'R2',task_id,repeat,task,api,active)
            counts[status]+=1
            directory=batch/'lanes/R2'/task_id/f'repeat-{repeat}'
            trace=sorted(directory.glob('attempt-*.jsonl'))[-1]
            events=[json.loads(s) for s in trace.read_text().splitlines()]
            stopped=next((e['payload']['http_status'] for e in events if e['type']=='model_response'
                          and e['payload'].get('http_status') in (401,402,403)),None)
            print(json.dumps({'at':now(),'lane':'R2','task':task_id,'repeat':repeat,
                              'status':status,'permanent_stop':stopped}),flush=True)
            if stopped:
                break
        if stopped:
            break
    after=canary(batch/'canary/R2'/(ident+'-after'))
    before_fp,after_fp=exact_canary(before['path']),exact_canary(after['path'])
    confirm=canary(batch/'canary/R2'/(ident+'-confirm')) if before_fp!=after_fp else None
    write(batch/'canary/R2'/(ident+'-gate.json'), {'before':before,'after':after,'rerun':confirm,
          'drift_state':'STABLE' if before_fp==after_fp else 'DRIFTED',
          'all_probes_valid':before['all_valid'] and after['all_valid'],
          'exact_before':before_fp,'exact_after':after_fp})
    write(batch/'sessions'/('R2-'+ident+'.json'), {'started_at':started,'ended_at':now(),
          'counts':dict(counts),'lane':'R2','selected':sorted(load_tasks()),
          'prior_terminated_slots':len(done),'stopped_reason':stopped,
          'all_planned_slots_terminated':len(done)+sum(counts.values())==160,
          'actual_date_guard':due,'pid':os.getpid()})
    generate(batch)
    api.session.close()
    if stopped:
        raise SystemExit(2)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--batch',default='E6-20261007-1791350994158084000')
    args=parser.parse_args()
    batch=(HERE/'batches'/args.batch).resolve()
    if not batch.is_relative_to((HERE/'batches').resolve()):
        raise ValueError('批次路径越界')
    main(batch)
