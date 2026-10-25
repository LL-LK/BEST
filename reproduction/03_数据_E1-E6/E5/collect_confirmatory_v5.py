"""作者身份即时收集真实会话；封存完整矩阵之前不评分，也不补跑。"""
from pathlib import Path
import hashlib,json,sys,time,shutil
import zstandard
ROOT=Path(r'<WORK_ROOT>')
sys.path.insert(0,r'<REPO_ROOT>')
from evals.ablation.iso.sealed_run import RunJournal,verify_sealed_run

def load(path):return json.loads(path.read_text('utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    public=ROOT/'public/confirmatory-v5';freeze=load(ROOT/'private/confirmatory-v5/freeze.json')
    schedule=load(public/'schedule.json');mapping=load(ROOT/'private/confirmatory-v5/schedule-map.json')['task_map']
    expected={(j['arm'],mapping[j['task_id']]+'-r'+str(j['replicate']),1) for j in schedule}
    journal=RunJournal.begin(ROOT/'evidence/formal-journal',run_id='confirmatory-v5',protocol_sha256=freeze['protocol_sha256'],expected_keys=expected)
    mirror=ROOT/'evidence/confirmatory-v5-stage';mirror.mkdir(exist_ok=False);(mirror/'cells').mkdir()
    journal.record_artifact('freeze-public.json',(public/'freeze-public.json').read_bytes())
    for name in ('tasks.json','arms.json','schedule.json','protocol.md'):
        journal.record_artifact('preregistration/'+name,(public/name).read_bytes())
    (ROOT/'evidence/collector-READY-v5.json').write_text(json.dumps({'protocol_sha256':freeze['protocol_sha256'],'expected':2016,'identity':'author collector'}),encoding='utf-8')
    recorded=set()
    while True:
        for job in schedule:
            if job['cell_id'] in recorded:continue
            source=ROOT/'cells/domain-runs'/job['cell_id']
            if not (source/'DONE.json').exists():continue
            summary=load(source/'summary.json')
            assert summary['cell_id']==job['cell_id'] and summary['protocol_sha256']==freeze['protocol_sha256']
            assert all(summary[k]==job[k] for k in ('task_id','arm','replicate'))
            actual=ROOT/'profile/sessions'/('--D-E5-v4-20261012-02-cells-domain-runs-'+job['cell_id']+'--')/summary['session_id']/'session.v4.jsonl.zstd'
            if not actual.exists():raise ValueError('source session missing; refuse surrogate trace')
            with actual.open('rb') as f:original=zstandard.ZstdDecompressor().stream_reader(f).read()
            events=[json.loads(line) for line in original.splitlines()]
            exported=[json.loads(line) for line in (source/'session.events.redacted.jsonl').read_text('utf-8').splitlines()]
            assert len(events)==len(exported) and [e.get('type') for e in events[1:]]==[e.get('type') for e in exported[1:]]
            assert all(events[0].get(k)==exported[0].get(k) for k in ('id','version','cwd','agentPreset','isSeeded'))
            # Calls and tool results must match the source byte-for-byte semantically; no reenactment.
            for original_event,visible_event in zip(events,exported):
                if original_event.get('type') in ('tool/call','tool/result','request/context','turn/end'):
                    assert original_event==visible_event,'source/export evidence mismatch'
            target=mirror/'cells'/job['cell_id'];target.mkdir()
            source_receipt={'session_id':summary['session_id'],'compressed_source_sha256':sha(actual),'source_event_count':len(events)-1,'hidden_reasoning_not_exported':True}
            for p in source.rglob('*'):
                if p.is_symlink():raise ValueError('reparse artifact')
                if p.is_file():
                    relative=p.relative_to(source);destination=target/relative;destination.parent.mkdir(parents=True,exist_ok=True)
                    with destination.open('xb') as f:f.write(p.read_bytes())
                    journal.record_artifact('cells/'+job['cell_id']+'/'+relative.as_posix(),destination.read_bytes())
            (target/'source-session-hash.json').write_text(json.dumps(source_receipt),encoding='utf-8')
            journal.record_artifact('cells/'+job['cell_id']+'/source-session-hash.json',(target/'source-session-hash.json').read_bytes())
            journal.record({'system':job['arm'],'item':mapping[job['task_id']]+'-r'+str(job['replicate']),'attempt':1,
                            'origin':'harness-live-confirmatory-v5','logical_e5_units':1,'cell_id':job['cell_id'],
                            'session_id':summary['session_id'],'source_session_sha256':source_receipt['compressed_source_sha256'],
                            'error':summary.get('error'),'terminal_failure_retained':not summary['all_turns_completed']})
            recorded.add(job['cell_id'])
            progress={'recorded':len(recorded),'expected':2016,'last_cell':job['cell_id'],'updated_at':time.time(),'status':'INCOMPLETE'}
            (ROOT/'evidence/confirmatory-progress-v5.json').write_text(json.dumps(progress),encoding='utf-8')
        end=ROOT/'cells/domain-runs/FORMAL-END-v5.json'
        if end.exists():
            marker=load(end)
            if not marker['complete'] or len(recorded)!=2016:
                (ROOT/'evidence/confirmatory-INCOMPLETE-v5.json').write_text(json.dumps({'recorded':len(recorded),'expected':2016,'end':marker,'no_addback':True},indent=2),encoding='utf-8');return
            break
        time.sleep(2)
    hashes={p.relative_to(mirror).as_posix():sha(p) for p in mirror.rglob('*') if p.is_file()}
    (mirror/'artifact-hashes.json').write_text(json.dumps(hashes,sort_keys=True,indent=2),encoding='utf-8')
    journal.record_artifact('artifact-hashes.json',(mirror/'artifact-hashes.json').read_bytes())
    sealed=journal.seal({'logical_e5_units':2016,'coverage':'56x12x3','no_addback':True,'scoring_not_started':True})
    verification=verify_sealed_run(sealed);assert verification['ok'],verification
    complete={'protocol_sha256':freeze['protocol_sha256'],'logical_e5_units':2016,'run_journal_sealed':str(sealed),'verification':verification,'scoring_not_started':True}
    (mirror/'SEALED-COMPLETE.json').write_text(json.dumps(complete,indent=2),encoding='utf-8')
    destination=ROOT/'evidence/confirmatory-v5-sealed';mirror.rename(destination)
    (ROOT/'evidence/collector-COMPLETE-v5.json').write_text(json.dumps({'sealed_input':str(destination),'verification':verification},indent=2),encoding='utf-8')
    print(json.dumps(complete))

if __name__=='__main__':main()
