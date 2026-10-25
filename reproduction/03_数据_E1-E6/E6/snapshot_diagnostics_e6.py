"""快照诊断材料：真实哨兵、软404和多页协议；不混入32题评分。"""
# 标准库：时间和JSON。
import json
import time
# 本轮保存设施和生产协议工具。
from common_e6 import fp, write, now
from trace_e6 import Trace
from transport_e6 import Transport
from src.ai_tools import ToolBox
from src.client import BestClient

def capture(batch):
    """少量真实请求补足快照协议材料，明确是诊断而非agent任务。"""
    directory = batch / 'snapshot-diagnostics'
    tw = Trace(directory / 'live-protocol.jsonl', batch.name+'-snapshot-diagnostics', 'DIAGNOSTIC')
    tw.emit('run_start', {'manifest': {'diagnostic': True, 'purpose': 'snapshot_protocol_preservation_not_task_or_control_group'}})
    client = BestClient(rate_limit=2.0)
    transport = Transport(client, tw.emit)
    box = ToolBox(client)
    results = {}
    results['unresolved_name'] = box.resolve_name('E6_UNRESOLVED_OBJECT_20261007_7f92c1').to_dict()
    # 按生产客户端构造表单；直接观察已知历史无效路由，不能说7工具agent可绕过其入口校验。
    form = client._build_form('stripe82', [], 10, ra=180.0, dec=30.0, radius_arcsec=60)
    sqlid, error = client._submit_query_for_sqlid('t/calib/stripe82/q', form)
    results['soft404_route'] = {'sqlid': sqlid, 'error': error, 'path': 't/calib/stripe82/q',
                               'scope': 'raw_client_protocol_diagnostic_not_available_through_invalid_catalog_ToolBox'}
    # 定参真实查询，较小页大小用于冻结真实page1/page2与count；不修改SUT任务的默认页大小。
    result = client.cone_search(ra=180.0, dec=30.0, radius_arcsec=60.0, catalog='ps1', max_records=10, page_size=5)
    results['two_pages'] = {'success': result.success, 'total_count': result.total_count, 'returned_count': result.returned_count,
                            'truncated': result.truncated, 'query_params': result.query_params,
                            'rows': [s.to_dict() for s in result.sources]}
    tw.emit('diagnostic_result', {'results': results, 'not_scored': True})
    tw.emit('run_end', {'total_requests': transport.session_requests, 'total_elapsed_s': time.monotonic()-tw.start, 'outcome': 'success'})
    tw.close()
    client.close()
    write(directory/'diagnostic-summary.json', {'at': now(), 'results': results, 'observed_session_requests': transport.session_requests,
          'notes': '真实诊断不补造缺上下文任务或扩大对照；其请求可归档但未触发的任务仍报告场景覆盖不足'})
    return directory/'live-protocol.jsonl'
