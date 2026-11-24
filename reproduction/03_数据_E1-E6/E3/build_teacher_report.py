"""从已归档E3结果生成中文阅读说明；不运行实验，不修改任何评分。"""
from pathlib import Path
import hashlib
import json
from html import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent
ARCHIVE = ROOT / 'docs/results/2026-10-07/e3-b5ad6d180c9f42ce'
SOURCE = ARCHIVE / 'FINAL-RESULTS.json'
data = SOURCE.read_bytes()
result = json.loads(data)
assert result['batch_id'] == 'e3-b5ad6d180c9f42ce'
assert result['collection']['actual'] == 216 and result['rating']['actual'] == 216
assert result['expert']['status'] == 'pending'

metrics = [
    ('sfa', '关键科学断言命中率', '应说明的关键科学点，回答覆盖了多少', '越高越好'),
    ('ungr', '无来源数值率', '所列科学数字中，有多少缺少可追溯来源', '越低越好'),
    ('ucr', '无支撑主张率', '所列科学说法中，有多少没有充分依据', '越低越好'),
    ('slr', '静态误称时序率', '相关题中，有多少把汇总测光当成时间变化证据', '越低越好'),
    ('rqc', '必要限定语覆盖率', '该交代的来源、范围、误差等条件，交代了多少', '越高越好'),
]

def val(group, field):
    return result['main']['systems'][group]['metrics'][field]['median']

def pct(x):
    return f'{x:.2%}'

summary = (
    f"在当前助手评分下，提供完整领域材料的A组，关键科学断言命中率为{pct(val('S-A','sfa'))}，"
    f"只提供普通接口说明的B组为{pct(val('S-B','sfa'))}。A组表现较好；但评分尚未经过独立专家复核，"
    "目前属于初步结果，不能写成已经完成专家验证的结论。"
)

design = [
    ('研究问题', '给同一个模型提供完整的天文领域skill材料，能否减少科学语义错误和无依据推断？'),
    ('被测模型', 'deepseek-flash；本轮结果不代表GPT-6.1的表现。'),
    ('A组（S-A）', '完整skill与领域材料，包含相关科学概念、数据含义和能力边界说明。'),
    ('B组（S-B）', '普通API包装器，只提供表名、列名和两阶段查询协议。'),
    ('样本与重复', '32道离线题和4道在线题；每题两组各独立回答3次，共216份回答。主表只统计192份离线回答，在线24份另列。'),
    ('谁评分', '当前对话助手直接评分，没有调用外部评分API；助手参与过准备并见过组别映射，不属于独立盲评。'),
]

examples = [
    ('把汇总数据当成光变证据', '“在 Stripe82 观测时段内它在 r 波段是稳定的”',
     '汇总星等和散射不等于完整光变曲线，不能直接据此确认整个时段物理恒定。应说明需要逐历元数据。'),
    ('缺少换算条件仍给出精确数值', '“15.44”（窄波段星等）',
     '题面没有提供完整的单位、带通响应及零点。即使套公式得到一个数，也不能把它当成该波段已核实的实际星等。'),
    ('把没有数据读成没有变化', '“has_epoch_photometry = False”（随后称不会有光变污染问题）',
     '没有公开历元测光，只表示数据可用性，不表示已经确认该源没有光变。'),
]

json_fields = [
    ('collection.actual = 216', '216份真实回答已经采集完成。'),
    ('rating.valid = true', '评分记录字段、证据绑定及反证检查符合流程要求；不代表每个回答都科学正确。'),
    ('scientific_performance.status = FAIL', '至少有回答触发科学红线；不是程序没有运行，也不是全部回答都错。'),
    ('main.systems.S-A / S-B', '分别为完整材料组与普通包装器组的离线主测结果。'),
    ('median / per_repeat / range', '三次结果的中间值 / 三次各自结果 / 最小值与最大值；range不是置信区间。'),
    ('expert.status = pending', '尚未收到专家独立评分；agreement=null表示当前没有可计算的一致性结果。'),
]

limits = [
    '评分独立性：助手参与准备、见过组别映射，可能有评分偏差；仍需一名未参与出题的天文专家独立复核。',
    '材料与题目：E04题面假定表内有Teff/logg，但公开列清单缺少这两个输出列。后续E6核对还发现部分材料把Download栏的文件大小误写成星数。相关失分和依据须重新核查。',
    '推广范围：只有32个独立主测题号和一个被测模型；三次重复并不增加独立题目数。两组信息量与上下文长度不同，比较的是整套材料配置，尚未分离这些因素。',
    '计数复核：数值和科学主张由助手逐条枚举，UNGR/UCR的完整性仍需专家确认。“无来源”不等于该数字一定为假。',
]

md = [
    '# 实验三结果说明｜老师阅读版', '',
    '说明日期：2026-10-08。依据既有结果重新组织说明，未重新采集或修改评分。', '',
    '## 先看结论', '', summary, '', '## 实验是怎样比较的', '',
    '| 项目 | 说明 |', '|---|---|',
]
md.extend(f'| {k} | {v} |' for k,v in design)
md += ['', '## 五项主指标怎样读', '',
       '表中数字是三次独立重复结果的中位数。例如三次为90%、92%、91%，报告91%。以下均为百分比，各指标的分母不同，不能相加成一个总分。', '',
       '| 指标 | 通俗含义 | 判断方向 | A组 | B组 |', '|---|---|---|---:|---:|']
for key,label,meaning,direction in metrics:
    md.append(f'| {label}（{key.upper()}） | {meaning} | {direction} | {pct(val("S-A",key))} | {pct(val("S-B",key))} |')
md += ['',
       '**90.14%不是“90.14%的题完全答对”。** 每次主测共有71个必须说明的关键科学点；A组其中两次命中64个，64÷71=90.14%。一题可以包含多个科学点。必要限定语每次共73项；时序语义相关题共14道。', '',
       f'另按严格的逐回答合格规则，A组三次合格率中位数为{pct(val("S-A","pass_rate"))}，B组为{pct(val("S-B","pass_rate"))}。', '',
       '第六项为人机评分一致性，目前缺少专家评分，不能计算。', '',
       '## 实际错误是什么样的', '',
       '下列片段来自已保存回答，解释沿用当前主评判断，仍待专家复核。', '']
for title,quote,why in examples:
    md += [f'**{title}**', '', f'> {quote}', '', why, '']
md += ['## JSON里容易误解的字段', '', '| 字段 | 实际意思 |', '|---|---|']
md.extend(f'| `{k}` | {v} |' for k,v in json_fields)
md += ['', '## 论文目前可以怎么写', '',
       '“在32道离线科学语义任务、每题三次重复的测试中，deepseek-flash在完整skill材料条件下的关键科学断言命中率中位数为90.14%，普通API包装器条件下为66.20%，相差23.94个百分点。上述结果基于当前助手主评，独立专家复核尚未完成。”', '',
       '应保留“当前助手主评、专家待复核”的限定。不能据此宣称完全消除幻觉、模型已达到专家水平，或把数据归属于未测试的其他模型。', '',
       '## 尚需处理的四件事', '']
md.extend(f'{i}. {v}' for i,v in enumerate(limits,1))
md += ['',
       '## 统计补充与查证位置', '',
       '关键断言命中率差为23.94个百分点；按题号成组重抽10,000次的95%区间为12.68至33.33个百分点。逐题三次多数合格的配对比较中，仅A合格12题、仅B合格0题，精确McNemar双侧p=0.00048828。这些统计依赖当前评分，不能排除评分者偏差。', '',
       '当前主评在B组16份回答中检出红线；A组本轮未检出红线，但仍有关键科学点遗漏与无支撑说法。没有检出红线不等于没有任何错误。', '',
       '结果来源：[FINAL-RESULTS.json](FINAL-RESULTS.json)。完整过程与三次范围：[FINAL-REPORT.md](FINAL-REPORT.md)。材料后续核验：[E6最终报告](../E6-20261007-1791350994158084000/FINAL-REPORT.md)。', '',
       '若老师将担任独立盲评专家，应避免先查看组别结果；实际评分使用另行提供的匿名包。', '',
       f'批次：{result["batch_id"]}。原始JSON SHA-256：{hashlib.sha256(data).hexdigest()}。',
]
markdown='\n'.join(md)+'\n'
(ARCHIVE/'E3-老师阅读版.md').write_text(markdown)
(BASE/'E3-老师阅读版.md').write_text(markdown)

pdfmetrics.registerFont(TTFont('Chinese', '/Library/Fonts/Arial Unicode.ttf'))
ink=colors.HexColor('#19324a'); teal=colors.HexColor('#126b72'); muted=colors.HexColor('#536474')
styles={
    'title': ParagraphStyle('title',fontName='Chinese',fontSize=21,leading=29,textColor=ink,spaceAfter=8,wordWrap='CJK'),
    'sub': ParagraphStyle('sub',fontName='Chinese',fontSize=8.5,leading=13,textColor=muted,spaceAfter=10,wordWrap='CJK'),
    'h': ParagraphStyle('h',fontName='Chinese',fontSize=12,leading=17,textColor=teal,spaceBefore=12,spaceAfter=6,wordWrap='CJK'),
    'body': ParagraphStyle('body',fontName='Chinese',fontSize=9.5,leading=15,textColor=ink,spaceAfter=6,wordWrap='CJK'),
    'small': ParagraphStyle('small',fontName='Chinese',fontSize=8,leading=12,textColor=muted,spaceAfter=5,wordWrap='CJK'),
    'cell': ParagraphStyle('cell',fontName='Chinese',fontSize=8.4,leading=13,textColor=ink,wordWrap='CJK'),
    'head': ParagraphStyle('head',fontName='Chinese',fontSize=8.4,leading=13,textColor=colors.white,wordWrap='CJK'),
}
def P(text,kind='body'):
    return Paragraph(escape(text),styles[kind])
def table(rows,widths):
    t=Table([[P(c,'head' if i==0 else 'cell') for c in row] for i,row in enumerate(rows)],colWidths=widths,hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),ink),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),
        ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.HexColor('#eff5f7'),colors.white]),
        ('LINEBELOW',(0,0),(-1,0),.6,ink),('LINEBELOW',(0,1),(-1,-1),.25,colors.HexColor('#d5e0e6')),
    ]))
    return t

out=BASE/'output/pdf/E3-实验结果说明-老师阅读版.pdf';out.parent.mkdir(parents=True,exist_ok=True)
doc=SimpleDocTemplate(str(out),pagesize=A4,rightMargin=42,leftMargin=42,topMargin=38,bottomMargin=38,
                      title='实验三结果说明 - 老师阅读版',author='E3实验整理',pageCompression=1)
width=A4[0]-84
story=[P('实验三结果说明','title'),P('老师阅读版 | 2026-10-08 | 当前助手主评，独立专家复核待完成','sub'),
       P(summary),P('01  实验怎样比较','h')]
compact=[('组别','本轮提供的材料'),('A组 / 完整skill','完整skill与天文领域材料，提供科学概念、列含义及能力边界。'),
         ('B组 / 普通API包装器','表名、列名和两阶段查询协议。')]
story += [table(compact,[130,width-130]),Spacer(1,7),
          P('两组使用同一个deepseek-flash模型。32道离线题、4道在线题，每题每组独立重复3次，共216份真实回答。下表只用192份离线回答；24份在线回答单独分析。'),
          P('研究的是：给模型完整领域材料，是否能减少科学语义错误和无依据推断？'),P('02  五项主指标，用中文读','h')]
grid=[['指标与判断方向','通俗含义','A组','B组']]
for key,label,meaning,direction in metrics:
    grid.append([label+' / '+direction,meaning,pct(val('S-A',key)),pct(val('S-B',key))])
story += [table(grid,[138,width-252,57,57]),Spacer(1,8),
          P('表中为三次结果的中位数，即排序后居中的数。各指标分母不同，不能相加成为一个总分。','small'),
          P('90.14%代表什么？','h'),
          P('它表示“应说明的关键科学点”命中了90.14%，不是90.14%的题完全答对。每次主测有71个关键科学点；A组其中两次命中64个，64÷71=90.14%。一题可以有多个科学点。'),
          P(f'按更严格的逐回答合格规则，A组三次合格率中位数为{pct(val("S-A","pass_rate"))}，B组为{pct(val("S-B","pass_rate"))}。必要限定语分母每次73项；静态误称时序率分母每次14题。','small'),
          P('第六项“人机评分一致性”暂缺：还没有专家独立评分，不能计算。','small'),PageBreak(),
          P('如何理解错误与结论','title'),P('以下解释依据现有主评记录，未重新运行实验或改动分数。','sub'),
          P('03  三类实际错误','h')]
for title,quote,why in examples:
    story += [P(title),P('回答片段：'+quote,'small'),P(why)]
story += [P('04  JSON中的“通过”和“失败”','h'),
          P('rating.valid=true：评分记录满足字段、证据和反证检查要求；不表示回答全对。scientific_performance.status=FAIL：有回答触发科学红线；不表示实验程序没运行。expert.status=pending：专家复核未完成。'),
          P('median是三次中位数，per_repeat是三次各自结果，range是最小值和最大值；range不是置信区间。','small'),
          P('05  目前能写进论文的表述','h'),
          P('在32道离线科学语义任务、每题三次重复的测试中，deepseek-flash在完整skill材料条件下的关键科学断言命中率中位数为90.14%，普通API包装器条件下为66.20%，相差23.94个百分点。结果基于当前助手主评，独立专家复核尚未完成。'),
          P('06  还需要老师关注什么','h')]
for i,text in enumerate(limits,1):
    story.append(P(str(i)+'. '+text,'small'))
story += [P('统计补充：按题号成组重抽10,000次，关键断言命中率差的95%区间为12.68至33.33个百分点；逐题多数合格的配对检验p=0.00048828。这些数值依赖当前评分，不排除评分者偏差。','small'),
          P('资料依据：同批次FINAL-RESULTS.json与FINAL-REPORT.md；材料问题补充核验见2026-10-07的E6最终报告。更完整的字段说明及原件链接见E3-老师阅读版.md。','small')]
def footer(canvas,document):
    canvas.saveState();canvas.setStrokeColor(colors.HexColor('#d5e0e6'));canvas.line(42,29,A4[0]-42,29)
    canvas.setFont('Chinese',7.5);canvas.setFillColor(muted)
    canvas.drawString(42,17,'E3 | 既有结果说明 | 批次 e3-b5ad6d180c9f42ce')
    canvas.drawRightString(A4[0]-42,17,f'{document.page}')
    canvas.restoreState()
doc.build(story,onFirstPage=footer,onLaterPages=footer)
assert SOURCE.read_bytes()==data
print(json.dumps({'pdf':str(out),'markdown':str(ARCHIVE/'E3-老师阅读版.md'),'source_unchanged':True},ensure_ascii=False))
