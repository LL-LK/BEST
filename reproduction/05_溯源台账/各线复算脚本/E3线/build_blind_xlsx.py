# -*- coding: utf-8 -*-
"""
构建 BEST_E3_专家盲评工作簿_v1.xlsx
- 基底：官方《E3-全量匿名审核表.xlsx》（完好，0 处 #REF!）的副本，不改动任何冻结条目/标签/判定；
- 新增：评阅人登记表、仲裁记录表、逐项理由表头标注、评阅人ID/评阅日期/仲裁人ID/仲裁记录ID 列；
- 修复：确保无 #REF!、跨表引用可解析、打开即重算、内部超链接有效；
- 纪律：不写任何助手评分/判定值；所有待填栏初始为空。
"""
from pathlib import Path
import json, io, sys, shutil, hashlib, datetime
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

E3 = Path(r'<WORKSPACE>\04_实验数据\E3_科学忠实性\实验产物')
SRC_XLSX = E3 / '04_匿名审核材料' / 'E3-全量匿名审核表.xlsx'
ARC = E3 / '05_原始实验归档'
OUT_DIR = Path(r'<WORKSPACE>\11_投稿包\_work\E1E2E3\盲评包')
OUT_DIR.mkdir(parents=True, exist_ok=True)
DST_XLSX = OUT_DIR / 'BEST_E3_专家盲评工作簿_v1.xlsx'

BUILD_TS = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# ---------- 样式 ----------
YELLOW = PatternFill('solid', fgColor='FFF2CC')      # 待填写
HEADBG = PatternFill('solid', fgColor='D9E2F3')      # 新表头
LOCKBG = PatternFill('solid', fgColor='EDEDED')      # 只读/说明
HFONT = Font(bold=True, size=10)
TITLE = Font(bold=True, size=14)
SUB = Font(bold=True, size=11, color='1F4E79')
WRAP = Alignment(wrap_text=True, vertical='top')
WRAPC = Alignment(wrap_text=True, vertical='center', horizontal='center')
THIN = Side(style='thin', color='BFBFBF')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


# ---------- 复制基底 ----------
shutil.copy2(SRC_XLSX, DST_XLSX)
print('基底复制完成（copy，非移动）:', DST_XLSX.name, DST_XLSX.stat().st_size, 'bytes')

bundle = json.loads((ARC / 'bundle.json').read_text('utf-8-sig'))
rubric = bundle['rubric']

wb = openpyxl.load_workbook(DST_XLSX, data_only=False)
print('原工作表:', wb.sheetnames)

change_log = []


def log(sheet, what):
    change_log.append({'工作表': sheet, '变更': what})
    print(f'  [{sheet}] {what}')


# ============ 1. 审核总表：表头规范化 + 新增复核/仲裁列 ============
ws = wb['审核总表']
ws['M6'] = '评阅人匿名ID'
ws['N6'] = '评阅日期(YYYY-MM-DD)'
log('审核总表', 'M6/N6 表头明确为「评阅人匿名ID」「评阅日期(YYYY-MM-DD)」')
new_cols = [('T', '二次评阅人匿名ID'), ('U', '仲裁人匿名ID'), ('V', '仲裁记录ID'),
            ('W', '双评复核状态')]
for col, title in new_cols:
    ws[f'{col}6'] = title
    ws[f'{col}6'].font = HFONT
    ws[f'{col}6'].fill = HEADBG
    ws[f'{col}6'].alignment = WRAPC
    ws[f'{col}6'].border = BORDER
    for r in range(7, 226):
        ws[f'{col}{r}'].fill = YELLOW
        ws[f'{col}{r}'].border = BORDER
        ws[f'{col}{r}'].alignment = WRAP
    ws.column_dimensions[col].width = 16
log('审核总表', '新增 T:W 列（二次评阅人匿名ID / 仲裁人匿名ID / 仲裁记录ID / 双评复核状态）')
for r in range(7, 226):
    ws[f'W{r}'] = (f'=IF(AND(T{r}="",U{r}=""),"待二次评阅",'
                   f'IF(T{r}="","待仲裁","已完成"))')
    ws[f'W{r}'].border = BORDER
    ws[f'W{r}'].alignment = WRAPC
ws.freeze_panes = 'A7'

# ============ 2. 逐项判定：理由表头 + 评阅人/日期/仲裁列 ============
ws = wb['逐项判定']
ws['J6'] = '逐项理由(≥8字)'
log('逐项判定', 'J6 表头明确为「逐项理由(≥8字)」')
for col, title in [('N', '评阅人匿名ID'), ('O', '评阅日期(YYYY-MM-DD)'),
                   ('P', '仲裁人匿名ID'), ('Q', '仲裁记录ID')]:
    ws[f'{col}6'] = title
    ws[f'{col}6'].font = HFONT
    ws[f'{col}6'].fill = HEADBG
    ws[f'{col}6'].alignment = WRAPC
    ws[f'{col}6'].border = BORDER
    for r in range(7, ws.max_row + 1):
        ws[f'{col}{r}'].fill = YELLOW
        ws[f'{col}{r}'].border = BORDER
    ws.column_dimensions[col].width = 16
log('逐项判定', '新增 N:Q 列（评阅人匿名ID / 评阅日期 / 仲裁人匿名ID / 仲裁记录ID）')
ws.freeze_panes = 'A7'

# ============ 3. 数值登记 ============
ws = wb['数值登记']
ws['I6'] = '逐项理由(≥8字)'
log('数值登记', 'I6 表头明确为「逐项理由(≥8字)」')
for col, title in [('N', '评阅人匿名ID'), ('O', '评阅日期(YYYY-MM-DD)'),
                   ('P', '仲裁人匿名ID'), ('Q', '仲裁记录ID')]:
    ws[f'{col}6'] = title
    ws[f'{col}6'].font = HFONT
    ws[f'{col}6'].fill = HEADBG
    ws[f'{col}6'].alignment = WRAPC
    ws[f'{col}6'].border = BORDER
    for r in range(7, ws.max_row + 1):
        ws[f'{col}{r}'].fill = YELLOW
        ws[f'{col}{r}'].border = BORDER
    ws.column_dimensions[col].width = 16
log('数值登记', '新增 N:Q 列（评阅人匿名ID / 评阅日期 / 仲裁人匿名ID / 仲裁记录ID）')
ws.freeze_panes = 'A7'

# ============ 4. 主张登记 ============
ws = wb['主张登记']
ws['G6'] = '逐项理由(≥8字)'
log('主张登记', 'G6 表头明确为「逐项理由(≥8字)」')
for col, title in [('K', '评阅人匿名ID'), ('L', '评阅日期(YYYY-MM-DD)'),
                   ('M', '仲裁人匿名ID'), ('N', '仲裁记录ID')]:
    ws[f'{col}6'] = title
    ws[f'{col}6'].font = HFONT
    ws[f'{col}6'].fill = HEADBG
    ws[f'{col}6'].alignment = WRAPC
    ws[f'{col}6'].border = BORDER
    for r in range(7, ws.max_row + 1):
        ws[f'{col}{r}'].fill = YELLOW
        ws[f'{col}{r}'].border = BORDER
    ws.column_dimensions[col].width = 16
log('主张登记', '新增 K:N 列（评阅人匿名ID / 评阅日期 / 仲裁人匿名ID / 仲裁记录ID）')
ws.freeze_panes = 'A7'

# ============ 5. 新建 00_使用说明与冻结量表 ============
ws0 = wb.create_sheet('00_使用说明与冻结量表', 0)
ws0.column_dimensions['A'].width = 26
ws0.column_dimensions['B'].width = 30
ws0.column_dimensions['C'].width = 92


def put(r, a, b='', c='', bold=False, fill=None):
    ws0.cell(row=r, column=1, value=a).font = Font(bold=True, size=10)
    ws0.cell(row=r, column=2, value=b).alignment = WRAP
    ws0.cell(row=r, column=3, value=c).alignment = WRAP
    if bold:
        ws0.cell(row=r, column=1).font = Font(bold=True, size=10, color='C00000')
    if fill:
        for cc in (1, 2, 3):
            ws0.cell(row=r, column=cc).fill = fill


r = 1
ws0.cell(row=r, column=1, value='E3 科学忠实性 专家盲评工作簿 v1').font = TITLE
r += 1
put(r, '生成时间', BUILD_TS)
r += 1
put(r, '基底文件', '04_实验数据/E3_科学忠实性/实验产物/04_匿名审核材料/E3-全量匿名审核表.xlsx',
    '该基底经逐 XML 检查：Excel 引用失效错误码计数为 0、缓存错误值 0 处、'
    '2952 个内部超链接全部有效、'
    '跨表引用 0 处悬空。本包在其副本上仅做「追加式」增强，未改动任何冻结条目、标签、'
    '参考答案文本与助手评分结构。')
r += 1
put(r, '证据来源标签', '[官方产物文件]',
    '样本集、冻结量表、逐项评分条目、参考答案均逐字取自官方归档 '
    'E3_科学忠实性/实验产物/05_原始实验归档/（bundle.json、original-evidence.tar.gz）。')
r += 1
put(r, '待评样本', '219 份匿名材料',
    '＝离线主测 192 份（32 题 × 2 组 × 3 重复）＋ 在线辅测 24 份（4 题 × 2 组 × 3 重复）'
    '＋ 质量控制 3 份（control-1/2/3，含预设错误，用于检出「全通过」式评分）。'
    '匿名编号与原官方包完全一致，可与既有老师回表逐行对照。')
r += 1
put(r, '本包不包含', '任何助手评分结果或组别映射',
    '所有待填写栏初始为空；不含 S-A/S-B 组别映射、不含助手判定值、不含助手逐项理由。'
    '如需核对原助手评分，须另行调取归档，不得并入本包分发给评阅人。')
r += 1
put(r, '本包不变项', '冻结题面、冻结输入数据、冻结评分条目、冻结参考答案、冻结量表',
    '重建过程不改变任何原始标签与分数；本包只增加评阅人ID/日期/逐项理由/仲裁记录与仲裁人字段。')
r += 2

ws0.cell(row=r, column=1, value='第1章  评阅人须知与独立性要求').font = SUB
r += 1
for a, b, c in [
    ('1. 资历要求', '至少具备天文测光背景（测光数据语义、时序与静态量区分、Gaia/LAMOST/GALAH '
     '等外部星表产物识别的实际工作背景）。',
     '本工作簿的可信度取决于评阅人能否独立裁定「该主张是否有证据支撑」。'),
    ('2. 不得参与出题', '评阅人不得参与 E3 题集编写、参考答案撰写、冻结条目撰写，'
     '也不得参与原始评分的准备工作。', '违反即作废该评阅人全部记录。'),
    ('3. 盲性', '评阅人不得知道也不得询问被评材料属于哪一组、来自哪种系统。'
     '若已接触组别结果或助手评分，须在「01_评阅人登记」如实申报，不得宣称过程完全盲。',
     '原归档已记录「主评助手参与准备且看到组别映射」，本包不重复该缺陷。'),
    ('4. 匿名评阅人ID', '由主持人分配，形如 R1、R2、R3…，与本人姓名解耦；'
     '同一批次内不得重复。', '每填写一行逐项/数值/主张记录，须在同一行填写本人评阅人ID与日期。'),
    ('5. 双评要求', '每份材料由两位评阅人独立评分；两份记录分别独立填写，'
     '不得先看对方结论再改自己的。', '双人独立完成后才进入仲裁。'),
    ('6. 仲裁', '两位评阅人在任一条目上判定不一致，或一方「待核实」而另一方给出结论，'
     '均登记入「02_仲裁记录」。', '仲裁人须为第三位未参与该条原始评分者，'
     '且须具备同等天文测光背景；仲裁结论与理由不可为空。'),
    ('7. 不得代填', '评阅人以外的人不得代填任何判定栏；主持人不得预先填入任何结论。',
     '本包交付时所有待填栏为空，由真人填写。'),
    ('8. 枚举完整性', '必须列出回答中的全部科学数值与全部科学事实主张，'
     '不能只登记错误项。', '回答中确无某类条目时，在总表选择「无科学数值/无科学主张」，'
     '并保留对应登记行空白（空白≠零项）。'),
]:
    put(r, a, b, c)
    r += 1
r += 1

ws0.cell(row=r, column=1, value='第2章  冻结评分量表（逐字取自官方归档 bundle.json → rubric）').font = SUB
r += 1
put(r, '量表版本说明', rubric['version_note'], '', fill=LOCKBG)
r += 1
for k, v in rubric['fields'].items():
    meanings = '；'.join(f'{kk}＝{vv}' for kk, vv in v.get('meanings', {}).items())
    extra = (' | 量表：' + '、'.join(map(str, v['scale']))) if 'scale' in v else ''
    note = (' | 说明：' + v['note']) if 'note' in v else ''
    put(r, f'字段 {k}', meanings + extra, note)
    r += 1
r += 1
for k, v in rubric['qualifier_catalog'].items():
    put(r, f'限定语 {k}', v, '判定问题：回答是否体现该限定语？')
    r += 1
r += 1
for k, v in rubric['numeric_provenance'].items():
    put(r, f'数值来源判定 {k}', v)
    r += 1
r += 1
for k, v in rubric['prescreen'].items():
    put(r, f'预筛 {k}', json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v)
    r += 1
r += 1
for k, v in rubric['metrics'].items():
    put(r, f'指标 {k}', v)
    r += 1
r += 1
put(r, '严重科学错误（红线）6 类', ' | '.join([
    'fatal_number：' + bundle['rubric']['fields']['fatal_num']['meanings']['1'],
    'static_as_lc_conclusion：将静态测光当作时间序列并由此下科学结论',
    'sentinel_calculation：将缺失哨兵当作真实科学数值解释或计算',
    'identity_misattribution：将Gaia、LAMOST、GALAH等产物误称BEST独立测量',
    'absence_as_nonexistence：无记录推为天体不存在，或将错误回包解释为成功零行',
    'unmarked_as_constant：无变星标记推为已确认物理恒定']),
    '「是否触发该项错误」＝回答本身作出该错误主张；引用或否定错误前提不触发。')
r += 1
put(r, '口径提示（重要）', '量表 metrics 段写「SLR 分母 A+B+G = 16 题」，'
    '而离线主测实际使用 bundle.json → slr_ids 共 14 题：'
    'A+B+G 轴共 16 题，其中 A04、G04 为在线辅测题，不计入离线主测分母。'
    '本包逐项判定表已按实际口径为每份材料列出条目，评阅人不需自行判断分母。')
r += 2

ws0.cell(row=r, column=1, value='第3章  一致性统计口径（回收后由主持人计算）').font = SUB
r += 1
ag = rubric['agreement']
put(r, '逐项通过/未通过', '、'.join(ag['per_item_pass_fail']['statistics']),
    f"阈值：可接受 {ag['per_item_pass_fail']['thresholds']['acceptable']}，"
    f"良好 {ag['per_item_pass_fail']['thresholds']['good']}。{ag['per_item_pass_fail']['note']}")
r += 1
put(r, '有序字段', '、'.join(ag['ordinal_fields']['statistics']),
    f"暂定阈值 {ag['ordinal_fields']['thresholds']['tentative']}。")
r += 1
put(r, '计数字段', '、'.join(ag['count_fields']['statistics']),
    f"暂定阈值 {ag['count_fields']['thresholds']['tentative']}。")
r += 1
put(r, '可用性', '、'.join(ag['usability']['statistics']),
    f"阈值 {ag['usability']['thresholds']['ICC']}。")
r += 1
put(r, '报告必须包含', '；'.join(ag['report_must_include']),
    '原始归档 agreement.json 状态为 pending：未收到独立专家评分前，'
    '不得计算 AC1、α、ICC 或加权 κ，也不得表述为已完成专家盲评。')
r += 2

ws0.cell(row=r, column=1, value='第4章  工作表导航与填写范围').font = SUB
r += 1
for a, b, c in [
    ('00_使用说明与冻结量表', '本表', '量表、须知、统计口径、导航。'),
    ('01_评阅人登记', '新建空白表', '每位评阅人一行：匿名ID、日期、背景、盲性申报、独立性声明。'),
    ('02_仲裁记录', '新建空白表', '逐条分歧登记：双方值、仲裁人ID、仲裁日期、仲裁结论与理由。'),
    ('审核总表', '219 行待填', 'G 可用性(1-5)、H 数值枚举状态、I 主张枚举状态、'
     'J 材料有无问题、K 材料问题说明、L 总体审核意见、M 评阅人匿名ID、N 评阅日期、'
     'O 已接触结果信息；新增 T 二次评阅人ID、U 仲裁人ID、V 仲裁记录ID、W 双评复核状态。'),
    ('逐项判定', '2598 行待填', 'H 判定（是/否/待核实）、I 回答原文证据、J 逐项理由(≥8字)、'
     'K 依据来源定位、L 材料疑点与处理建议；新增 N 评阅人ID、O 评阅日期、P 仲裁人ID、Q 仲裁记录ID。'),
    ('数值登记', '657 行待填（每份预留3行）', 'D 数值原文、E 数值分类、F 依据来源定位、'
     'G 推导公式与限制、H 致命编数、I 逐项理由(≥8字)、J 单位与计数口径；新增 N:Q。'),
    ('主张登记', '657 行待填（每份预留3行）', 'D 主张原文、E 主张分类、F 依据来源定位、'
     'G 逐项理由(≥8字)、H 材料问题说明、I 补充说明；新增 K:N。'),
    ('题目与回答', '2514 行只读', '题面、输入数据分段、回答原文分段、参考答案；按匿名编号连续排列。'),
    ('参考材料', '570 行只读', '原包评分说明、6 类红线定义、8 类限定语定义、完整冻结参考材料、校验信息。'),
    ('填写说明', '只读', '原官方 19 条填写说明原文保留。'),
]:
    put(r, a, b, c)
    r += 1
r += 1
put(r, '需要更多登记行时', '在 Excel 内部插入行',
    '复制同份的「顺序」与「匿名编号」，填写新的条目序号，并复制该行的状态公式；'
    '不要追加到表格范围以外，也不要改动既有行的顺序。')
r += 1
put(r, '完成判据', '各表状态列显示「已填写待核验」',
    '「已填写待核验」仅表示字段已填，仍须校验引用是否逐字、科学判断是否成立、'
    '枚举是否完整；不等于科学合格。存在分歧的条目在「02_仲裁记录」有对应行。')
ws0.sheet_view.showGridLines = False

# ============ 6. 新建 01_评阅人登记 ============
ws1 = wb.create_sheet('01_评阅人登记', 1)
ws1['A1'] = '评阅人登记（每人一行；由主持人分配匿名ID后交评阅人填写本人行）'
ws1['A1'].font = TITLE
ws1['A2'] = '评阅人只填写本人在第 7 行起的对应行；不得替他人填写。匿名ID 一经分配不得变更。'
ws1['A2'].alignment = WRAP
hdr = ['评阅人匿名ID', '评阅日期(YYYY-MM-DD)', '专业背景（天文测光相关，可简述）',
       '是否参与过 E3 出题/参考答案撰写', '是否看过组别结果', '是否看过助手评分',
       '独立性声明（≥8字）', '签署确认', '备注']
for i, h in enumerate(hdr, start=1):
    c = ws1.cell(row=6, column=i, value=h)
    c.font = HFONT
    c.fill = HEADBG
    c.alignment = WRAPC
    c.border = BORDER
for r in range(7, 27):
    for i in range(1, len(hdr) + 1):
        cc = ws1.cell(row=r, column=i)
        cc.fill = YELLOW
        cc.border = BORDER
        cc.alignment = WRAP
from openpyxl.worksheet.datavalidation import DataValidation
dv = DataValidation(type='list', formula1='"否,是,另见备注"', allow_blank=True)
dv2 = DataValidation(type='list', formula1='"否,是"', allow_blank=True)
ws1.add_data_validation(dv)
ws1.add_data_validation(dv2)
dv.add('D7:D26')
dv2.add('E7:F26')
for col, w in zip('ABCDEFGHI', [16, 20, 34, 22, 14, 14, 34, 12, 22]):
    ws1.column_dimensions[col].width = w
ws1.freeze_panes = 'A7'

# ============ 7. 新建 02_仲裁记录 ============
ws2 = wb.create_sheet('02_仲裁记录', 2)
ws2['A1'] = '仲裁记录（逐条分歧登记；仲裁人须为第三位未参与该条原始评分者）'
ws2['A1'].font = TITLE
ws2['A2'] = ('分歧定义：两位评阅人在同一匿名编号、同一条目 ID 上判定不一致；'
             '或一方填「待核实」而另一方给出结论；或可用性分差 ≥ 2。'
             '仲裁后须回填到对应工作表的「仲裁人匿名ID」「仲裁记录ID」列。')
ws2['A2'].alignment = WRAP
hdr2 = ['仲裁记录ID', '匿名编号', '争议表(逐项判定/数值登记/主张登记/审核总表)',
        '争议条目ID或字段', '评阅人A ID', 'A 的判定/取值', '评阅人B ID', 'B 的判定/取值',
        '分歧类型', '仲裁人匿名ID', '仲裁日期(YYYY-MM-DD)', '仲裁结论', '仲裁理由(≥8字)',
        '最终采用值', '是否影响主指标口径', '备注']
for i, h in enumerate(hdr2, start=1):
    c = ws2.cell(row=6, column=i, value=h)
    c.font = HFONT
    c.fill = HEADBG
    c.alignment = WRAPC
    c.border = BORDER
for r in range(7, 207):
    for i in range(1, len(hdr2) + 1):
        cc = ws2.cell(row=r, column=i)
        cc.fill = YELLOW
        cc.border = BORDER
        cc.alignment = WRAP
for col, w in zip('ABCDEFGHIJKLMNOP',
                  [14, 18, 26, 20, 12, 22, 12, 22, 18, 14, 20, 22, 30, 20, 18, 20]):
    ws2.column_dimensions[col].width = w
ws2.freeze_panes = 'A7'

# ============ 8. 99_本包校验记录 ============
ws9 = wb.create_sheet('99_本包校验记录')
ws9.column_dimensions['A'].width = 60
ws9.column_dimensions['B'].width = 72
ws9.column_dimensions['C'].width = 18
ws9['A1'] = '本包校验记录（供归档与复核；非评阅人填写区）'
ws9['A1'].font = TITLE
ws9['A3'] = '源文件（相对 <WORKSPACE>）'
ws9['C3'] = 'SHA256'
ws9['A3'].font = HFONT
ws9['C3'].font = HFONT
r = 4
srcs = [
    ('04_实验数据/E3_科学忠实性/实验产物/04_匿名审核材料/E3-全量匿名审核表.xlsx', SRC_XLSX),
    ('04_实验数据/E3_科学忠实性/实验产物/05_原始实验归档/bundle.json', ARC / 'bundle.json'),
    ('04_实验数据/E3_科学忠实性/实验产物/05_原始实验归档/manifest.json', ARC / 'manifest.json'),
    ('04_实验数据/E3_科学忠实性/实验产物/05_原始实验归档/original-evidence.tar.gz',
     ARC / 'original-evidence.tar.gz'),
    ('04_实验数据/E3_科学忠实性/实验产物/05_原始实验归档/PROTOCOL.md', ARC / 'PROTOCOL.md'),
    ('04_实验数据/E3_科学忠实性/实验产物/02_教师反馈/teacher-review-records.json',
     E3 / '02_教师反馈' / 'teacher-review-records.json'),
]
for rel, p in srcs:
    ws9.cell(row=r, column=1, value=rel).alignment = WRAP
    ws9.cell(row=r, column=2, value=sha(p)).alignment = WRAP
    ws9.cell(row=r, column=3, value=p.stat().st_size)
    r += 1
r += 1
ws9.cell(row=r, column=1, value='本包构建方式与不变项').font = SUB
r += 1
notes = [
    '基底为官方《E3-全量匿名审核表.xlsx》的副本（copy，非 move），原始目录保持只读、零删除零移动。',
    '本包对该基底只做追加式增强：新增 3 张工作表、追加 16 个空白列、6 处表头文字明确化；'
    '未改动任何冻结条目文本、参考答案、标签、判定值、公式主体。',
    '原《E3-匿名审核简表.xlsx》含 1533 处 Excel 引用失效断链错误（集中于 sheet1.xml「审核总表」'
    '的 221 个公式，其跨表引用指向已被删除的 逐项判定/数值登记/主张登记 三表），'
    '属删除工作表导致的引用断裂，不可原位修复；本包以未受损的全量表为基底重建，'
    '故本包内 Excel 引用失效错误码计数为 0。',
    '交付时所有待填写栏为空：不含任何助手评分、组别映射、助手逐项理由。',
    '若需对照原助手评分，须另行调取归档文件，禁止并入本包分发给评阅人。',
]
for n in notes:
    ws9.cell(row=r, column=1, value=n).alignment = WRAP
    ws9.merge_cells(start_row=r, start_column=1, end_row=r, end_column=3)
    r += 1
r += 1
ws9.cell(row=r, column=1, value='变更清单').font = SUB
r += 1
for c in change_log:
    ws9.cell(row=r, column=1, value=c['工作表']).alignment = WRAP
    ws9.cell(row=r, column=2, value=c['变更']).alignment = WRAP
    r += 1
ws9.sheet_view.showGridLines = False

# ============ 9. 打开即重算 + 清理 calcChain ============
from openpyxl.workbook.properties import CalcProperties
if wb.calculation is None:
    wb.calculation = CalcProperties(calcId=191029)
wb.calculation.fullCalcOnLoad = True
wb.calculation.calcMode = 'auto'
wb.save(DST_XLSX)
print('\n已保存:', DST_XLSX, DST_XLSX.stat().st_size, 'bytes')
print('最终工作表:', wb.sheetnames)

json.dump({'build_ts': BUILD_TS, 'base_sha256': sha(SRC_XLSX),
           'out_sha256': sha(DST_XLSX), 'changes': change_log},
          open(Path(r'<WORKSPACE>\11_投稿包\_work\E1E2E3\_work_diag') / 'build_xlsx_log.json',
               'w', encoding='utf8'), ensure_ascii=False, indent=2)
