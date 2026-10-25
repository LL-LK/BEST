"""补齐 count-first 查询的有限公共样本供所有臂共用；不重新 POST。"""
from pathlib import Path
import csv
import hashlib
import json
import time
import requests

out=Path(__file__).parent/'public-recapture-01/D05-pages-continuation-01'
out.mkdir(exist_ok=False)
session=requests.Session()
session.trust_env=False
records=[]
for page in range(1,6):
    url=f'https://nadc.china-vo.org/data/best/sqlid/s7987?output.fmt=csv&rows=1000&page={page}&sort=ps1_ra&order=asc'
    response=session.get(url,timeout=(15,60))
    response.raise_for_status()
    name=f'page_{page:04d}.bin'
    (out/name).write_bytes(response.content)
    rows=list(csv.DictReader(response.content.decode('utf-8-sig').splitlines()))
    if len(rows)!=1000 or 'ps1_ra' not in rows[0]:raise RuntimeError('incomplete ps1 CSV')
    records.append({'page':page,'url':url,'method':'GET','status':response.status_code,'response_file':name,
                    'bytes':len(response.content),'sha256':hashlib.sha256(response.content).hexdigest(),'rows':len(rows)})
    (out/'progress.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(records[-1]),flush=True)
    time.sleep(1.5)
session.close()
(out/'COMPLETE.json').write_text(json.dumps({'logical_e5_units':0,'post_retried':False,'records':records},indent=2)+'\n',encoding='utf-8')
