"""Validate the public E5 archive and exact original RunJournal artifacts."""
from pathlib import Path
import argparse, hashlib, json, zipfile

PUBLIC_ZIP_SHA = '729ee85f7d97eb8dd3a575c7e253a405a426a9bd6c322f19d9285ce3ca88164c'
SCORES_SHA = '2a030fb9e6f5a362a2f5dc485e01c5b1e5ece8ef6ab1735596dff9ca6da75a5c'


def verify_public_archive(path, archive):
    """Verify the published, projected archive against its sealed reference bytes."""
    with path.open('rb') as handle:
        if hashlib.file_digest(handle, 'sha256').hexdigest() != PUBLIC_ZIP_SHA:
            raise ValueError('Published E5 ZIP checksum differs from its reference')
    published_scores = archive.read('results/scores.json')
    if hashlib.sha256(published_scores).hexdigest() != SCORES_SHA:
        raise ValueError('Published E5 score bytes differ from the original score ledger')
    rows = json.loads(published_scores)
    if len(rows) != 2016 or len({(r['arm'], r['task'], r['replicate']) for r in rows}) != 2016:
        raise ValueError('Expected 2,016 unique E5 scores')
    print(json.dumps({'archive_hash_verified': True, 'score_ledger_verified': True, 'unique_scores': 2016}))


def main():
    p=argparse.ArgumentParser();p.add_argument('archive',type=Path);args=p.parse_args()
    with zipfile.ZipFile(args.archive) as z:
        names=z.namelist();assert len(names)==len(set(names))
        if 'E5/MANIFEST.sha256.json' not in names:
            return verify_public_archive(args.archive, z)
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
