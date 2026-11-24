# -*- coding: utf-8 -*-
"""
构建 BEST_E3_专家盲评工作簿_v1.docx —— 评审手册 + 冻结量表 + 空白评审表 + 219 样本索引。
不含任何助手评分、组别映射或代填判定。
"""
from pathlib import Path
import json, io, sys, hashlib, datetime, collections
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
import openpyxl

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

E3 = Path(r'<WORKSPACE>\04_实验数据\E3_科学忠实性\实验产物')
ARC = E3 / '05_原始实验归档'
OUT_DIR = Path(r'<WORKSPACE>\11_投稿包\_work\E1E2E3\盲评包')
XLSX = OUT_DIR / 'BEST_E3_专家盲评工作簿_v1.xlsx'
DST = OUT_DIR / 'BEST_E3_专家盲评工作簿_v1.docx'
BUILD_TS = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

bundle = json.loads((ARC / 'bundle.json').read_text('utf-8-sig'))
rubric = bundle['rubric']

wb = openpyxl.load_workbook(XLSX, data_only=False)
master = wb['审核总表']
peritem = wb['逐项判定']
samples = []
for r in range(7, 226):
    sid = master.cell(row=r, column=2).value
    samples.append({
        'order': master.cell(row=r, column=1).value,
        'sid': sid,
        'dtype': master.cell(row=r, column=3).value,
        'prompt': master.cell(row=r, column=4).value,
        'row': r,
    })
# 逐项判定区间
span = collections.defaultdict(list)
for r in range(7, peritem.max_row + 1):
    span[peritem.cell(row=r, column=2).value].append(r)
for s in samples:
    rs = span.get(s['sid'], [])
    s['n_items'] = len(rs)
    s['item_first'] = rs[0] if rs else ''
    s['item_last'] = rs[-1] if rs else ''
print('样本数:', len(samples), '| 逐项判定行总数:', sum(s['n_items'] for s in samples))

doc = Document()

# 全局样式
st = doc.styles['Normal']
st.font.name = 'Times New Roman'
st.font.size = Pt(10.5)
st.element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
for s in doc.sections:
    s.left_margin = s.right_margin = Cm(2.2)
    s.top_margin = s.bottom_margin = Cm(2.0)


def ea(run, name='宋体'):
    run.font.name = run.font.name or 'Times New Roman'
    rPr = run._element.get_or_add_rPr()
    rf = rPr.get_or_add_rFonts()
    rf.set(qn('w:eastAsia'), name)

def H(text, level=1):
    p = doc.add_heading(text, level=level)
    for run in p.runs:
        run.font.name = 'Times New Roman'
        ea(run, '黑体')
        run.font.color.rgb = RGBColor(0x1F, 0x3B, 0x63)
    return p


def P(text, bold=False, italic=False, size=10.5, after=3):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(after)
    r = p.add_run(text)
    r.bold = bold
    r.italic = italic
    r.font.size = Pt(size)
    r.font.name = 'Times New Roman'
    ea(r, '宋体')
    return p


def KV(rows, widths=(4.2, 13.0)):
    t = doc.add_table(rows=0, cols=2)
    t.style = 'Table Grid'
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for k, v in rows:
        cells = t.add_row().cells
        cells[0].text = ''
        cells[1].text = ''
        pk = cells[0].paragraphs[0]
        rk = pk.add_run(str(k))
        rk.bold = True
        rk.font.size = Pt(9.5)
        ea(rk, '黑体')
        pv = cells[1].paragraphs[0]
        rv = pv.add_run(str(v))
        rv.font.size = Pt(9.5)
        ea(rv, '宋体')
    for row in t.rows:
        row.cells[0].width = Cm(widths[0])
        row.cells[1].width = Cm(widths[1])
    doc.add_paragraph()
    return t


def blank_table(headers, nrows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = 'Table Grid'
    hdr = t.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = ''
        r = hdr[i].paragraphs[0].add_run(h)
        r.bold = True
        r.font.size = Pt(8.5)
        ea(r, '黑体')
    for _ in range(nrows):
        cells = t.add_row().cells
        for c in cells:
            c.text = ''
            for p in c.paragraphs:
                p.paragraph_format.space_after = Pt(0)
                rr = p.add_run(' ')
                rr.font.size = Pt(8.5)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph()
    return t


# ================= 封面 =================
ttl = doc.add_heading('E3 科学忠实性  专家盲评工作簿', level=0)
for run in ttl.runs:
    ea(run, '黑体')
P('版本 v1', bold=True, size=13)
P('本文件为「评审手册 + 空白评审表」。完整题面、输入数据、回答原文与逐条冻结评分条目'
  '位于同名 xlsx 的「题目与回答」「逐项判定」「参考材料」工作表，请与本文件配套使用。')
doc.add_paragraph()
KV([
    ('生成时间', BUILD_TS),
    ('证据来源标签', '[官方产物文件] —— 样本集、冻结量表、逐项评分条目、参考答案均逐字取自 '
     '官方归档 04_实验数据/E3_科学忠实性/实验产物/05_原始实验归档/（bundle.json、original-evidence.tar.gz）'),
    ('本包基底', '官方《E3-全量匿名审核表.xlsx》的副本（copy，非 move）；'
     '原始目录全程只读、零删除零移动'),
    ('本包不含', '任何助手评分结果、组别映射、助手逐项理由。'
     '所有待填写栏在交付时为空，由真人填写'),
    ('待评样本', '219 份匿名材料 ＝ 离线主测 192 份 ＋ 在线辅测 24 份 ＋ 质量控制 3 份'),
    ('最低评阅要求', '至少两位具备天文测光背景的评审，独立盲评；'
     '分歧条目须由第三位同等背景者仲裁'),
], widths=(4.0, 13.2))

P('重要声明', bold=True, size=12)
P('原归档记录：E3 的逐项主评由「参与准备的助手」完成，评分上下文未独立隔离（见 05_原始实验归档/'
  'manifest.json → protocol.primary_judge.context_isolated = false；'
  'self_rating_risk 记为「主评助手参与准备且看到组别映射，匿名材料不保证评阅人盲性」）。'
  '此前的老师回表覆盖 213/216 份真实回答，但属定性勾选与文字意见，未替换逐项科学主张的量化标签，'
  '且回表核验明确原主指标未改变；agreement.json 状态仍为 pending。')
P('因此：现有 30.26% 无支撑主张率可复算，但不得表述为「已完成独立专家逐主张裁定的客观错误率」。'
  '本盲评包正是为补齐这一步而制作；在本包完成独立盲评并完成仲裁之前，'
  '论文不得作出「经独立专家逐主张裁定」的表述。')

doc.add_page_break()

# ================= 1 =================
H('1  盲评对象与样本构成', 1)
P('E3（实验三）检验领域语义材料能否改善模型对星表结果的科学解释。'
  '完整配置 S-A 获得领域材料与能力边界，基础包装器 S-B 获得表名、列名与两阶段查询协议。'
  '两组使用相同题面与输入数据，每题在独立上下文中重复三次。')
blank_table(['分层', '题号数', '回答份数', '是否并入主指标', '说明'],
            3, widths=(3.0, 2.0, 2.4, 3.4, 6.4))
for row in doc.tables[-1].rows[1:]:
    vals = [['离线主测', '32', '192（32×2 组×3 重复）', '是', '离线输入为语义测试夹具，不视为真实天体观测'],
            ['在线辅测', '4', '24（4×2 组×3 重复）', '否', '在线题输入是该轮实际回包，不并入离线主指标'],
            ['质量控制', '—', '3（control-1/2/3）', '否', '含预设错误，用于检出「全通过」式评分；'
             '上一轮控制项仅 2/3 被明确识别出预设错误']]
    break
t = doc.tables[-1]
for row, vals in zip(t.rows[1:], vals):
    for c, v in zip(row.cells, vals):
        c.text = ''
        r = c.paragraphs[0].add_run(v)
        r.font.size = Pt(8.5)
        ea(r, '宋体')
P('合计 219 份匿名材料。匿名编号与原官方包、既有老师回表完全一致，可逐行对照。', bold=True)
P('盲性要求：评阅人不得知道也不得询问某份材料属于哪一组；材料中不含组别映射、'
  '被测模型标签或助手评分身份。', after=8)

# ================= 2 =================
H('2  评阅人须知与独立性要求', 1)
KV([
    ('资历要求', '至少具备天文测光背景：测光数据语义、静态量与时序量区分、'
     'Gaia/LAMOST/GALAH 等外部星表产物识别的实际工作背景。'),
    ('不得参与出题', '评阅人不得参与 E3 题集编写、参考答案撰写、冻结条目撰写，'
     '也不得参与原始评分的准备工作。违反即作废该评阅人全部记录。'),
    ('盲性', '不得知道被评材料属于哪一组、来自哪种系统。若已接触组别结果或助手评分，'
     '须在「01_评阅人登记」如实申报，不得宣称过程完全盲。'),
    ('匿名评阅人 ID', '由主持人分配，形如 R1、R2、R3…，与本人姓名解耦，同批次内不得重复。'
     '每填写一行逐项/数值/主张记录，须在同一行填写本人评阅人 ID 与日期。'),
    ('独立双评', '每份材料由两位评阅人独立评分，互不看对方结论。'),
    ('仲裁', '同一匿名编号的同一条目上判定不一致，或一方「待核实」而另一方给出结论，'
     '或可用性分差 ≥ 2，均登记入「02_仲裁记录」。仲裁人须为第三位未参与该条原始评分者，'
     '且具备同等天文测光背景；仲裁结论与理由不可为空。'),
    ('不得代填', '评阅人以外的人不得代填任何判定栏；主持人不得预先填入任何结论。'),
    ('枚举完整性', '必须列出回答中的全部科学数值与全部科学事实主张，不能只登记错误项。'
     '确无某类条目时，在总表选「无科学数值/无科学主张」并保留登记行空白（空白 ≠ 零项）。'),
], widths=(3.6, 13.6))

# ================= 3 =================
H('3  冻结评分量表', 1)
P('以下量表逐字取自官方归档 bundle.json → rubric，评阅期间不得修改。'
  '如发现量表或参考答案本身存在科学缺陷，请在对应登记表的「材料问题说明」栏记录，'
  '不得因参考答案如此就自动扣分，也不得把「可追溯」直接等同于「科学正确」。')
P('量表版本说明：' + rubric['version_note'])
H('3.1  逐项字段定义', 2)
blank_table(['字段', '取值', '含义'], len(rubric['fields']), widths=(3.4, 2.4, 11.4))
t = doc.tables[-1]
for row, (k, v) in zip(t.rows[1:], rubric['fields'].items()):
    meanings = '\n'.join(f'{kk} ＝ {vv}' for kk, vv in v.get('meanings', {}).items())
    scale = ('量表：' + '、'.join(map(str, v['scale']))) if 'scale' in v else ''
    txt = meanings + (('\n' + scale) if scale else '') + (('\n说明：' + v['note']) if 'note' in v else '')
    for c, val in zip(row.cells, [k, '、'.join(map(str, v.get('scale', []))) or '计数', txt]):
        c.text = ''
        r = c.paragraphs[0].add_run(val)
        r.font.size = Pt(8.5)
        ea(r, '宋体')

H('3.2  必要限定语定义（8 类）', 2)
blank_table(['限定语 ID', '定义', '判定问题'], len(rubric['qualifier_catalog']), widths=(3.8, 9.4, 4.0))
t = doc.tables[-1]
for row, (k, v) in zip(t.rows[1:], rubric['qualifier_catalog'].items()):
    for c, val in zip(row.cells, [k, v, '回答是否体现该限定语？']):
        c.text = ''
        r = c.paragraphs[0].add_run(val)
        r.font.size = Pt(8.5)
        ea(r, '宋体')

H('3.3  数值来源判定规则', 2)
KV([(k, v) for k, v in rubric['numeric_provenance'].items()], widths=(4.4, 12.8))

H('3.4  严重科学错误（红线）6 类', 2)
P('「是否触发该项错误」＝回答本身作出该错误主张；引用或否定错误前提不触发。'
  '每份材料的逐项判定表已按此 6 类逐条列出，评阅人逐条判定即可。')
blank_table(['红线 ID', '定义'], 6, widths=(5.0, 12.2))
t = doc.tables[-1]
redlines = [
    ('fatal_number', '无来源科学数值直接决定周期、振幅、概率、零点或其他科学结论'),
    ('static_as_lc_conclusion', '将静态测光当作时间序列并由此下科学结论'),
    ('sentinel_calculation', '将缺失哨兵当作真实科学数值解释或计算'),
    ('identity_misattribution', '将 Gaia、LAMOST、GALAH 等产物误称 BEST 独立测量'),
    ('absence_as_nonexistence', '无记录推为天体不存在，或将错误回包解释为成功零行'),
    ('unmarked_as_constant', '无变星标记推为已确认物理恒定'),
]
for row, (k, v) in zip(t.rows[1:], redlines):
    for c, val in zip(row.cells, [k, v]):
        c.text = ''
        r = c.paragraphs[0].add_run(val)
        r.font.size = Pt(8.5)
        ea(r, '宋体')

H('3.5  指标口径（供理解条目用途，不需评阅人自行计算）', 2)
KV([(k, v) for k, v in rubric['metrics'].items()], widths=(3.2, 14.0))
P('口径提示（重要）：量表 metrics 段写「SLR 分母 A+B+G = 16 题」，'
  '而离线主测实际使用 bundle.json → slr_ids 共 14 题 —— A+B+G 轴共 16 题，'
  '其中 A04、G04 为在线辅测题，不计入离线主测分母。'
  '本工作簿逐项判定表已按实际口径为每份材料列出条目，评阅人无须自行判断分母。', bold=True)

doc.add_page_break()

# ================= 4 =================
H('4  填写操作说明', 1)
P('以下 19 条为原官方评审包《填写说明》原文保留；第 20–27 条为本版新增的盲评与仲裁操作要求。')
blank_table(['序号', '说明项目', '填写方法'], 19, widths=(1.2, 3.6, 12.4))
t = doc.tables[-1]
ws = wb['填写说明']
rows19 = []
for r in range(7, ws.max_row + 1):
    a = ws.cell(row=r, column=1).value
    b = ws.cell(row=r, column=2).value
    c = ws.cell(row=r, column=3).value
    if a:
        rows19.append((a, b, c))
for row, vals in zip(t.rows[1:], rows19):
    for c, val in zip(row.cells, [str(v) for v in vals]):
        c.text = ''
        r = c.paragraphs[0].add_run(val)
        r.font.size = Pt(8.5)
        ea(r, '宋体')

P('本版新增操作要求（第 20–27 条）', bold=True)
newrules = [
    ('20', '评阅人登记', '开始前先在 xlsx「01_评阅人登记」填写本人那一行：'
     '匿名ID、日期、专业背景、是否参与出题、是否看过组别结果/助手评分、独立性声明、签署确认。'),
    ('21', '逐行署名', '在「逐项判定」「数值登记」「主张登记」每写一行，就在同一行的'
     '「评阅人匿名ID」「评阅日期」两列填本人ID与日期；空行不填。'),
    ('22', '理由长度', '「逐项理由」至少 8 个汉字，必须写清依据来源或缺失的证据类型，'
     '不得写「无」「不对」「同上」。'),
    ('23', '引用逐字', '「回答原文证据」必须逐字取自回答，不得改写、概括或拼接。'),
    ('24', '待核实', '无法判定的条目填「待核实」并在理由中说明缺什么；'
     '「待核实」不计入完成状态，须回访补齐。'),
    ('25', '仲裁触发', '两位评阅人在同一条目判定不一致、或一方「待核实」另一方给出结论、'
     '或可用性分差 ≥ 2 时，在「02_仲裁记录」新增一行，逐列填双方ID与取值。'),
    ('26', '仲裁回填', '仲裁完成后，在对应工作表该行的「仲裁人匿名ID」「仲裁记录ID」'
     '两列回填仲裁人ID与仲裁记录ID，并在「仲裁结论/最终采用值」写明结论。'),
    ('27', '完成判据', '各表状态列显示「已填写待核验」仅表示字段已填，'
     '仍须校验引用逐字性、枚举完整性与科学判断；不等于科学合格。'),
]
blank_table(['序号', '说明项目', '填写方法'], len(newrules), widths=(1.2, 3.6, 12.4))
t = doc.tables[-1]
for row, vals in zip(t.rows[1:], newrules):
    for c, val in zip(row.cells, list(vals)):
        c.text = ''
        r = c.paragraphs[0].add_run(val)
        r.font.size = Pt(8.5)
        ea(r, '宋体')

doc.add_page_break()

# ================= 5 =================
H('5  评阅人登记表（空白，待填写）', 1)
P('每人一行；由主持人分配匿名ID后交评阅人本人填写本人那一行，不得代他人填写。')
blank_table(['评阅人匿名ID', '评阅日期', '专业背景', '参与过出题？', '看过组别结果？',
             '看过助手评分？', '独立性声明（≥8字）', '签署确认'],
            8, widths=(2.0, 2.0, 3.2, 1.8, 1.8, 1.8, 3.6, 1.6))

# ================= 6 =================
H('6  仲裁记录表（空白，待填写）', 1)
P('仲裁人须为第三位未参与该条原始评分者，且具备同等天文测光背景。'
  '仲裁结论与仲裁理由不可为空；最终采用值须与回填到各工作表的值一致。')
blank_table(['仲裁记录ID', '匿名编号', '争议表', '争议条目ID/字段', '评阅人A ID', 'A 取值',
             '评阅人B ID', 'B 取值', '分歧类型', '仲裁人ID', '仲裁日期', '仲裁结论',
             '仲裁理由（≥8字）', '最终采用值', '影响主指标口径？'],
            10, widths=(1.8, 2.0, 1.8, 1.8, 1.4, 1.4, 1.4, 1.4, 1.6, 1.4, 1.6, 1.8, 2.4, 1.8, 1.6))

doc.add_page_break()

# ================= 7 =================
H('7  逐项判定空白记录表模板', 1)
P('下表为单份材料的逐项判定模板（xlsx「逐项判定」表为 219 份材料的完整展开，'
  '共 2598 行，每份材料自带其应判条目）。本模板仅示格式，填写时在 xlsx 对应行填写。')
blank_table(['类别', '条目ID', '冻结条目原文', '判定问题', '判定（是/否/待核实）',
             '回答原文证据', '逐项理由（≥8字）', '依据来源定位', '评阅人ID', '评阅日期',
             '仲裁人ID', '仲裁记录ID'],
            9, widths=(1.8, 1.4, 3.4, 1.8, 1.8, 2.6, 2.6, 1.8, 1.2, 1.2, 1.2, 1.2))
t = doc.tables[-1]
demo = [
    ('关键科学点', 'c1', '（以该材料实际条目原文为准）', '是否命中或说明'),
    ('关键科学点', 'c2', '（以该材料实际条目原文为准）', '是否命中或说明'),
    ('必要限定语', 'missing_or_sentinel', '缺失值与哨兵(-999/-1004)已识别并排除，未当真实值', '是否命中或说明'),
    ('必要限定语', 'catalog_and_column', "说清哪张表、哪一列(如 stripe82.rmmed，不是'r 星等')", '是否命中或说明'),
    ('禁止结论', 'f1', '（以该材料实际条目原文为准）', '是否触发该项错误'),
    ('严重科学错误', 'fatal_number', '无来源科学数值直接决定周期、振幅、概率、零点或其他科学结论', '是否触发该项错误'),
    ('严重科学错误', 'static_as_lc_conclusion', '将静态测光当作时间序列并由此下科学结论', '是否触发该项错误'),
    ('严重科学错误', 'sentinel_calculation', '将缺失哨兵当作真实科学数值解释或计算', '是否触发该项错误'),
    ('严重科学错误', 'identity_misattribution', '将Gaia、LAMOST、GALAH等产物误称BEST独立测量', '是否触发该项错误'),
]
for row, vals in zip(t.rows[1:], demo):
    for c, val in zip(row.cells, list(vals) + [''] * 8):
        c.text = ''
        r = c.paragraphs[0].add_run(str(val))
        r.font.size = Pt(8)
        ea(r, '宋体')

P('数值登记模板（每份预留 3 行）', bold=True)
blank_table(['数值序号', '回答中的数值原文', '数值分类', '依据来源定位', '推导公式与限制',
             '致命编数', '逐项理由（≥8字）', '单位与计数口径', '材料问题说明', '补充证据',
             '记录状态', '评阅人ID', '评阅日期', '仲裁人ID', '仲裁记录ID'],
            3, widths=(1.4, 2.8, 1.4, 1.8, 2.2, 1.2, 2.2, 1.6, 1.6, 1.6, 1.2, 1.2, 1.2, 1.2, 1.2))
P('主张登记模板（每份预留 3 行）', bold=True)
blank_table(['主张序号', '回答中的科学主张原文', '主张分类', '依据来源定位', '逐项理由（≥8字）',
             '材料问题说明', '补充说明', '记录状态', '评阅人ID', '评阅日期', '仲裁人ID', '仲裁记录ID'],
            3, widths=(1.4, 3.6, 1.4, 1.8, 2.4, 1.6, 1.6, 1.2, 1.2, 1.2, 1.2, 1.2))
P('审核总表模板（每份材料一行）', bold=True)
blank_table(['顺序', '匿名编号', '数据类型', '题面', '可用性1-5', '数值枚举状态', '主张枚举状态',
             '材料有无问题', '材料问题说明', '总体审核意见', '评阅人匿名ID', '评阅日期',
             '已接触结果信息', '二次评阅人ID', '仲裁人ID', '仲裁记录ID', '双评复核状态'],
            3, widths=(1.0, 2.0, 1.6, 3.4, 1.2, 1.4, 1.4, 1.4, 1.8, 2.4, 1.4, 1.2, 1.6, 1.4, 1.2, 1.4, 1.4))

doc.add_page_break()

# ================= 8 =================
H('8  样本索引表（219 份）', 1)
P('题面与冻结条目数取自官方归档；「逐项判定行」指向 xlsx 中该匿名编号对应的行区间。')
blank_table(['序', '匿名编号', '数据类型', '题面', '冻结条目数', '逐项判定行'],
            len(samples), widths=(0.9, 2.6, 2.0, 8.0, 1.5, 1.8))
t = doc.tables[-1]
for row, s in zip(t.rows[1:], samples):
    for c, val in zip(row.cells, [str(s['order']), str(s['sid']), str(s['dtype']),
                                  str(s['prompt'] or ''), str(s['n_items']),
                                  f"{s['item_first']}–{s['item_last']}"]):
        c.text = ''
        r = c.paragraphs[0].add_run(val)
        r.font.size = Pt(7.5)
        ea(r, '宋体')

doc.add_page_break()

# ================= 9 =================
H('9  回收与一致性计算（回收后由主持人执行）', 1)
ag = rubric['agreement']
KV([
    ('逐项通过/未通过', '、'.join(ag['per_item_pass_fail']['statistics']) +
     f"；阈值 可接受 {ag['per_item_pass_fail']['thresholds']['acceptable']}、"
     f"良好 {ag['per_item_pass_fail']['thresholds']['good']}。{ag['per_item_pass_fail']['note']}"),
    ('有序字段', '、'.join(ag['ordinal_fields']['statistics']) +
     f"；暂定阈值 {ag['ordinal_fields']['thresholds']['tentative']}。"),
    ('计数字段', '、'.join(ag['count_fields']['statistics']) +
     f"；暂定阈值 {ag['count_fields']['thresholds']['tentative']}。"),
    ('可用性', '、'.join(ag['usability']['statistics']) +
     f"；阈值 {ag['usability']['thresholds']['ICC']}。"),
    ('报告必须包含', '；'.join(ag['report_must_include'])),
    ('统计检验', rubric['statistics']['main_test'] + '；' + rubric['statistics']['ci']),
    ('效力提示', rubric['statistics']['power_caveat']),
    ('附加交付物', rubric['extra_deliverable']),
    ('当前状态', '原归档 agreement.json 状态为 pending：未收到独立专家评分前，'
     '不得计算 AC1、α、ICC 或加权 κ，也不得表述为已完成专家盲评。'),
], widths=(3.6, 13.6))
P('回收流程建议（不覆盖任何既有记录）', bold=True)
for i, s in enumerate([
    '主持人分别收回各评阅人的 xlsx 原件，原样归档，不做任何编辑。',
    '先校验每份原件的完整性（状态列是否全为「已填写待核验」、引用是否逐字、'
    '数值/主张枚举是否完整），再合并为带评阅人ID列的合并表。',
    '对同一匿名编号、同一条目 ID 做双评比对，生成分歧清单。',
    '分歧清单逐条进入「02_仲裁记录」，由第三人仲裁。',
    '仲裁完成后按 rubric.agreement 的统计口径计算一致性指标与逐轴分层 κ，'
    '并按 report_must_include 列出分歧项清单与仲裁项占比。',
    '独立盲评结果与原助手主评的对照单独成表，保留双方原始记录，'
    '不覆盖、不合并、不删除任何一方的不利结果。',
    '若独立盲评与原主评不一致，按第 4 节第 1 条建议口径交人工裁决：'
    '保留原分并建立新评分版本，不追溯改分、不删除不利结果。',
], 1):
    P(f'{i}. {s}', size=10)

# ================= 10 =================
H('10  本包校验记录', 1)
KV([
    ('基底文件 SHA256', '见 xlsx「99_本包校验记录」工作表（含 bundle.json、manifest.json、'
     'original-evidence.tar.gz、PROTOCOL.md、teacher-review-records.json、基底工作簿的逐文件 SHA256）'),
    ('基底检查结论', '逐 XML 检查：Excel 引用失效错误码 0 处、缓存错误值 0 处、'
     '2952 个内部超链接全部有效、跨表引用悬空 0 处'),
    ('本包自检', '输出 xlsx：引用失效错误码 0 处、公式 4353 条、跨表引用悬空 0、'
     '超链接 2952 有效、待填写栏非空单元格 0'),
    ('相对基底差异', '仅 6 处表头文字明确化（审核总表 M6/N6、逐项判定 J6、数值登记 I6、'
     '主张登记 G6）＋ 新增 16 个空白列 ＋ 新增 3 张工作表；'
     '冻结只读表（题目与回答/参考材料/填写说明）与基底差异 0 单元格；'
     '逐项判定原 A–I 列、数值登记原 A–H 列、主张登记原 A–F 列差异 0 单元格'),
    ('不含项声明', '本包不含任何助手评分、组别映射、助手逐项理由；'
     '未改动任何冻结条目文本、参考答案、标签与判定值'),
], widths=(3.6, 13.6))

doc.save(DST)
print('已保存:', DST, DST.stat().st_size, 'bytes')


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


json.dump({'build_ts': BUILD_TS, 'docx_sha256': sha(DST), 'xlsx_sha256': sha(XLSX),
           'n_samples': len(samples),
           'n_peritem_rows': sum(s['n_items'] for s in samples)},
          open(Path(r'<WORKSPACE>\11_投稿包\_work\E1E2E3\_work_diag') / 'build_docx_log.json',
               'w', encoding='utf8'), ensure_ascii=False, indent=2)
