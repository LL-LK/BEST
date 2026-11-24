"""生成候选领域 schema、零单元计划与受管理安装输入。"""
from pathlib import Path
import hashlib
import json
import yaml

REPO=Path(r'<REPO_ROOT>')
PUBLIC=Path(r'<WORK_ROOT>\public')
PLUGIN=PUBLIC/'e5-confirmatory-host'
tools=json.loads((REPO/'references/tools.schema.json').read_text('utf-8'))['tools']
schemas=[]
for tool in tools:
    parameters=tool['inputSchema']
    parameters['additionalProperties']=False
    for key,value in parameters.get('properties',{}).items():
        if value.get('type')=='string':value.setdefault('maxLength',200)
        if key=='max_rows':value['maximum']=5000
    schemas.append({'name':tool['name'],'description':tool['description'],'parameters':parameters})
properties={k:v.copy() for k,v in next(s for s in schemas if s['name']=='cone_search')['parameters']['properties'].items() if k not in ('max_rows',)}
properties.update({'radec_text':{'type':'string','maxLength':8192},'default_radius_arcsec':{'type':'number','exclusiveMinimum':0,'maximum':18000}})
raw=[('best_submit','Raw BEST phase-1 form submission over a fixed offline public snapshot backend. Returns sqlid; get count and pages in subsequent calls.',properties,['catalog']),
     ('best_get_count','Raw BEST GET count for a sqlid issued in this session.',{'sqlid':{'type':'string','maxLength':80}},['sqlid']),
     ('best_get_page','Raw BEST GET CSV page for this session sqlid; full CSV is materialized as an artifact, large replies have a marked preview.',{'sqlid':{'type':'string','maxLength':80},'page':{'type':'integer','minimum':1,'maximum':5000},'rows':{'type':'integer','minimum':1,'maximum':5000},'catalog':{'type':'string','maxLength':80},'sort':{'type':'string','maxLength':80},'order':{'type':'string','enum':['asc','desc']}},['sqlid']),
     ('best_metadata','Read public catalog metadata from the production registry.',{'catalog':{'type':'string','maxLength':80}},['catalog']),
     ('best_resolve','Raw BEST name resolution from a frozen public server response.',{'name':{'type':'string','maxLength':200}},['name']),
     ('e5_fixture_square','Zero-unit integration fixture. Square only the permitted value 7 inside the isolated worker.',{'value':{'type':'integer','enum':[7]}},['value'])]
for name,description,properties,required in raw:
    schemas.append({'name':name,'description':description,'parameters':{'type':'object','properties':properties,'required':required,'additionalProperties':False}})
(PLUGIN/'schemas.json').write_text(json.dumps(schemas,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
old=yaml.safe_load((PUBLIC/'e5-gate-host/cordis.patch.yml').read_text('utf-8'))[0]
old['config']['description']='Claude Science mode with E5 finite domain tools and an isolated public-snapshot worker'
patch=[old,{'insert':[{'id':'e5-confirmatory-host','name':'@local/e5-confirmatory-host'},
                     {'id':'e5-confirmatory-driver','name':'@local/e5-confirmatory-host/driver','disabled':True}]}]
(PLUGIN/'cordis.patch.yml').write_text(yaml.safe_dump(patch,allow_unicode=True,sort_keys=False),encoding='utf-8')
definition_hash=hashlib.sha256((PLUGIN/'schemas.json').read_bytes()).hexdigest()
plan={'schema':'e5-zero-unit-domain-gate-plan-v1','scope':'non-E5 integration and catalogue gate only','logical_e5_units':0,
      'protocol_sha256':definition_hash,'concurrency':1,'cells':[
          {'cell_id':'gate-domain-fixture-01','allow':['e5_fixture_square'],'envelope':'structured',
           'prompt':'This is a zero-unit integration fixture, containing no E5 task. Call e5_fixture_square with value 7 exactly once and report the returned value and _e5_evidence.receipt_id in your final answer.'},
          {'cell_id':'gate-domain-atomic-01','allow':[s['name'] for s in schemas[:7]],'envelope':'structured',
           'prompt':'This is a zero-unit catalogue fixture, containing no E5 task. Call list_catalogs exactly once and report the count of publicly registered query catalogs and _e5_evidence.receipt_id in your final answer.'},
          {'cell_id':'gate-domain-empty-01','allow':[],'envelope':'structured',
           'prompt':'This is a zero-unit empty-catalogue fixture. State that no tools are available in this session. Do not claim you ran a tool.'}]}
(PUBLIC/'domain-gate-plan-01.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(PUBLIC/'domain-gate-run.patch.yml').write_text("- id: e5-headless-runner\n  disabled: true\n- id: e5-gate-host\n  disabled: true\n- id: e5-confirmatory-driver\n  disabled: false\n  config:\n    planFile: D:/E5-v4-20261012-02/public/domain-gate-plan-01.json\n",encoding='utf-8')
prompt="Use the real plugin_manager now. Install local bundle @local/e5-confirmatory-host from D:/E5-v4-20261012-02/public/e5-confirmatory-host in this isolated profile. Disable include:e5-gate-host, keep include:e5-science-gate-driver and include:e5-confirmatory-driver disabled, and enable include:e5-confirmatory-host. Inspect and report each actual manager receipt including application status. This is a zero-unit management operation authorized by the user; do not run an E5 question or simulate a receipt."
(PUBLIC/'install-domain-host.prompt.txt').write_text(prompt,encoding='utf-8')
print(json.dumps({'schemas':len(schemas),'definition_hash':definition_hash,'gate_only':True}))
