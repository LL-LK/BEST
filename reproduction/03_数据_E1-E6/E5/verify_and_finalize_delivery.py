from pathlib import Path
import json,hashlib,zipfile,csv,collections,datetime,yaml
ROOT=Path(r'<WORK_ROOT>');REPORT=Path(r'<USER_HOME>\Desktop\论文\e2和e5重构计划\E5_正式结果_2026-10-12');BASE=REPORT.parent/'E5_执行_2026-10-12_v4_01'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
rows=json.loads((REPORT/'scores.json').read_text('utf-8'));analysis=json.loads((REPORT/'analysis.json').read_text('utf-8'))
assert len(rows)==len({r['session_id'] for r in rows})==len({(r['task'],r['arm'],r['replicate']) for r in rows})==2016
schedule=json.loads((ROOT/'public/confirmatory-v51/schedule.json').read_text('utf-8'));assert {r['cell_id'] for r in rows}=={r['cell_id'] for r in schedule}
receipt=json.loads((REPORT/'scorer-receipt.json').read_text('utf-8'));assert receipt['identity'].lower().endswith('\\e5scorerv4') and sha(REPORT/'scores.json')==receipt['scores_sha256'] and sha(REPORT/'analysis.json')==receipt['analysis_sha256']
assert json.loads((REPORT/'glmm-sensitivity.json').read_text('utf-8'))['optimizer_success']
reviews=list(csv.DictReader((REPORT/'human-review-pending.csv').open(encoding='utf-8-sig')));assert len(reviews)==2016 and all(not r['human_verdict'] and not r['human_comment'] for r in reviews)
reasons=collections.Counter();byarm=collections.defaultdict(collections.Counter)
for r in rows:
    s=json.loads((ROOT/'evidence/confirmatory-v51-sealed/cells'/r['cell_id']/'summary.json').read_text('utf-8'))
    for reason in s['turn_ends']:reasons[reason['kind']]+=1
    byarm[r['arm']]['units']+=1;byarm[r['arm']]['rule_pass']+=r['e2e_success'];byarm[r['arm']]['max_tokens_units']+=any(e['kind']=='max-tokens' for e in s['turn_ends'])
    byarm[r['arm']]['other_incomplete_units']+=not s['all_turns_completed'] and not any(e['kind']=='max-tokens' for e in s['turn_ends'])
max_units=sum(v['max_tokens_units'] for v in byarm.values());assert max_units==236
extra={'schema':'e5-postrun-descriptive-diagnostics-v1','scope':'descriptive only; no new hypothesis tests or score edits','units':2016,'max_tokens_units':max_units,'turn_end_reason_counts':dict(reasons),'by_arm':{k:dict(v) for k,v in byarm.items()},'category_rule_rates':analysis['by_class']}
(REPORT/'execution-diagnostics.json').write_text(json.dumps(extra,ensure_ascii=False,indent=2),encoding='utf-8')
md=REPORT/'E5_结果报告.md';text=md.read_text('utf-8');text+='\n全部计划单元已执行并封存，不表示全部任务成功。236个单元触及冻结的maxTokens=4096预算，按原规则计入未通过，未提高预算或补跑；各臂和终止原因见execution-diagnostics.json。\n\n类别结果仅作描述：B3/B2b的数据任务规则通过率为57.58%/66.67%，澄清38.10%/28.57%，拒绝65.63%/55.21%，语义27.78%/11.11%。总体差值不能解释成每类能力都提升。\n';md.write_text(text,encoding='utf-8')
manifest=json.loads((ROOT/'evidence/confirmatory-v51-sealed/artifact-hashes.json').read_text('utf-8'))
creds=yaml.safe_load((ROOT/'profile/.credentials.yaml').read_text('utf-8'));secrets=[]
def leaves(v):
    if isinstance(v,dict):
        for child in v.values():leaves(child)
    elif isinstance(v,list):
        for child in v:leaves(child)
    elif isinstance(v,str) and len(v)>=40:secrets.append(v.encode())
leaves(creds);assert secrets,'credential leak scan must have an actual credential needle'
def hidden(v):
    if isinstance(v,dict):
        if v.get('role')=='assistant' and isinstance(v.get('content'),list):
            assert not any(isinstance(c,dict) and c.get('type') in ('reasoning','thinking','redacted_thinking') for c in v['content'])
        for c in v.values():hidden(c)
    elif isinstance(v,list):
        for c in v:hidden(c)
package=REPORT/'E5_public_reproduction.zip';previous=BASE/'E5_public_reproduction-before-diagnostics.zip';assert not previous.exists();package.rename(previous)
matched=set();source_sessions=0
with zipfile.ZipFile(previous) as src,zipfile.ZipFile(package,'x',compression=zipfile.ZIP_DEFLATED) as dst:
    names=src.namelist();assert len(names)==len(set(names))
    assert not any(any(k in n.lower().split('/') for k in ('profile','profiles','private','credentials')) or n.lower().endswith(('.clixml','gold.json','credentials.yaml')) for n in names)
    for name in names:
        data=src.read(name)
        assert not any(secret in data for secret in secrets),'actual credential value found in package'
        if name.startswith('evidence/cells/'):
            rel=name.removeprefix('evidence/');assert hashlib.sha256(data).hexdigest()==manifest[rel];matched.add(rel)
        if name.endswith('session.events.redacted.jsonl'):
            for line in data.splitlines():hidden(json.loads(line))
            source_sessions+=1
        if name=='results/E5_结果报告.md':data=md.read_bytes()
        dst.writestr(name,data)
    dst.write(REPORT/'execution-diagnostics.json','results/execution-diagnostics.json')
assert matched=={k for k in manifest if k.startswith('cells/')} and source_sessions==2016
hashes={p.name:sha(p) for p in REPORT.iterdir() if p.is_file() and p.name!='SHA256.json'}
(REPORT/'SHA256.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
verification={'schema':'e5-final-delivery-verification-v1','verified_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'units':2016,'unique_sessions':2016,'source_exports':source_sessions,'source_artifacts_matched':len(matched),'zip_crc_read_verified':True,'private_gold_and_profile_absent':True,'actual_credential_values_absent':True,'hidden_assistant_reasoning_absent':True,'score_and_analysis_receipt_hashes_match':True,'human_review_rows_blank':2016,'glmm_optimizer_success':True,'package_sha256':sha(package),'human_review':'pending'}
(ROOT/'evidence/delivery-verification-v51.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
(BASE/'FINAL-DELIVERY.json').write_text(json.dumps({'logical_e5_units':2016,'report_directory':str(REPORT),'human_review':'pending','verification':verification,'hashes':hashes},indent=2),encoding='utf-8')
print(json.dumps(verification))
