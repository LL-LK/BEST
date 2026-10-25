"""补采固定澄清第二轮依赖的公开查询；不访问模型和答案键。"""
from pathlib import Path
import json
import sys
import time
sys.path.insert(0,str(Path(__file__).parent))
from recapture_public import WireSession, BestClient, cone, _run_cone, dump_snapshot

OUT=Path(__file__).parent/'public-followup-capture-01'
OUT.mkdir(exist_ok=False)
results=[]
cases=([('C02',cone('scr_galah',120.3,-20.4,5.0))]+
       [(f'C05_{catalog}',cone(catalog,180.0,30.0,60.0)) for catalog in ('scr_galah','scr_lamost','xpsp')])
cases += [('name_M31',{'kind':'name','name':'M31'}),
          ('name_GaiaID',{'kind':'name','name':'Gaia DR3 1234567890123456789'})]
for case,task in cases:
    folder=OUT/case
    folder.mkdir()
    session=WireSession(folder)
    client=BestClient(rate_limit=1.5,max_retries=0,timeout=60)
    client.session.close()
    client.session=session
    meta={'returned_count':0,'page_size':1000}
    error=None
    try:
        if task['kind']=='cone':
            meta.update(_run_cone(client,task))
            if session.bodies:dump_snapshot(folder,task,session,meta)
        else:
            resolved=client.resolve_name(task['name'])
            meta={'name_resolution':resolved.to_dict()}
    except Exception as exc:
        error={'type':type(exc).__name__,'message':str(exc)[:1000]}
    finally:
        client.close()
    receipt={'schema':'e5-public-followup-acquisition-v1','logical_e5_units':0,
             'case_id':case,'task':task,'wire_responses':session.wire,'observed':meta,'error':error}
    (folder/'acquisition.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    results.append({'case_id':case,'observed':meta,'error':error,'responses':len(session.wire)})
    (OUT/'progress.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(results[-1],ensure_ascii=False),flush=True)
(OUT/'COMPLETE.json').write_text(json.dumps({'logical_e5_units':0,'results':results},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
