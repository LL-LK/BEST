"""公开快照整理与 SUT/依赖只读部署素材；不复制 scorer 或任务答案键。"""
from pathlib import Path
import csv
import hashlib
import importlib
import io
import json
import shutil
import zipfile

HERE=Path(__file__).parent
REPO=Path(r'<REPO_ROOT>')
OUT=Path(r'<WORK_ROOT>\public\e5-candidate-02')
OUT.mkdir(exist_ok=False)
ROOT=HERE/'public-recapture-01'
FOLLOWUP=HERE/'public-followup-capture-01'

def read(path):return json.loads(path.read_text('utf-8-sig'))
def rows(paths):
    records=[]
    for path in paths:
        records.extend(csv.DictReader(io.StringIO(path.read_bytes().decode('utf-8-sig'))))
    return records
def standard(folder,extra=(),replace_pages=False):
    capture=read(folder/'acquisition.json')
    files=list(extra) if replace_pages else list(sorted((folder/'pages').glob('*.csv')))+list(extra)
    data=rows(files)
    total=json.loads((folder/'count.json').read_bytes().decode('utf-8-sig'))['total']
    task=capture['task']
    query={k:task[k] for k in ('kind','catalog','ra','dec','radius','points','nearest_only') if k in task}
    query['sort']=task.get('sort','ps1_ra' if task['catalog']=='ps1' else None)
    query['order']=task.get('order','asc')
    columns=next(csv.reader(io.StringIO(files[0].read_bytes().decode('utf-8-sig')))) if files else []
    return {'query':query,'total_count':total,'rows':data,'columns':columns,'complete':len(data)==total,
            'public_sources':[{ 'file_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
                               'bytes':p.stat().st_size} for p in files]}

queries=[]
queries.append(standard(ROOT/'D01_D10_D11_D12'))
queries.append(standard(ROOT/'D02'))
queries.append(standard(ROOT/'D03',sorted((ROOT/'D03-pages-continuation-01').glob('page_*.bin'))))
queries.append(standard(ROOT/'D04_unfiltered'))
queries.append(standard(ROOT/'D05_count_first',sorted((ROOT/'D05-pages-continuation-01').glob('page_*.bin')),True))
continuation=ROOT/'D06-get-continuation-01'
completion=read(continuation/'COMPLETE.json')
assert completion['complete_3000_row_material']
d06files=[continuation/r['response_file'] for r in completion['records'] if r['role'].startswith('page') and not r.get('error')]
queries.append({'query':{'kind':'cone','catalog':'ps1','ra':180.0,'dec':30.0,'radius':18000.0,'sort':'ps1_ra','order':'asc'},
                'total_count':completion['server_total'],'rows':rows(d06files),'columns':list(rows(d06files)[0]),'complete':False,
                'public_sources':[{'file_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in d06files]})
queries.append(standard(ROOT/'D07'))
queries.append(standard(ROOT/'D09'))
for name in ('C02','C05_scr_galah','C05_scr_lamost','C05_xpsp'):
    queries.append(standard(FOLLOWUP/name))
names={}
for folder in ('name_M31','name_GaiaID'):
    capture=read(FOLLOWUP/folder/'acquisition.json')
    response=next(r for r in capture['wire_responses'] if r['status']==200)
    path=FOLLOWUP/folder/response['response_file']
    names[capture['task']['name']]={'response':json.loads(path.read_bytes().decode('utf-8-sig')),
                                  'response_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
for query in queries:
    query['query_id']=hashlib.sha256(json.dumps(query['query'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    query['rows_sha256']=hashlib.sha256(json.dumps(query['rows'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert len(query['rows'])==len({json.dumps(row,sort_keys=True) for row in query['rows']}),'duplicate public rows'
bundle={'schema':'e5-public-fixed-data-v1','queries':queries,'names':names,
        'source':'recorded public BEST HTTP response entity bytes, 2026-10-12',
        'coverage':'complete small cones; bounded ascending-RA large cones; no fabricated rows or totals'}
(OUT/'data').mkdir()
(OUT/'data/bundle.json').write_text(json.dumps(bundle,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
# A worker receives production source only; no evals, scorer, history, credentials or tasks.
(OUT/'runtime').mkdir()
shutil.copytree(REPO/'src',OUT/'runtime/src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
(OUT/'runtime/vendor').mkdir()
dependencies=[]
for package in ('requests','urllib3','certifi','charset_normalizer','idna','yaml'):
    module=importlib.import_module(package)
    origin=Path(module.__file__).parent
    shutil.copytree(origin,OUT/'runtime/vendor'/package,
                    ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pyd','*.so'))
    dependencies.append({'name':package,'version':getattr(module,'__version__',None)})
manifest={'schema':'e5-public-runtime-candidate-v1','logical_e5_units':0,'frozen_for_confirmatory':False,
          'dependencies':dependencies,'queries':[{'query_id':q['query_id'],'query':q['query'],
          'total_count':q['total_count'],'stored_rows':len(q['rows']),'complete':q['complete']} for q in queries],
          'files':{p.relative_to(OUT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in OUT.rglob('*') if p.is_file()}}
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
with zipfile.ZipFile(OUT/'runtime-and-data.zip','x',compression=zipfile.ZIP_DEFLATED) as archive:
    for root in (OUT/'runtime',OUT/'data'):
        for path in root.rglob('*'):
            if path.is_file():archive.write(path,path.relative_to(OUT).as_posix())
(HERE/'public-bundle-candidate.json').write_text(json.dumps({'path':str(OUT),'manifest_sha256':hashlib.sha256((OUT/'manifest.json').read_bytes()).hexdigest(),
    'zip_sha256':hashlib.sha256((OUT/'runtime-and-data.zip').read_bytes()).hexdigest(),'query_count':len(queries),'dependencies':dependencies,
    'logical_e5_units':0,'frozen_for_confirmatory':False},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'query_count':len(queries),'total_stored_rows':sum(len(q['rows']) for q in queries),'out':str(OUT)},ensure_ascii=False))
