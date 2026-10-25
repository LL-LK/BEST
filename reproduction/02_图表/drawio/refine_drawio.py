"""Refine the supplied native draw.io generator, preserving its original layout.
Run this script, then render_drawio.py. All graphics remain editable mxCells.
"""
from pathlib import Path
import json
import generate_drawio as g
OUT=Path(__file__).resolve().parent
g.OUT=OUT
import optimize_reference as visual
visual.install(g)
c1=g.fig1_v50_body_aligned();c2=g.fig2_v50_data_aligned()
c1.title='图1｜BEST-Skill 总体架构';c2.title='图2｜数据准备与评价设计'
# Keep familiar labels and explain operations without exposing implementation names.
R1={
 '(list_catalogs)':'（发现可用星表）','(count)':'（读取命中总数）',
 '(resolve_name)':'（名称转换为坐标）','(fetch_page)':'（获取分页记录）',
 '(cone_search)':'（检索指定天区）','(describe_catalog)':'（字段、波段与单位）',
 '(crossmatch_batch)':'（建立位置对应关系）','分页获取':'分页读取',
 'astro-envelope':'统一结果结构','schema':'结果结构','status':'执行状态',
 'data':'返回数据','data_hash':'内容摘要','provenance':'数据来源','lineage':'步骤关联',
 '（结构定义）':'（统一组织方式）','（状态信息）':'（查询完成情况）','（数据载荷）':'（实际返回记录）',
 '（内容哈希）':'（比较数据内容）','（来源记录）':'（关联原始来源）','（上下游关联）':'（连接处理过程）',
 '提交查询条件，获取 sqlid':'提交查询条件，建立结果集',
 '(Submit query and obtain sqlid)':'(Submit query and create result set)',
 '基于 sqlid 获取计数和分页结果':'读取结果集的计数和分页记录',
 'BEST 会话与 CSRF 令牌':'BEST 原站会话','(BEST Session & CSRF)':'(BEST Session)',
 '网关 Bearer 令牌与配额':'网关授权与配额','(Gateway Bearer Token)':'(Gateway Authorization)',
 'NADC OAuth 2.0':'NADC 身份记录','(NADC OAuth 2.0)':'(NADC Identity)',
 '◆  CSRF 防护':'◆  请求来源验证','(CSRF Protection)':'(Request Verification)',
 '七个原子工具':'七项原子工具',
}
for e in c1.items:
 if e.kind=='label':
  e.text=R1.get(e.text,e.text)
  if e.text in R1.values() and e.text.startswith('（'):e.size=16.5
  if e.text=='(Submit query and create result set)':e.size=14.5
  if e.text=='(Gateway Authorization)':e.size=15.5
  if e.text in ['（字段、波段与单位）','（建立位置对应关系）']:e.size=15
# The inherited outer cards extend below the original viewBox; close their borders.
for e in c1.items:
 if e.kind=='rect' and e.y==175 and e.h==766:e.h=735
# Remove the two short cross-arrows: tools and gateway are parallel entry routes.
c1.items=[e for e in c1.items if not(e.kind=='line' and e.p1 in [(877,409),(902,413)])]
R2={
 'BEST-Skill 数据准备与评测建模':'BEST-Skill 数据准备与评价设计',
 '二、评测建模':'二、评价与统计','题集、答案键与夹具冻结':'任务与评价条件',
 'E1 26题×3次；E2 17场景；E3 32题号×2配置×3次\nE4 35话术+15协议故障；E6 32任务×5次':'E1：26题×3次；E2：21场景×3次；E3：32题×2配置×3次\nE4：35请求场景+15协议场景；E6：32任务×5次',
 '题面、标准答案、评分规则与检验夹具在正式运行前冻结':'运行前固定题目、标准答案、数据与评分条件',
 '答案键权限隔离':'标准答案隔离','答案键与模型、执行器分离保存':'标准答案与被测模型、执行器分离保存',
 '置于模型与执行器不可读的独立权限域':'模型依据题目与数据独立生成回答',
 '执行留痕与状态归档':'运行记录与数据条件','实站查询、冻结回包与压力样本按批次执行':'分别使用实站快照、固定回包和压力数据',
 '逐次保留请求、返回、最终回答、工具轨迹与状态':'保存请求、工具操作、返回数据与最终回答',
 '结构化解析与字段核验':'结果整理与有效性判断',
 '评分前解析工具名、调用参数、数值字段、结果行集与运行状态':'统一参数单位、数据表示和结果状态',
 '失败记录保留在相应分母中，不因补测而消失':'按预设条件识别有效记录和适用任务',
 '五层证据框架':'五组评价任务','格式 E1':'映射 E1','判分分工':'结果评价',
 '结构化字段由程序逐项核验；科学断言按公开量规主评':'数据操作按标准答案核验；科学陈述按量规评分',
 '工具选择、参数、轨迹与最终文本分别计分':'工具选择、参数设置与回答内容分别评价',
 '独立判据与分母':'指标与统计单位','各组使用独立判据、评分器与分母':'按任务、断言或场景确定统计单位',
 '不合并为单一总体能力分数':'各项指标分别对应其评价目标',
 '统计推断与重复一致性':'组间比较与运行一致性',
 '配对题号 Bootstrap 95% CI；二元结果精确 McNemar':'配对题目估计 95% 置信区间与组间差异',
 '重复一致性按题计算 TSC / PAC_call / RDC / FCC，再取宏平均':'比较工具、参数、数据和核心结论的重复一致性',
 '正式运行前冻结题集、夹具与答案键；各组按独立判据与分母分别报告，不合并为总体能力分数。':'固定研究条件，分别评价数据访问、科学解释与重复运行稳定性。',
}
for e in c2.items:
 if e.kind=='label':
  e.text=R2.get(e.text,e.text)
  if e.text.startswith('E1：26题'):e.size=12.9;e.h=44
  if e.text.startswith('运行前固定题目'):e.size=17
  if e.text.startswith('数据操作按标准答案'):e.size=17
  if e.text.startswith('比较工具、参数'):e.size=17
  if e.text.startswith('固定研究条件，'):e.size=26
  if e.text in ['结果整理与有效性判断','组间比较与运行一致性']:e.size=24
visual.refine(c1,c2,g)
from align_architecture import align
align(c2)
from polish_fig2 import compose
c2=compose(g)
for c,stem in [(c1,'fig1_architecture'),(c2,'fig2_data_model')]:g.save_canvas(c,stem)
g.all_file([c1,c2],OUT/'BEST_Skill_图1图2_可编辑.drawio')
checks=[]
for c in [c1,c2]:
 checks.append({'name':c.title,'vertices':sum(e.kind!='line' for e in c.items),'connectors':sum(e.kind=='line' for e in c.items),'canvas':[c.width,c.height]})
(OUT/'diagram_validation.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
print('Refined supplied native draw.io source:',checks)
