# -*- coding: utf-8 -*-
"""盲评包 xlsx 交付前自检。"""
from pathlib import Path
import json, io, sys, zipfile, re, collections
import openpyxl

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
P = Path(r'<WORKSPACE>\11_投稿包\_work\E1E2E3\盲评包\BEST_E3_专家盲评工作簿_v1.xlsx')
SRC = Path(r'<WORKSPACE>\04_实验数据\E3_科学忠实性\实验产物\04_匿名审核材料\E3-全量匿名审核表.xlsx')

ok = True
res = {}

with zipfile.ZipFile(P) as z:
    names = z.namelist()
    ref = {}
    for n in names:
        if n.endswith('.xml'):
            raw = z.read(n).decode('utf8', 'replace')
            c = raw.count('#REF!')
            if c:
                ref[n] = c
    res['ref_error_total'] = sum(ref.values())
    res['ref_error_by_xml'] = ref
    res['calcChain_present'] = 'xl/calcChain.xml' in names
    wbx = z.read('xl/workbook.xml').decode('utf8', 'replace')
    m = re.search(r'<calcPr[^>]*/>', wbx)
    res['calcPr'] = m.group(0) if m else None
print('1) #REF! 总数 =', res['ref_error_total'], res['ref_error_by_xml'])
print('   calcChain =', res['calcChain_present'], '| calcPr =', res['calcPr'])
ok &= res['ref_error_total'] == 0

wb = openpyxl.load_workbook(P, data_only=False)
res['sheets'] = wb.sheetnames
print('2) 工作表:', wb.sheetnames)

# 跨表引用
names_set = set(wb.sheetnames)
dang = collections.Counter()
formula_n = 0
for ws in wb.worksheets:
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, str) and c.value.startswith('='):
                formula_n += 1
                for m2 in re.finditer(r"'([^']+)'!", c.value):
                    if m2.group(1) not in names_set:
                        dang[m2.group(1)] += 1
res['formula_total'] = formula_n
res['dangling'] = dict(dang)
print(f'3) 公式总数={formula_n}  悬空跨表引用={dict(dang)}')
ok &= len(dang) == 0

# 超链接
tot = bad = 0
for ws in wb.worksheets:
    for row in ws.iter_rows():
        for c in row:
            if c.hyperlink:
                tot += 1
                loc = getattr(c.hyperlink, 'location', None)
                tgt = getattr(c.hyperlink, 'target', None)
                if loc and loc.split('!')[0].strip("'") not in names_set:
                    bad += 1
                elif not loc and not tgt:
                    bad += 1
res['hyperlinks'] = tot
res['hyperlinks_bad'] = bad
print(f'4) 超链接={tot} 无效={bad}')
ok &= bad == 0

# 待填栏是否全空
must_empty = {
    '审核总表': ['G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'T', 'U', 'V'],
    '逐项判定': ['H', 'I', 'J', 'K', 'L', 'N', 'O', 'P', 'Q'],
    '数值登记': ['D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'N', 'O', 'P', 'Q'],
    '主张登记': ['D', 'E', 'F', 'G', 'H', 'I', 'K', 'L', 'M', 'N'],
}
viol = []
for sn, cols in must_empty.items():
    ws = wb[sn]
    for col in cols:
        for r in range(7, ws.max_row + 1):
            v = ws[f'{col}{r}'].value
            if v is not None and not (isinstance(v, str) and v.startswith('=')):
                viol.append((sn, f'{col}{r}', str(v)[:40]))
print(f'5) 待填栏非空单元格 = {len(viol)}  {viol[:5]}')
ok &= len(viol) == 0

# 新表空白性
for sn in ['01_评阅人登记', '02_仲裁记录']:
    ws = wb[sn]
    n = 0
    for r in range(7, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            v = ws.cell(row=r, column=c).value
            if v is not None:
                n += 1
    print(f'   [{sn}] 第7行起非空单元格 = {n}')
    res[sn + '_nonempty'] = n

# 数据校验保留
for sn in wb.sheetnames:
    ws = wb[sn]
    dvs = len(ws.data_validations.dataValidation)
    if dvs:
        print(f'6) [{sn}] 数据校验 {dvs} 条')

# 与基底的内容一致性：冻结文本逐字未改
src = openpyxl.load_workbook(SRC, data_only=False)
frozen_sheets = ['题目与回答', '参考材料', '填写说明']
diff = 0
for sn in frozen_sheets:
    a, b = src[sn], wb[sn]
    if a.max_row != b.max_row or a.max_column != b.max_column:
        diff += 1
        print(f'   [{sn}] 尺寸变化 {a.max_row}x{a.max_column} -> {b.max_row}x{b.max_column}')
        continue
    for r in range(1, a.max_row + 1):
        for c in range(1, a.max_column + 1):
            if a.cell(row=r, column=c).value != b.cell(row=r, column=c).value:
                diff += 1
                if diff < 5:
                    print(f'   [{sn}] {a.cell(row=r, column=c).coordinate} 变了')
print(f'7) 冻结只读表(题目与回答/参考材料/填写说明)与基底差异单元格 = {diff}')
ok &= diff == 0

# 逐项判定/数值登记/主张登记 的冻结列(A..G / A..H / A..F)与公式未改
# 有意的 6 处表头文字明确化（白名单），其余差异视为违规
ALLOWED = {('逐项判定', 'J6'), ('数值登记', 'I6'), ('主张登记', 'G6'),
           ('审核总表', 'M6'), ('审核总表', 'N6')}
for sn, upto in [('逐项判定', 9), ('数值登记', 13), ('主张登记', 10)]:
    a, b = src[sn], wb[sn]
    d = 0
    unexpected = 0
    for r in range(1, a.max_row + 1):
        for c in range(1, upto + 1):
            av, bv = a.cell(row=r, column=c).value, b.cell(row=r, column=c).value
            if av != bv:
                d += 1
                coord = a.cell(row=r, column=c).coordinate
                if (sn, coord) in ALLOWED:
                    continue
                unexpected += 1
                if unexpected <= 3:
                    print(f'   [{sn}] 意外差异 {coord}: {str(av)[:40]} -> {str(bv)[:40]}')
    print(f'8) [{sn}] 原 A..{upto} 列差异 = {d}（其中有意表头 {d-unexpected}，意外 {unexpected}）')
    ok &= unexpected == 0

# 审核总表原列
a, b = src['审核总表'], wb['审核总表']
d = 0
unexpected = 0
for r in range(1, a.max_row + 1):
    for c in range(1, 20):
        av, bv = a.cell(row=r, column=c).value, b.cell(row=r, column=c).value
        if av != bv:
            d += 1
            coord = a.cell(row=r, column=c).coordinate
            if ('审核总表', coord) in ALLOWED:
                continue
            unexpected += 1
            if unexpected <= 5:
                print(f'   [审核总表] 意外差异 {coord}: {str(av)[:50]} -> {str(bv)[:50]}')
print(f'9) [审核总表] 原 A..S 列差异 = {d}（其中有意表头 {d-unexpected}，意外 {unexpected}）')
res['audit_master_diffs'] = d
res['audit_master_unexpected'] = unexpected
ok &= unexpected == 0

print('\n==== 自检结论:', 'PASS' if ok else 'FAIL', '====')
res['pass'] = bool(ok)
Path(r'<WORKSPACE>\11_投稿包\_work\E1E2E3\_work_diag\xlsx_selfcheck.json').write_text(
    json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding='utf8')
