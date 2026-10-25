"""只读全量已结束记录，恢复离线汇总，不重采或调用 API。"""
import argparse
import json
from pathlib import Path
import common_e6
import audit_delivery_e6
import supplement_e6
from offline_delivery_support_e6 import credentials_for_offline_only, generic_scan


def finalize(batch):
    done=supplement_e6.terminal_slots(batch)
    if len(done)!=160:
        raise ValueError('未结束全部槽位，不能生成完成报告')
    for trace in (batch/'lanes/R3').glob('*/repeat-*/attempt-*.jsonl'):
        if not trace.with_name(trace.stem+'-result.json').exists():
            raise ValueError('存在未闭合轨迹')
    protocol=common_e6.read(batch/'SUPPLEMENT-PROTOCOL.json')
    if common_e6.fp(Path(supplement_e6.__file__).read_text())!=protocol['runner_fp']:
        raise ValueError('冻结采集器已改变')
    credentials=credentials_for_offline_only()
    original_audit=audit_delivery_e6.audit
    def audit_offline(target):
        output=original_audit(target)
        value=common_e6.read(output/'audit.json')
        structural_hits=generic_scan(p for p in target.rglob('*') if p.is_file())
        value['credential_scan']['hits']+=structural_hits
        value['credential_scan']['scope']='结构字段、sk-模式、解码回包；已知 API 密钥精确扫描可用性单列'
        value['credential_scan'].update(credentials)
        value['credential_scan']['generic_scan_passed']=not structural_hits
        common_e6.write(output/'audit.json',value,exclusive=False)
        return output
    # 仅分析模块使用离线配置；冻结采集器字节及 run_once 均未修改或执行。
    supplement_e6.config=lambda: {}
    audit_delivery_e6.config=lambda: {}
    supplement_e6.audit=audit_offline
    out=supplement_e6.report(batch)
    common_e6.write(batch/'OFFLINE-FINALIZATION.json',{
        'at':common_e6.now(),'collector_exit_code':1,'reason':'汇总阶段重新读取配置时缺 API 密钥',
        'collection_complete':True,'sampling_parameters_changed':False,'recollected_slots':0,
        'network_calls':0,'credentials':credentials,'report':str(out),
        'analysis_only_config_override':True})
    common_e6.write(batch/'RUN-STATUS.json',{'at':common_e6.now(),'status':'collection_complete',
        'terminated_slots':160,'planned_slots':160,'stopped_http_status':None,
        'report_recovered_offline':True},exclusive=False)
    return out


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--batch',required=True)
    finalize(common_e6.HERE/'batches'/parser.parse_args().batch)
