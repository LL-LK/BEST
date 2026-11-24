"""将真实零单元会话与 worker 回执封存；不声称确认性矩阵放行。"""
from pathlib import Path
import hashlib
import json
import sys
import zstandard

ROOT = Path(r'<WORK_ROOT>')
OUT = Path(__file__).parent
REPO = Path(r'<REPO_ROOT>')
SESSION = 'session-9c80f38e-de96-4b07-a15c-5001c78fa556'
sys.path.insert(0, str(REPO))
from evals.ablation.iso.sealed_run import RunJournal, verify_sealed_run

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def redact(value):
    if isinstance(value,list):
        return [redact(v) for v in value if not (isinstance(v,dict) and v.get('type') in ('thinking','reasoning'))]
    if isinstance(value,dict):
        return {k:redact(v) for k,v in value.items() if k not in ('thinking','reasoning','reasoning_content','reasoningContent','thinkingSignature')}
    return value

source = ROOT/'profile/sessions/--D-E5-v4-20261012-02-cells--'/SESSION/'session.v4.jsonl.zstd'
with source.open('rb') as stream:
    raw = zstandard.ZstdDecompressor().stream_reader(stream).read()
records = [json.loads(line) for line in raw.splitlines()]
calls = [r for r in records if r.get('type')=='tool/call']
results = [r for r in records if r.get('type')=='tool/result']
contexts = [r['data'] for r in records if r.get('type')=='request/context']
assert contexts and all(c.get('provider')=='opencode-go' and c.get('model')=='deepseek-v4.1-flash' for c in contexts)
assert len(calls)==len(results)==1
call, result = calls[0], results[0]
receipt = json.loads(result['data']['message']['content'][0]['text'])
assert receipt['session_id']==SESSION and receipt['call_id']==call['data']['callId']
assert result['data']['message']['toolCallId']==call['data']['callId']
assert receipt['worker']['worker_boundary_pass'] and receipt['host_sentinel_positive_control']
summary_path = ROOT/'cells'/f'{SESSION}.summary.json'
summary = json.loads(summary_path.read_text('utf-8-sig'))
assert summary['same_session_binding_pass'] and summary['logical_e5_units']==0
catalog_path = ROOT/'cells'/f'catalog-{SESSION}.json'
catalog = json.loads(catalog_path.read_text('utf-8-sig'))
assert [c['name'] for c in catalog['catalog']]==['e5_fixture_square'] and not catalog['reserved_run_code_visible']
spec = {'schema':'e5-zero-unit-canary-freeze-v1','logical_e5_units':0,
        'scope':'restricted Claude Science persona + one integration fixture; not 12-arm E5',
        'harness_version':'0.2.0-rc.2','route':contexts[0],
        'source_session_sha256':sha(source),'session_id':SESSION,
        'preset':'claude-science','preset_variant':'original persona retained; general scoped tools removed',
        'assets':{str(p.relative_to(ROOT)).replace('\\','/'):sha(p)
                  for p in list((ROOT/'public/e5-gate-host').glob('*')) if p.is_file()}}
spec_bytes = (json.dumps(spec,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8')
protocol_hash = hashlib.sha256(spec_bytes).hexdigest()
journal = RunJournal.begin(ROOT/'evidence/gate-journal',run_id='science-canary-v1',
                           protocol_sha256=protocol_hash,expected_keys={('GATE','FIXTURE',1)})
journal.record_artifact('canary-freeze.json',spec_bytes)
sanitized = b''.join((json.dumps(redact(r),ensure_ascii=False)+'\n').encode('utf-8') for r in records)
journal.record_artifact('session.events.redacted.jsonl',sanitized)
for name, path in [('summary.json',summary_path),('catalog.json',catalog_path),
                   ('process.result.json',ROOT/'cells/science-fixture-v1.result.json'),
                   ('process.stderr.txt',ROOT/'cells/science-fixture-v1.stderr.txt'),
                   ('os-identity-proof.json',ROOT/'cells/identity-proof.json')]:
    journal.record_artifact(name,path.read_bytes())
fixture_path = next((ROOT/'cells').glob('fixture-*'))
for path in fixture_path.rglob('*'):
    if path.is_file():
        journal.record_artifact('worker/'+path.relative_to(fixture_path).as_posix(),path.read_bytes())
for path in (ROOT/'public/e5-gate-host').glob('*'):
    if path.is_file():
        journal.record_artifact('plugin/'+path.name,path.read_bytes())
for name in ('fixture_gateway.py','fixture_worker.py'):
    journal.record_artifact('plugin/'+name,(OUT/name).read_bytes())
journal.record({'system':'GATE','item':'FIXTURE','attempt':1,'logical_e5_units':0,
                'session_id':SESSION,'call_id':receipt['call_id'],'receipt_id':receipt['receipt_id'],
                'actual_model_contexts':contexts,'same_session_binding_pass':True,
                'worker_boundary_pass':True,'final_answer':summary['final_answer']})
sealed = journal.seal({'scope':'zero-unit Harness to worker integration gate','logical_e5_units':0,
                       'same_session_binding_pass':True,'confirmatory_go':False})
verified = verify_sealed_run(sealed)
assert verified['ok'],verified
report = {'schema':'e5-zero-unit-seal-verification-v1','logical_e5_units':0,'sealed_dir':str(sealed),
          'session_id':SESSION,'source_session_sha256':sha(source),'source_event_count':len(records)-1,
          'verification':verified,'confirmatory_go':False,'scope':spec['scope']}
(OUT/'science-canary-seal-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
