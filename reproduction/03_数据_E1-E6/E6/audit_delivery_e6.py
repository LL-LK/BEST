"""独立交付审计：读取全部实际尝试、冻结输入和快照；不调用任何API。"""
# 标准库：命令行、指纹、JSON与不可覆盖审计目录。
import argparse
import base64
import hashlib
import json
import time
from collections import Counter
# 临时设施：安全配置和逐事件验证。
from common_e6 import HERE, SECRETS, config, fp, now, read, write
from trace_e6 import validate

def decoded_secret_present(response):
    """检查正文及每层重定向的原始字节；结果绝不回显匹配片段。"""
    raw = base64.b64decode(response.get('content_base64', ''))
    return any(secret and secret.encode() in raw for secret in SECRETS) or any(
        decoded_secret_present(r) for r in response.get('redirects', []))

def check_snapshot_sources(snapshot):
    """核验每个来源指针，不只核验被选作回放的第一条。"""
    errors, cache, checked = [], {}, 0
    if fp(snapshot['bank']) != snapshot['fingerprint']:
        errors.append('bank_fingerprint_mismatch')
    for key, record in snapshot['bank'].items():
        if key != fp(record['request']) or record['mode'] != 'live':
            errors.append('invalid_request_semantics_or_source:'+key)
        pointers = snapshot['sources'].get(key, [])
        if not pointers:
            errors.append('missing_snapshot_source:'+key)
        for index, pointer in enumerate(pointers):
            checked += 1
            try:
                if pointer['trace'] not in cache:
                    with open(pointer['trace']) as stream:
                        cache[pointer['trace']] = [json.loads(s) for s in stream]
                event = cache[pointer['trace']][pointer['seq']]
                source = event['payload']
                if (event['seq'] != pointer['seq'] or event['type'] != 'network_exchange'
                    or fp(source) != pointer['fp'] or source.get('request_key') != key
                    or source.get('mode') != 'live' or (index == 0 and source != record)):
                    errors.append('snapshot_source_mismatch:'+key+':'+str(index))
            except (OSError, ValueError, KeyError, IndexError, TypeError):
                errors.append('unreadable_snapshot_source:'+key+':'+str(index))
    return errors, checked

def check_replay_network(network, snapshot, completed):
    """逐回包核对bank来源；正确失败关闭的未知分支不冒充审计异常。"""
    errors, misses = [], []
    bank = snapshot['bank'] if snapshot else {}
    for record in network:
        key = record.get('request_key')
        if record.get('mode') != 'replay':
            errors.append('R3_live_network')
            continue
        source = bank.get(key)
        if source is None:
            misses.append(key)
            if completed or 'E_SNAPSHOT_MISS' not in record.get('error', '') or record.get('response'):
                errors.append('R3_unknown_branch_not_failed_closed:'+str(key))
        elif (record.get('source_fp') != fp(source) or record.get('response') != source.get('response')
              or (source.get('error') and record.get('error') != source['error'])):
            errors.append('R3_replay_source_mismatch:'+str(key))
    return errors, misses

def audit(batch):
    """所有失败也进入审计，区分预期无最终答案和完整性错误。"""
    config()
    manifest = read(batch/'run_manifest.json')
    snapshot = read(batch/'snapshot_manifest.json') if (batch/'snapshot_manifest.json').exists() else None
    prompt = (batch/'frozen/system-prompt.txt').read_text()
    schema = read(batch/'frozen/function-tools.json')
    out = batch/'delivery-audits'/str(time.time_ns())
    records, totals = [], Counter()
    for path in sorted((batch/'lanes').glob('*/*/repeat-*/attempt-*.jsonl')):
        lane, task, repeat = path.parts[-4:-1]
        try:
            events = [json.loads(s) for s in path.read_text().splitlines()]
        except ValueError:
            records.append({'trace':str(path),'lane':lane,'errors':['incomplete_jsonl']})
            totals['incomplete_jsonl'] += 1
            continue
        errors = validate(events, None if lane.startswith('R0') else manifest['sampling']['actual_request_parameters'])
        result_path = path.with_name(path.stem+'-result.json')
        if lane.startswith('R0'):
            result_path = path.parent/'success.json'
        result = read(result_path) if result_path.exists() else None
        requests = [e for e in events if e['type'] == 'model_request']
        input_errors = []
        if requests:
            task_text = events[0]['payload']['task']['utterance']
            expected_user = task_text+'\n\n实验运行数据标识（仅供引用）：'+manifest['best_data']['fingerprint_before']
            for e in requests:
                body = e['payload']['request']
                if body['input'][:2] != [{'role':'system','content':prompt},{'role':'user','content':expected_user}]:
                    input_errors.append('frozen_initial_input_changed:'+str(e['seq']))
                if body['tools'] != schema or body.get('tool_choice') != 'auto':
                    input_errors.append('schema_or_tool_choice_changed:'+str(e['seq']))
                if e['payload']['endpoint'] != manifest['model']['endpoint']:
                    input_errors.append('model_endpoint_changed:'+str(e['seq']))
        network = [e['payload'] for e in events if e['type'] == 'network_exchange']
        replay_misses = []
        if lane == 'R3':
            replay_errors, replay_misses = check_replay_network(network,snapshot,bool(result and result.get('completed')))
            input_errors.extend(replay_errors)
        for r in network:
            response = r.get('response')
            if response and decoded_secret_present(response):
                input_errors.append('credential_in_response_bytes')
        totals[lane+'_attempts'] += 1
        totals[lane+'_completed'] += bool(result and result.get('completed'))
        totals[lane+'_valid'] += bool(result and result.get('completed') and not errors and not input_errors)
        records.append({'trace':str(path),'lane':lane,'task':task,'repeat':repeat,
                        'result_exists':result is not None,'completed':bool(result and result.get('completed')),
                        'validation_errors':errors,'frozen_input_errors':input_errors,
                        'models':dict(Counter(e['payload'].get('returned_model') for e in events if e['type']=='model_response')),
                        'generation_requests':len(requests),'network_exchanges':len(network),
                        'R3_replay_source_checks':len(network) if lane=='R3' else 0,
                        'R3_expected_snapshot_misses':replay_misses,
                        'trace_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    # 只输出命中文件名和计数，永不输出密钥或匹配片段。
    secret_hits = []
    for path in batch.rglob('*'):
        if path.is_file():
            raw = path.read_bytes()
            if any(secret and secret.encode() in raw for secret in SECRETS):
                secret_hits.append(str(path))
    bank_errors = []
    checked_sources = 0
    if snapshot:
        bank_errors, checked_sources = check_snapshot_sources(snapshot)
    payload = {'at':now(),'batch':batch.name,'totals':dict(totals),'records':records,
               'credential_scan':{'hits':secret_hits,'scope':'batch_all_files_and_decoded_network_response_bytes'},
               'snapshot':{'present':snapshot is not None,'entries':len(snapshot['bank']) if snapshot else 0,
                           'source_pointers_checked':checked_sources,'errors':bank_errors},
               'judge_api_used':False,'U7_raters':0,'R2_collected':(batch/'lanes/R2').exists(),
               'protocol_pass':False,'note':'失败原件仍保留；其无最终答案/快照缺失是无效原因，不以删除失败提高成绩。'}
    write(out/'audit.json',payload)
    print(json.dumps({'audit':str(out/'audit.json'),'totals':dict(totals),'secret_hits':len(secret_hits),'bank_errors':len(bank_errors)}))
    return out

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch',required=True)
    args = parser.parse_args()
    audit(HERE/'batches'/args.batch)
