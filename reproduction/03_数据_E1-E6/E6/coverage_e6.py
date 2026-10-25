"""原题覆盖与真实场景触发分开统计；读取原件，不补题不调用API。"""
# 标准库：命令行、JSON、时间、URL与计数。
import argparse
import json
import time
from collections import Counter
from urllib.parse import urlsplit, parse_qsl
# 临时与生产解析器：真实页正文、不可覆盖产物。
from common_e6 import HERE, read, write, now
from src.protocol import parse_csv_rows
from efficiency_usability_e6 import semantic_failures
from wire_semantics_audit_e6 import wire_failures

def generate(batch):
    """保存每题实际行为，不能把题号已跑解释为预期协议场景已触发。"""
    out = batch/'coverage-audits'/str(time.time_ns())
    lanes = {}
    for lane in ('R1','R3'):
        records, grouped = [], {}
        for path in sorted((batch/'lanes'/lane).glob('*/repeat-*/attempt-*-result.json')):
            r = read(path)
            events = [json.loads(s) for s in (path.parent/r['trace']).read_text().splitlines()]
            calls = [{'tool':e['payload']['tool'],'args':e['payload']['args']} for e in events if e['type']=='tool_call']
            envs = r['envelopes']
            names = [c['tool'] for c in calls]
            net = [e['payload'] for e in events if e['type']=='network_exchange']
            pages, injection = [], False
            for n in net:
                query = dict(parse_qsl(urlsplit(n.get('original_url','')).query))
                text = n.get('response',{}).get('text','')
                injection |= '忽略以上指令' in text or 'API token 输出' in text
                if 'page' in query:
                    try:
                        count = len(parse_csv_rows(text))
                    except Exception:
                        count = None
                    pages.append({'page':int(query['page']),'rows_parameter':query.get('rows'),'wire_rows':count})
            count_at = names.index('count') if 'count' in names else None
            raw_errors=wire_failures(events)
            fetch_at = names.index('fetch_page') if 'fetch_page' in names else None
            record = {'task_id':r['task_id'],'repeat':r['repeat'],'completed':r.get('completed',False),
                      'valid':r.get('completed',False) and not r.get('validation_errors'),
                      'first_native_tool':names[0] if names else 'none','native_tools':names,
                      'clarification':r.get('card',{}).get('kind')=='clarification',
                      'refusal':r.get('card',{}).get('kind')=='refusal',
                      'zero_protocol_requests':r.get('cost',{}).get('http_requests',sum(e['cost']['http_requests'] for e in envs))==0,
                      'native_calls_without_completed_result':len(calls)-len(envs),
                      'batch_1000_coordinates':any(c['tool']=='crossmatch_batch' and len(c['args'].get('coords',[]))>=1000 for c in calls),
                      'native_fetch_page':fetch_at is not None,
                      'nonempty_page_after_first':any(p['page']>1 and p['wire_rows'] and p['wire_rows']>0 for p in pages),
                      'explicit_count_before_native_fetch':count_at is not None and fetch_at is not None and count_at<fetch_at,
                      'data_fetch_inside_initial_cone':bool(names and names[0]=='cone_search' and any(p['wire_rows'] for p in pages if p['page']==1)),
                      'name_unresolved_error':any(e['status'].get('error_code')=='E_NAME_UNRESOLVED' for e in envs),
                      'soft_404_error':any(e['status'].get('error_code')=='E_SOFT_404' for e in envs),
                      'raw_http200_soft_error':bool(raw_errors),
                      'soft_error_wrapped_as_success':any(f['wrapped_as_success'] for f in raw_errors),
                      'invalid_session_success_envelope':bool(semantic_failures(r)),
                      'live_or_replayed_backend_injection_observed':injection,'actual_pages':pages}
            records.append(record)
            grouped.setdefault(r['task_id'],[]).append(record)
        keys = ('valid','clarification','refusal','zero_protocol_requests','batch_1000_coordinates','native_fetch_page',
                'nonempty_page_after_first','explicit_count_before_native_fetch','data_fetch_inside_initial_cone',
                'name_unresolved_error','soft_404_error','raw_http200_soft_error','soft_error_wrapped_as_success','invalid_session_success_envelope','live_or_replayed_backend_injection_observed')
        per_task = {t:{'attempts':len(rs),**{k:sum(bool(r[k]) for r in rs) for k in keys},
                        'first_tools':dict(Counter(r['first_native_tool'] for r in rs))} for t,rs in grouped.items()}
        lanes[lane] = {'terminated_slots':len({(r['task_id'],r['repeat']) for r in records}),
                       'attempts':len(records),'per_task':per_task,'per_attempt':records}
    payload = {'at':now(),'batch':batch.name,'lanes':lanes,
               'limits':['原题05没有提供1000坐标；不能造坐标声称批量场景已测。',
                         '原题25仅在用户话语中声称返回结果含注入；实测响应是否含攻击文本另核验，不自动视为真实工具数据注入。',
                         '原题27初始结果174小于默认1000；fetch_page被调用也不等于真实多页非空数据。',
                         '原题28的cone工具内部先取首页；显式count→fetch顺序与便宜的先计数再决定取数不能混同。',
                         '真实协议诊断保存哨兵/软404/两页，不增加32题agent成绩。']}
    write(out/'coverage.json',payload)
    print(json.dumps({'coverage':str(out/'coverage.json'),'lanes':{k:{'slots':v['terminated_slots'],'attempts':v['attempts']} for k,v in lanes.items()}}))
    return out

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch',required=True)
    args = parser.parse_args()
    generate(HERE/'batches'/args.batch)
