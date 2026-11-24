"""Portable integrity check and separate reproduction of the accepted E2 inputs."""
from pathlib import Path
import argparse, hashlib, json, sys, uuid

HERE=Path(__file__).resolve().parent
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--verify-only',action='store_true');p.add_argument('--output',type=Path);args=p.parse_args()
    root=HERE/'accepted_run';pre=json.loads((root/'preregistration.json').read_text('utf-8'))
    for key,folder in [('scenario_manifest','scenarios'),('gold_manifest','gold'),('snapshot_manifest','snapshots')]:
        assert all(sha(root/folder/name)==value for name,value in pre[key].items()),key
    mapping=json.loads((HERE/'frozen-code-map.json').read_text('utf-8'))
    assert set(mapping)==set(pre['code_hashes'])
    assert all(sha(HERE/mapping[name])==value for name,value in pre['code_hashes'].items())
    sys.path.insert(0,str(HERE/'code'))
    from evals.groundtruth.verify_independent import verify_all
    independent=verify_all(gold_dir=root/'gold',scenarios_dir=root/'scenarios',snapshots_root=root/'snapshots')
    assert independent['pass'] and independent['n_pass']==21
    if args.verify_only:
        print(json.dumps({'frozen_inputs_verified':True,'frozen_code_verified':True,'independent_gold_cases':21}));return
    from evals.groundtruth import frozen_runner
    frozen_runner.SNAPSHOTS_DIR=root/'snapshots';frozen_runner.GOLD_DIR=root/'gold';frozen_runner.SCENARIOS_DIR=root/'scenarios'
    out=args.output or HERE/'reproduction_outputs'/('check-'+uuid.uuid4().hex)
    out.mkdir(parents=True,exist_ok=False)
    result=frozen_runner.run(root/'scenarios',repeat=3)
    trace=result['trace_events'];assert len(trace)==len({(r['case_id'],r['repeat_index']) for r in trace})==63
    assert result['pass'] and result['n_pass']==result['n_cases']==21
    accepted=[json.loads(line) for line in (root/'trace.jsonl').read_text('utf-8').splitlines()]
    # Expected-error cases have no row hash: compare their error receipt too.
    observed={(r['case_id'],r['repeat_index']):r for r in trace}
    expected={(r['case_id'],r['repeat_index']):{k:v for k,v in r.items() if k!='run_id'} for r in accepted}
    assert observed==expected, 'reproduced requests, row hashes, envelopes or error receipts differ'
    result.update(reproduction_validation_only=True,accepted_run_unchanged=pre['run_id'],units=63,independent_gold_verified=True)
    (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'reproduction_validation_only':True,'units':63,'cases_passed':21,'accepted_full_trace_matches':True,'output':str(out)}))

if __name__=='__main__': main()
