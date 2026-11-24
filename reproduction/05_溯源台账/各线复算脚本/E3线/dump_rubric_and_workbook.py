# -*- coding: utf-8 -*-
"""提取冻结量表(rubric)与匿名审核表数据行结构，供重建盲评包使用。只读。"""
from pathlib import Path
import json, io, sys
import openpyxl

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
E3 = Path(r'<WORKSPACE>\04_实验数据\E3_科学忠实性\实验产物')
ARC = E3 / '05_原始实验归档'
DIAG = Path(r'<WORKSPACE>\11_投稿包\_work\E1E2E3\_work_diag')
out = {}

bundle = json.loads((ARC / 'bundle.json').read_text('utf-8-sig'))
rub = bundle['rubric']
print('rubric keys:', list(rub.keys()))
for k, v in rub.items():
    if isinstance(v, (str, int, float)):
        print(f'\n--- {k} ({type(v).__name__}, len={len(str(v))}) ---')
        print(str(v)[:900])
    elif isinstance(v, list):
        print(f'\n--- {k} (list n={len(v)}) ---')
        print(json.dumps(v[:3], ensure_ascii=False)[:900])
    else:
        print(f'\n--- {k} (dict keys={list(v.keys())[:14]}) ---')
        print(json.dumps(v, ensure_ascii=False)[:900])
out['rubric'] = rub

# item 结构
it = bundle['items'][0]
print('\n=== item 结构 ===')
print(json.dumps({k: (str(v)[:160]) for k, v in it.items()}, ensure_ascii=False, indent=1))
out['item_example'] = it

wb = openpyxl.load_workbook(E3 / '04_匿名审核材料' / 'E3-全量匿名审核表.xlsx', data_only=False)
ws = wb['审核总表']
print('\n=== 审核总表 第6行完整表头 ===')
hdr = [(c.coordinate, c.value) for c in ws[6] if c.value is not None]
for co, v in hdr:
    print(f'  {co}: {v}')
out['audit_header_row6'] = hdr

print('\n=== 审核总表 数据行 7 (前若干列) ===')
for c in ws[7]:
    if c.value is not None:
        print(f'  {c.coordinate}: {str(c.value)[:150]}')
out['audit_row7'] = [(c.coordinate, str(c.value)) for c in ws[7] if c.value is not None]

ws2 = wb['题目与回答']
print('\n=== 题目与回答 前12行(匿名编号/内容类型/段号) ===')
for r in range(6, 20):
    vals = [(c.coordinate, str(c.value)[:60]) for c in ws2[r] if c.value is not None]
    print('  ', vals)

ws3 = wb['填写说明']
print('\n=== 填写说明 全表 ===')
for r in range(1, ws3.max_row + 1):
    vals = [(c.coordinate, str(c.value)[:300]) for c in ws3[r] if c.value is not None]
    if vals:
        print('  ', vals)
out['instructions_sheet'] = [[(c.coordinate, str(c.value)) for c in ws3[r] if c.value is not None]
                             for r in range(1, ws3.max_row + 1)]

ws4 = wb['逐项判定']
print('\n=== 逐项判定 数据行 7 ===')
for c in ws4[7]:
    if c.value is not None:
        print(f'  {c.coordinate}: {str(c.value)[:200]}')
out['per_item_row7'] = [(c.coordinate, str(c.value)) for c in ws4[7] if c.value is not None]

(DIAG / 'e3_rubric_and_workbook_dump.json').write_text(
    json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding='utf8')
print('\n->', DIAG / 'e3_rubric_and_workbook_dump.json')
