"""当前实验进程的阶段编排：等pilot收尾后顺序实跑R0、R1、R3。"""
# 标准库：当前进程阶段等待、时间和输出；不创建定时任务。
import json
import time
# 本轮单进程设施：准备、回放、采集与报告。
from common_e6 import HERE, read, write, fp, now
from prepare_e6 import prepare
from run_e6_formal import run_lane
from r0_e6 import run as run_r0
from transport_e6 import freeze_bank
from snapshot_diagnostics_e6 import capture
from report_e6 import generate, pilot_calibration

def main():
    """按授权持续运行，所有模型/站点采集在本次进程完成。"""
    pilot_batch = HERE / 'batches' / read(HERE/'current.json')['batch']
    deadline = time.monotonic() + 14400
    while not list((pilot_batch/'sessions').glob('pilot-*.json')):
        if time.monotonic() > deadline:
            raise RuntimeError('pilot未能在当前执行窗口收尾，请检查原件；不启动正式采集')
        time.sleep(5)
    batch = prepare()
    old, new = read(pilot_batch/'run_manifest.json'), read(batch/'run_manifest.json')
    checks = {'prompt': old['system_prompt']['fingerprint'] == new['system_prompt']['fingerprint'],
              'schema': old['tool_schema']['function_tools'] == new['tool_schema']['function_tools'],
              'parameters': old['sampling']['actual_request_parameters'] == new['sampling']['actual_request_parameters'],
              'task_set': old['eval_data']['task_set_fp'] == new['eval_data']['task_set_fp'],
              'data_identity': old['best_data']['fingerprint_before'] == new['best_data']['fingerprint_before']}
    write(batch/'pilot-source.json', {'batch': pilot_batch.name, 'checks': checks,
          'purpose': '独立校准来源；不与正式R1/R3样本合并',
          'collector_changes': '增加材料/端点/成本篡改校验，R3标签保持相同输入；pilot没有R3，其实际模型输入和参数不变'})
    if not all(checks.values()):
        raise RuntimeError('校准来源与正式系统不一致，需重新pilot，未混批')
    calibration_dir = batch/'pilot-calibration'
    calibration_dir.mkdir()
    pilot = pilot_calibration(batch, calibration_dir)
    if not pilot['complete_10x5']:
        raise RuntimeError('pilot计划50个槽位未完成，正式运行停止')
    run_r0(batch)
    print(json.dumps({'stage': 'R1_start', 'batch': batch.name, 'at': now()}), flush=True)
    run_lane(batch, 'R1')
    # 原协议材料仅做真实快照诊断，无法触发的agent场景仍缺失。
    diagnostic = capture(batch)
    paths = sorted((pilot_batch/'lanes/pilot').glob('*/repeat-*/attempt-*.jsonl')) + sorted((batch/'lanes/R1').glob('*/repeat-*/attempt-*.jsonl')) + [diagnostic]
    freeze_bank(paths, batch/'snapshot_manifest.json')
    snapshot = read(batch/'snapshot_manifest.json')
    write(batch/'R3-frozen-manifest.json', {**read(batch/'run_manifest.json'),
          'snapshot': {'id': batch.name+'-actual-request-bank', 'fingerprint': snapshot['fingerprint'],
                       'entries': len(snapshot['bank']), 'source_traces': [str(p) for p in paths], 'freeze_at': now()}})
    print(json.dumps({'stage': 'R3_start', 'batch': batch.name, 'snapshot_entries': len(snapshot['bank']), 'at': now()}), flush=True)
    run_lane(batch, 'R3')
    out = generate(batch)
    write(batch/'COLLECTION-COMPLETE.json', {'at': now(), 'report': str(out), 'R2': 'D+7_manual_not_collected',
          'collection_complete': True, 'record_validity_and_protocol_pass': 'see_audits_and_blockers'})
    print(json.dumps({'stage': 'complete', 'batch': batch.name, 'report': str(out), 'at': now()}), flush=True)

if __name__ == '__main__':
    main()
