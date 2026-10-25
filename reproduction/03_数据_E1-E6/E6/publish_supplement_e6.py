"""发布补测结果和论文补充段落；历史交付包保持不变。"""
import argparse
from collections import Counter
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from common_e6 import HERE, ROOT, SECRETS, config, read, now
from offline_delivery_support_e6 import credentials_for_offline_only, generic_scan


def delivery_check(results):
    """输出失败不等于证据损坏；只容许可从原件解释的失败标志。"""
    audit=read(results['integrity_audit'])
    failures=[]
    known_partial=[]
    for row in audit['records']:
        if not row.get('result_exists') or row.get('frozen_input_errors'):
            failures.append(row['trace'])
            continue
        errors=row.get('validation_errors',[])
        if not errors:
            continue
        if row.get('completed'):
            failures.append(row['trace'])
            continue
        events=[json.loads(s) for s in Path(row['trace']).read_text().splitlines()]
        final_count=sum(e['type']=='final_answer' for e in events)
        allowed=all((err=='final_answer_missing_or_duplicate' and final_count==0) or
                    err.startswith('snapshot_miss:') for err in errors)
        nan_exception=any(e['type']=='error' and e.get('payload',{}).get('layer')=='harness'
                          and e.get('payload',{}).get('error_code')=='ValueError'
                          and e.get('payload',{}).get('detail')=='Out of range float values are not JSON compliant: nan'
                          for e in events)
        if (nan_exception and final_count==0 and set(errors)==
            {'tool_pairing_incomplete','final_answer_missing_or_duplicate','run_total_cost_mismatch'}):
            allowed=True
            known_partial.append({'trace':row['trace'],'errors':errors,
                                  'reason':'NaN 工具回包序列化中断；工具结果和成本对账存在缺段，仍属无效记录'})
        if not allowed:
            failures.append(row['trace'])
    passed=not failures and not audit['credential_scan']['hits'] and not audit['snapshot']['errors']
    return {'passed':passed,'unexpected_evidence_errors':failures,
            'invalid_output_traces':sum(bool(r.get('validation_errors')) for r in audit['records']),
            'known_partial_trace_failures':known_partial,
            'exact_known_api_key_scan_available':audit['credential_scan'].get('exact_known_api_key_scan_available',True),
            'scope':'source/input/snapshot integrity separate from failed output validity; credential scan scope disclosed'}


def remove_u7(value):
    """当前修订方案仅保留 U1–U6，原件中的旧字段留在证据 ZIP。"""
    if isinstance(value,dict):
        return {k:remove_u7(v) for k,v in value.items() if k not in ('U7','U7_raters')}
    if isinstance(value,list):
        return [remove_u7(v) for v in value if not (isinstance(v,str) and v.startswith('U7无人评阅'))]
    return value


def failure_explanations(batch, collection):
    """原因只取实际回包或已记录错误，不从缺答臆测模型能力。"""
    rows=[]
    for row in collection['failures']:
        path=batch/'lanes/R3'/row['task_id']/f"repeat-{row['repeat']}"/row['trace']
        events=[json.loads(s) for s in path.read_text().splitlines()]
        responses=[e['payload'] for e in events if e['type']=='model_response']
        statuses=[p['http_status'] for p in responses if p.get('http_status',0)>=400]
        last=responses[-1] if responses else {}
        budget=(last.get('raw',{}).get('incomplete_details') or {}).get('reason')=='max_output_tokens'
        if last.get('http_status',0)>=400:
            reason='模型接口 HTTP '+str(last['http_status'])
        elif row.get('snapshot_misses'):
            reason='未收录的冻结回包分支'
        elif budget:
            reason='推理或生成耗尽输出预算，未完成答案'
        elif '最终输出不是' in (row.get('error') or ''):
            reason='最终输出不符合冻结 JSON 格式'
        elif row.get('error')=='Out of range float values are not JSON compliant: nan':
            reason='NaN 工具回包序列化中止，工具结果与成本对账存在缺段'
        elif row.get('error')=='Response ended prematurely':
            reason='网络分块响应中断（Response ended prematurely）'
        else:
            reason=row.get('error') or '见原始错误与校验记录'
        rows.append({'task_id':row['task_id'],'repeat':row['repeat'],'reason':reason,
                     'recorded_error':row.get('error'),'validation_errors':row.get('validation_errors'),
                     'observed_http_errors_including_retries':statuses,
                     'trace':str(path.relative_to(batch))})
    return rows


def publish(batch):
    credentials=credentials_for_offline_only()
    pointer=read(batch/'LATEST-REPORT.json')
    results=read(pointer['results'])
    amendment=read(batch/'PROTOCOL-AMENDMENT-U7-REMOVAL.json')
    separated_audit=delivery_check(results)
    if not results['collection_complete'] or not separated_audit['passed'] or not results['original_files_preserved']:
        raise ValueError('补测尚未完成或审计不通过；不发布完成包')
    out=ROOT/'docs/results/2026-10-11/e6-r3-supplement'/batch.name
    if out.exists():
        raise FileExistsError('发布目录已存在；不要覆盖历史交付')
    out.mkdir(parents=True)
    report_dir=Path(pointer['report']).parent
    for path in report_dir.iterdir():
        if path.is_file():
            shutil.copyfile(path,out/path.name)
    results=remove_u7(results)
    results['current_protocol_amendment']=amendment
    current_usability=out/'R3-usability.json'
    current_usability.write_text(json.dumps(remove_u7(read(current_usability)),ensure_ascii=False,indent=2)+'\n')
    # 冻结编排器的严格标志包含预期无效输出；保留其原值并补充独立完整性口径。
    results['delivery_integrity_audit']=separated_audit
    results['producer_strict_trace_flag']=results['integrity_audit_passed']
    (out/'FINAL-RESULTS.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    readable=out/'REPORT.md'
    readable_text=readable.read_text().replace('U7 独立专家评分尚缺；','')
    readable.write_text(readable_text+'\n## 方案修订\n\n'
        '经研究者于 10 月 11 日修订，本实验取消主观 U7，仅报告客观可用性 U1–U6。'
        'U7 不再列为待完成项；原方案及原始记录作为历史证据保留。\n'
        '\n## 证据完整性与输出有效性\n\n'
        f"原件、冻结输入与快照的独立完整性审计通过：{separated_audit['passed']}。"
        f"有 {separated_audit['invalid_output_traces']} 条轨迹含无效输出标志，失败记录仍保留并计入分母。"
        '上文冻结编排器的严格标志同时计入这些输出失败，不能据其为 False 推断原件损坏。\n'
        '\n## 指标释义\n\n'
        '- TSC：同题重复时，模型采用的工具调用序列是否一致。\n'
        '- PAC_call：工具调用位置与其参数是否一致。\n'
        '- RDC：工具返回的数据是否一致；本补测使用冻结回包指纹。\n'
        '- FCC：回答的核心结论是否一致，不等同于科学事实准确率。\n'
        '\n0–1 越高表示越一致；少于两次有效重复时，该题记为缺失。'
        '“有效”表示轨迹和输出格式符合采集条件，澄清、拒绝也可有效。\n')
    for name in ('SUPPLEMENT-PROTOCOL.json','REMAINING-WORK.md','TESTS.log','RUN-STATUS.json','run_manifest.json',
                 'PORTABLE-SNAPSHOT-VERIFICATION.json','FINAL-TESTS.log','ASSISTANT-REVIEW-NOTES.json',
                 'R2-DATE-GUARD-PREFLIGHT.json','PROTOCOL-AMENDMENT-U7-REMOVAL.json','DELIVERY-TESTS.log',
                 'FINAL-TESTS-311.log','FINAL-TESTS-313.log','FINAL-TESTS-314.log','OPERATIONAL-TIMING-NOTE.json',
                 'OFFLINE-FINALIZATION.json','OFFLINE-FINALIZATION.log'):
        if (batch/name).exists():
            shutil.copyfile(batch/name,out/name)
    protocol=remove_u7(read(out/'SUPPLEMENT-PROTOCOL.json'))
    protocol['current_protocol_amendment']=amendment
    protocol['usability_metrics']=['U1','U2','U3','U4','U5','U6']
    (out/'SUPPLEMENT-PROTOCOL.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2)+'\n')
    shutil.copyfile(results['integrity_audit'],out/'INTEGRITY-AUDIT.json')
    if not credentials['exact_known_api_key_scan_available']:
        with readable.open('a') as handle:
            handle.write('\n## 离线收尾及凭据扫描范围\n\n'
                '采集完成后本机配置已无 API 密钥，原汇总入口因此退出；现已仅从原件恢复离线汇总，未补采或调用网络。'
                '结构敏感字段、sk-模式及解码回包的检查未发现凭据；按当前实际密钥进行的精确字串扫描不可用，不能标为已通过。\n')
    if separated_audit['known_partial_trace_failures']:
        with readable.open('a') as handle:
            handle.write('\n## 已知的部分轨迹缺段\n\n'
                'REPRO-11 第 3 次重复的 NaN 工具回包无法序列化，导致工具结果缺段及成本对账不一致。'
                '已保存的事件指纹、冻结输入和快照来源核验通过，但该轨迹不完整且未计为有效。'
                '此失败计入总体分母；不能把来源完整性核验解释为全部工具输出及成本账目均已闭合。\n')
    score=results['consistency']
    audit=results['collection_audit']
    failure_rows=failure_explanations(batch,audit)
    (out/'FAILURE-EXPLANATIONS.json').write_text(json.dumps(failure_rows,ensure_ascii=False,indent=2)+'\n')
    failure_lines=['# E6 补测失败记录','',
                   '每条均保留原始输出与错误，不重跑为成功，不将 HTTP 200 视为答案有效。','',
                   '| 题号 | 重复 | 实际失败原因 |','|---|---:|---|']
    failure_lines += [f"| {r['task_id']} | {r['repeat']} | {r['reason'].replace('|','／').replace(chr(10),' ')} |"
                      for r in failure_rows]
    if not failure_rows:
        failure_lines += ['', '本批没有失败尝试。']
    failure_lines += ['', '## 分类计数','']+[f'- {reason}：{count} 次'
                        for reason,count in Counter(r['reason'] for r in failure_rows).items()]
    (out/'失败记录.md').write_text('\n'.join(failure_lines)+'\n')
    ef=results['efficiency']
    u=results['usability']['summary']
    if (out/'OPERATIONAL-TIMING-NOTE.json').exists():
        note=read(out/'OPERATIONAL-TIMING-NOTE.json')
        with readable.open('a') as handle:
            handle.write('\n## 时间记录异常与运行条件\n\n'
                f"REPRO-22 第 2 次重复出现网络超时与分块响应中断。单调计时 {note['monotonic_wall_s']:.3f} 秒，"
                f"日历跨度 {note['calendar_span_s']:.3f} 秒；差额原因未确认，不能算作模型推理耗时。"
                '随后启用随采集 PID 退出的临时防空闲休眠措施，未改变模型、提示、参数或失败槽位。'
                '该运行条件变化与原始失败均保留；时间与用量比较需要同时考虑这一限制。\n')
    def percentage(value):
        return f'{value*100:.2f}%' if value is not None else '缺失'
    metric_sentences=[]
    for name in ('TSC','PAC_call','RDC','FCC'):
        row=score['aggregate'][name]
        ci=row['bootstrap_95']
        metric_sentences.append(f"{name}={row['point']:.4f}，95% 区间 [{ci[0]:.4f}, {ci[1]:.4f}]，"
                                f"可估计题数 {row['task_units']}" if ci else f'{name} 样本不足')
    paragraph=(f"自 2026 年 10 月 11 日起，在更换认证密钥并补足服务商余额后，对原冻结 R3 任务开展事后全量补测。"
               f"补测使用原 32 题，每题 5 次独立上下文，共 160 个计划槽位，沿用原模型、生成参数、系统提示、工具实现和冻结实际回包。"
               f"全部 160 个槽位已结束，产生 {score['records']} 份有效记录（{percentage(score['records']/160)}），"
               f"失败 {audit['failure_attempts']} 次，{score['coverage']['tasks_with_5_valid']} 题具有完整 5 次有效重复。"
               + '；'.join(metric_sentences)+'。区间通过题号成组重抽 10000 次估计，指标以有效记录为条件。'
               '本次结果与 10 月 7 日原 R3 单独报告，不替换原 69 次余额不足或其他失败。'
               '服务商权重版本不透明；FCC 仅代表当前助手及本地规则抽取的核心事实一致性，不代表全文科学正确或独立专家验证。')
    sections=['# E6 补测：可直接用于论文的补充段落','',paragraph,'',
              '## 运营与成本分母','',
              f"补测模型接口余额不足次数：{results['generation_api_failures']['insufficient_balance_attempts']}。"
              f"全部尝试的已知输入 token 合计 {ef['EF7']['tokens_in_observed_sum']}，"
              f"已知输出 token 合计 {ef['EF7']['tokens_out_observed_sum']}。缺失 usage 保持未知，不能当完整账单。",
              '', '## U1–U6 及剩余边界','', '| 指标 | 点估计 | 实际适用分母 |','|---|---:|---:|']
    labels={'U1':'一次可用率','U2':'错误信息要素率','U3':'澄清要素率','U4':'溯源标注覆盖',
            'U5':'步骤比值','U6':'降级标签率'}
    for name,label in labels.items():
        sections.append(f"| {name} {label} | {u[name]['point']} | {u[name]['observations']} |")
    sections+=['', '修订方案取消主观 U7，仅报告客观可用性 U1–U6。D+7 在线 R2 仍须在 2026 年 10 月 14 日执行。'
               '原协议温度、题目、材料及场景覆盖限制继续披露，不能将补测收尾表述为 E6 原完整协议全部通过。', '',
               'E3 方法与结果沿用此前论文复核包。本补充段落只更新 E6 的充值后观察，不改 E3 数据和教师反馈。']
    (out/'论文补充段落.md').write_text('\n'.join(sections)+'\n')
    (out/'README.md').write_text('''# E6 R3 充值后补测交付

先阅读 REPORT.md 或 论文补充段落.md。FINAL-RESULTS.json 为机器结果，R3-consistency.json 保存所有逐题指标和实际分母，效率与可用性 JSON 保存全部尝试及有效记录的独立口径。

这是独立补测批次，不覆盖 10 月 7 日原件，也不把原批次失败择优替换为新答案。全部原始请求、回包、回答和失败保存在同名原始证据 ZIP；快照来源指针指向原 E6 批次的真实网络轨迹，来源已全量核验。

本轮 E6 取消主观 U7，只保留客观 U1–U6；不再等待 E6 人工评分。尚待 10 月 14 日 D+7 在线复测。原协议门禁仍未通过。E3 既有交付包保持不变。

原始证据 ZIP 已同时收录快照来源网络轨迹和路径映射。解压后，在批次目录运行 `python3 verify_supplement_archive_e6.py`，即可用标准库离线核验全部来源；不需要 API 密钥、服务商连接或原电脑的文件路径。该核验确认来源与指纹，不能替代科学正确性复核。
''')
    # 摘要、正文和原件都扫描真实当前密钥；绝不输出凭据或匹配片段。
    for directory in (out,batch):
        if generic_scan(p for p in directory.rglob('*') if p.is_file()):
            raise ValueError('结构或模式扫描发现可能凭据；停止发布')
        for path in directory.rglob('*'):
            if path.is_file() and any(secret and secret.encode() in path.read_bytes() for secret in SECRETS):
                raise ValueError('发现凭据，停止发布：'+str(path.relative_to(directory)))
    raw_zip=out.parent/(batch.name+'-原始证据.zip')
    snapshot=read(batch/'snapshot_manifest.json')
    source_paths=sorted({p['trace'] for pointers in snapshot['sources'].values() for p in pointers})
    source_map={path:{'archive_path':f'{batch.name}/snapshot-sources/{i:03d}.jsonl',
                      'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}
                for i,path in enumerate(source_paths)}
    with zipfile.ZipFile(raw_zip,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in sorted(batch.rglob('*')):
            if path.is_file():
                archive.write(path,Path(batch.name)/path.relative_to(batch))
        for source,entry in source_map.items():
            raw=Path(source).read_bytes()
            if any(secret and secret.encode() in raw for secret in SECRETS):
                raise ValueError('快照来源含当前凭据；停止发布')
            archive.writestr(entry['archive_path'],raw)
        archive.writestr(batch.name+'/SNAPSHOT-SOURCE-PATH-MAP.json',
                         json.dumps(source_map,ensure_ascii=False,indent=2)+'\n')
        archive.write(HERE/'verify_supplement_archive_e6.py',batch.name+'/verify_supplement_archive_e6.py')
        for path in sorted(HERE.glob('*.py')):
            archive.write(path,batch.name+'/supplementary-harness/'+path.name)
    with zipfile.ZipFile(raw_zip) as archive:
        if archive.testzip() is not None:
            raise ValueError('原始证据 ZIP 校验失败')
    artifacts={str(p.relative_to(out)):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
                                    'bytes':p.stat().st_size} for p in sorted(out.rglob('*')) if p.is_file()}
    receipt={'at':now(),'batch':batch.name,'report':str(out/'REPORT.md'),
             'paper_paragraph':str(out/'论文补充段落.md'),'results':str(out/'FINAL-RESULTS.json'),
             'artifacts':artifacts,'raw_archive':str(raw_zip),
             'raw_archive_sha256':hashlib.sha256(raw_zip.read_bytes()).hexdigest(),
             'raw_archive_bytes':raw_zip.stat().st_size,'original_e3_e6_paper_unchanged':True,
             'bundled_snapshot_source_traces':len(source_paths),
             'delivery_integrity_audit':separated_audit,
             'remaining':['2026-10-14 R2 D+7'],'excluded_subjective_metric':'U7',
             'current_protocol_amendment':amendment,'protocol_complete':False}
    (out/'DELIVERY-MANIFEST.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    # 将当前入口指向新交付；历史报告和压缩包不覆盖。
    (HERE/'SUPPLEMENT-DELIVERY.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:receipt[k] for k in ('batch','report','raw_archive','raw_archive_bytes','protocol_complete')},ensure_ascii=False))
    return out


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--batch',required=True)
    publish(HERE/'batches'/parser.parse_args().batch)
