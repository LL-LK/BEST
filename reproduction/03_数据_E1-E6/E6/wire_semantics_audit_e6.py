"""离线检查软错误被成功信封掩盖、及冻结请求键丢弃SQLID前缀的范围。"""
import argparse
import json
import re
import time
from urllib.parse import urlsplit
from common_e6 import HERE, read, write, fp, now
from src.protocol import is_soft_error, soft_error_detail

def wire_failures(events):
    findings=[]
    for event in events:
        if event['type']!='tool_result':
            continue
        parent=event['parent_seq']
        call=events[parent]['payload']
        env=event['payload']['envelope']
        for network in events[parent+1:event['seq']]:
            if network['type']!='network_exchange':
                continue
            payload=network['payload'];response=payload.get('response',{})
            if response.get('status')==200 and is_soft_error(response.get('text','')):
                findings.append({'tool_call_seq':parent,'network_seq':network['seq'],
                    'tool':call['tool'],'args':call['args'],'raw_http_status':200,
                    'soft_error':soft_error_detail(response['text']),
                    'original_url':payload.get('original_url'),'envelope_ok':env['status']['ok'],
                    'envelope_error_code':env['status'].get('error_code'),
                    'wrapped_as_success':env['status']['ok'] is True})
    return findings

def prefix_records(events, source):
    records=[]
    for event in events:
        if event['type']!='network_exchange':
            continue
        payload=event['payload'];url=payload.get('original_url','')
        match=re.search(r'/sqlid/(s?)(\d+)',urlsplit(url).path)
        if not match:
            continue
        response=payload.get('response',{})
        records.append({'request_key':payload['request_key'],'prefix':'s' if match[1] else 'bare',
                        'trace':source,'seq':event['seq'],'original_url':url,
                        'response_http_status':response.get('status'),
                        'response_text_fp':fp(response.get('text','')),
                        'raw_soft_error':is_soft_error(response.get('text','')),
                        'network_error':payload.get('error')})
    return records

def generate(batch):
    sources=[batch]
    if (batch/'pilot-source.json').exists():
        sources.append(HERE/'batches'/read(batch/'pilot-source.json')['batch'])
    paths=sorted(p for source in sources for p in (source/'lanes').glob('*/*/repeat-*/attempt-*.jsonl'))
    paths+=sorted((batch/'snapshot-diagnostics').glob('*.jsonl'))
    findings, grouped=[],{}
    for path in paths:
        try:
            events=[json.loads(s) for s in path.read_text().splitlines()]
        except ValueError:
            continue
        for finding in wire_failures(events):
            findings.append({'trace':str(path),**finding})
        for record in prefix_records(events,str(path)):
            grouped.setdefault(record['request_key'],[]).append(record)
    both={key:rs for key,rs in grouped.items() if len({r['prefix'] for r in rs})>1}
    payload={'at':now(),'batch':batch.name,'soft_error_evidence':findings,
             'soft_error_success_wraps':sum(f['wrapped_as_success'] for f in findings),
             'frozen_request_key_erases_bound_sqlid_s_prefix':True,
             'observed_keys_with_both_prefix_styles':len(both),'prefix_style_shared_keys':both,
             'limitation':'绑定会话的request_key会丢弃s前缀。结构上未保留该路径区别；不同页大小/投影等同时改变时不能将响应差异单因归于前缀。未新增因果对照或修冻结collector。'}
    out=batch/'wire-semantics-audits'/str(time.time_ns())/'audit.json'
    write(out,payload)
    print(json.dumps({'audit':str(out),'soft_error_success_wraps':payload['soft_error_success_wraps'],
                      'observed_keys_with_both_prefix_styles':len(both)}))
    return out

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--batch',required=True)
    generate(HERE/'batches'/parser.parse_args().batch)
