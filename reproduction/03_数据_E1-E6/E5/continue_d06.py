"""只对已提交的 D06 会话复核 GET；不重试非幂等 POST。"""
from pathlib import Path
import csv
import hashlib
import json
import time
from datetime import datetime, timezone
import requests

OUT = Path(__file__).parent/'public-recapture-01/D06-get-continuation-01'
OUT.mkdir(exist_ok=False)
session = requests.Session()
session.trust_env = False
records = []
base = 'https://nadc.china-vo.org/data/best/sqlid/'
# 此 ID 仅为前次公开查询的服务端 continuation，不是 Harness session 或认证秘密。
urls = [('count',base+'7988/getcount')]+[(f'page_{i:04d}',base+f's7988?output.fmt=csv&rows=1000&page={i}&sort=ps1_ra&order=asc') for i in range(1,4)]
count = None
for role,url in urls:
    if role != 'count' and count is None:
        break
    for attempt in range(1,3):
        started = datetime.now(timezone.utc).isoformat()
        t0=time.monotonic()
        try:
            response=session.get(url,timeout=(15,60))
            file=f'{role}-a{attempt}.bin'
            (OUT/file).write_bytes(response.content)
            record={'role':role,'attempt':attempt,'method':'GET','url':url,'status':response.status_code,
                    'started_at_utc':started,'elapsed_s':time.monotonic()-t0,'response_file':file,
                    'sha256':hashlib.sha256(response.content).hexdigest(),'bytes':len(response.content)}
            if role=='count':
                body=response.json()
                if response.status_code==200 and isinstance(body.get('total'),int):
                    count=body['total']
                    record['verified_total']=count
                else:
                    record['error']='no valid server total'
            else:
                parsed=list(csv.DictReader(response.content.decode('utf-8-sig').splitlines()))
                record['independent_csv_rows']=len(parsed)
                record['columns']=list(parsed[0]) if parsed else []
                if 'ps1_ra' not in record['columns']:
                    record['error']='no ps1 CSV columns'
        except Exception as exc:
            record={'role':role,'attempt':attempt,'method':'GET','url':url,'started_at_utc':started,
                    'elapsed_s':time.monotonic()-t0,'error_type':type(exc).__name__,'error':str(exc)[:1000]}
        records.append(record)
        (OUT/'progress.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(record,ensure_ascii=False),flush=True)
        if not record.get('error'):
            break
        time.sleep(5)
    time.sleep(1.5)
session.close()
(OUT/'COMPLETE.json').write_text(json.dumps({'schema':'e5-public-get-continuation-v1','logical_e5_units':0,
    'post_retried':False,'server_total':count,'records':records,
    'complete_3000_row_material':count is not None and sum(r.get('independent_csv_rows',0) for r in records if not r.get('error'))==3000},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
