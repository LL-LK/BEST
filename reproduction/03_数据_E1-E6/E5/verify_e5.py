"""Validate the public E5 archive and exact original RunJournal artifacts."""
from pathlib import Path
import argparse, hashlib, json, zipfile

def main():
    p=argparse.ArgumentParser();p.add_argument('archive',type=Path);args=p.parse_args()
    with zipfile.ZipFile(args.archive) as z:
        names=z.namelist();assert len(names)==len(set(names))
        manifest=json.loads(z.read('E5/MANIFEST.sha256.json'))
        assert set(names)==set(manifest)|{'E5/MANIFEST.sha256.json'}
        actual={name:hashlib.sha256(z.read(name)).hexdigest() for name in manifest}
        assert actual==manifest
        prefix='E5/audit/sealed_journal/confirmatory-v51-packed/'
        seal=json.loads(z.read(prefix+'SEALED.json'))
        assert seal['expected_cells']==len(seal['trace_hashes'])==2016
        for section in ('trace_hashes','artifact_hashes'):
            assert all(actual[prefix+name]==value.removeprefix('sha256:') for name,value in seal[section].items())
        assert actual[prefix+'REPORT.json']==seal['report_sha256'].removeprefix('sha256:')
        traces=[json.loads(z.read(prefix+n)) for n in seal['trace_hashes']]
        assert len({r['session_id'] for r in traces})==len({(r['system'],r['item'],r['attempt']) for r in traces})==2016
        assert all(r['origin']=='harness-live-confirmatory-v5' for r in traces)
        rows=json.loads(z.read('E5/results/scores.json'))
        assert len(rows)==2016 and {r['session_id'] for r in rows}=={r['session_id'] for r in traces}
        assert not any(n.endswith(('gold.json','.clixml','.credentials.yaml')) or '/profile/' in n for n in names)
    print(json.dumps({'archive_hashes_verified':True,'original_run_journal_verified':True,'unique_live_sessions':2016,'private_gold_absent':True}))

if __name__=='__main__':main()
