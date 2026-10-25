from pathlib import Path
import hashlib
import json
import yaml

REPO=Path(r'<REPO_ROOT>')
OUT=Path(__file__).parent
items_path=REPO/'evals/ablation/items.yaml'
items=yaml.safe_load(items_path.read_text(encoding='utf-8-sig'))['items']
issues=[]
for item in items:
    gold=item.get('gold_result') or {}
    reference=gold.get('ref')
    if not reference or not reference.endswith('.json'):
        continue
    path=REPO/reference
    if not path.is_file():
        issues.append({'item':item['id'],'kind':'missing_canonical_gold_reference','path':reference})
        continue
    canonical=json.loads(path.read_text(encoding='utf-8-sig'))
    mismatch=[]
    for field in ['row_count','row_keys']:
        if field in gold and field in canonical and gold[field]!=canonical[field]:
            mismatch.append(field)
    if mismatch:
        issues.append({'item':item['id'],'kind':'embedded_gold_differs_from_current_canonical','fields':mismatch,'canonical_reference':reference,'canonical_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'answer_values_exported':False})
systems=[]
for path in sorted((REPO/'evals/ablation/systems').glob('*.yaml')):
    system=yaml.safe_load(path.read_text(encoding='utf-8-sig'))['system']
    systems.append({'id':system['id'],'llm_mode':(system.get('llm') or {}).get('mode'),'tool_face':system.get('tool_face'),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
report={
    'schema':'e5-confirmatory-asset-preflight-v4',
    'logical_e5_units':0,
    'task_count':len(items),'arm_count':len(systems),'planned_units':len(items)*len(systems)*3,
    'source_items_sha256':hashlib.sha256(items_path.read_bytes()).hexdigest(),
    'missing_decision_class':[item['id'] for item in items if not item.get('decision_class')],
    'gold_reference_issues':issues,
    'systems':systems,
    'statistics_conflicts':[
        {'asset':'evals/ablation/metrics/stats.py','existing':'3 repeats -> majority-vote task Boolean','required':'3 repeats -> within-arm task success proportion, then task-paired difference'},
        {'asset':'evals/ablation/metrics/stats.py','existing':'MAIN_FAMILY = B0/B1/B2b/A1-A5','required':'primary B3-B2b; one Holm family A1-A6 vs B3; separate A2-sham length control'},
    ],
    'confirmatory_go':False,
    'reason':'Existing assets remain historical/scripted and statistically incompatible; independent live cell exporter, frozen arm prompts/schema, gold/rubric repairs and confirmatory analysis are not sealed. Human review is post-run and does not block this status.',
}
with (OUT/'confirmatory-assets-preflight.json').open('x',encoding='utf-8') as stream:
    json.dump(report,stream,ensure_ascii=False,indent=2)
print(json.dumps({k:report[k] for k in ['task_count','arm_count','planned_units','gold_reference_issues','statistics_conflicts','confirmatory_go']},ensure_ascii=False,indent=2))
