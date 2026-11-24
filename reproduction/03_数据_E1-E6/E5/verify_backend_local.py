"""以新公开采集结果核验生产 ToolBox 接线与查询绑定负对照。"""
from pathlib import Path
import hashlib
import json
import sys
sys.path.insert(0,str(Path(__file__).parent))
sys.path.insert(0,r'<REPO_ROOT>')
from frozen_backend import invoke

ROOT=Path(r'<WORK_ROOT>\public\e5-candidate-02')
bundle=json.loads((ROOT/'data/bundle.json').read_text('utf-8'))
checks=[]
queries=[(5,1000,3,3),(60,1000,174,174),(300,1000,5109,1000),(1800,1,215774,1),(18000,3000,19904142,3000)]
state={}
for radius,cap,total,returned in queries:
    result,state,log=invoke(bundle,state,'gate-local-positive','cone_search',{'ra':180.0,'dec':30.0,'radius_arcsec':radius,'catalog':'ps1','max_rows':cap})
    observed={'ok':result['status']['ok'],'total':result['data'].get('total_count'),'returned':result['data'].get('returned_count')}
    checks.append({'name':f'cone_{radius}_bound_to_public_response','pass':observed=={'ok':True,'total':total,'returned':returned},'observed':observed,'logical_transport_requests':result['cost']['http_requests'],'transport_log_records':len(log)})
    assert checks[-1]['pass'],checks[-1]
sqlid=result['provenance']['session_id']
count,state,log=invoke(bundle,state,'gate-local-positive','count',{'sqlid':sqlid})
checks.append({'name':'same_session_count_receipt','pass':count['data']['total']==19904142})
try:
    invoke(bundle,{},'gate-local-other','count',{'sqlid':sqlid})
    denied=False
except PermissionError:
    denied=True
checks.append({'name':'foreign_handle_denied_before_SUT','pass':denied})
wrong,_,_=invoke(bundle,{},'gate-local-wrong','cone_search',{'ra':180,'dec':-30,'radius_arcsec':5,'catalog':'ps1'})
checks.append({'name':'wrong_sky_rejected_without_anchor_fallback','pass':not wrong['status']['ok']})
invalid,_,_=invoke(bundle,{},'gate-local-invalid','cone_search',{'ra':180,'dec':0,'radius_arcsec':0,'catalog':'ps1'})
checks.append({'name':'invalid_radius_rejected','pass':invalid['status']['error_code']=='E_INVALID_INPUT'})
cross,_,_=invoke(bundle,{},'gate-local-cross','crossmatch_batch',{'coords':[{'ra':ra,'dec':dec} for ra,dec in [(180,-30),(180.5,-30.5),(181,-31),(185,-35),(182,-32)]], 'catalog':'ps1','radius_arcsec':5,'nearest_only':True,'max_rows':5000})
checks.append({'name':'five_original_inputs_bound_to_public_proximity','pass':cross['status']['ok'] and cross['data']['returned_count']==1,'status':cross['status'],'data_keys':list(cross['data'])})
for catalog,ra,dec,radius,total in [('ps1',180,0,60,222),('scr_galah',120.3,-20.4,5,0),('scr_galah',180,30,60,0),('scr_lamost',180,30,60,0),('xpsp',180,30,60,0)]:
    result,_,_=invoke(bundle,{},'gate-local-'+catalog,'cone_search',{'ra':ra,'dec':dec,'radius_arcsec':radius,'catalog':catalog})
    checks.append({'name':'fixed_followup_or_pagination_'+catalog+str(dec),'pass':result['status']['ok'] and result['data']['total_count']==total})
result,_,_=invoke(bundle,{},'gate-local-alias','cone_search',{'ra':180,'dec':30,'radius_arcsec':60,'catalog':'ps1','sort':'ps1.rpsf','order':'asc','columns':['ra','dec','rpsf']})
checks.append({'name':'public_column_aliases_preserved','pass':result['status']['ok'] and result['data']['returned_count']==174})
assert all(c['pass'] for c in checks),checks
report={'schema':'e5-local-production-backend-gate-v1','logical_e5_units':0,'checks':checks,'all_pass':True,
        'scope':'local production ToolBox + recorded public transport, not Harness integration',
        'backend_sha256':hashlib.sha256((Path(__file__).parent/'frozen_backend.py').read_bytes()).hexdigest()}
(Path(__file__).parent/'backend-local-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
