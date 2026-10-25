"""Recompose Figure 2 using the supplied native Canvas and editable mxCells.

Contract: show how frozen inputs become separately scoped evidence, rather than
suggesting that heterogeneous experiments yield one overall ability score.
Schematic-led, two lanes; Python generator and renderer; vector PDF/SVG + PNG.
"""

def compose(g):
    c = g.Canvas('图2｜数据准备与评价设计', 1400, 1050)
    navy, muted = '#203B56', '#52687D'
    blue, orange = '#3279AD', '#AB733D'
    c.label('数据准备与评价设计', 40, 20, 1320, 60, 34, navy, True)
    c.label('固定研究条件 → 保存运行证据 → 按独立判据评价', 40, 80, 1320, 40, 20, muted)
    lanes = [(36, blue, '#F0F6FB', 'a  数据准备', '任务、数据与参考答案'),
             (718, orange, '#FBF5ED', 'b  评价与统计', '六组任务分别回答不同问题')]
    for x, color, fill, title, subtitle in lanes:
        c.rect(x, 145, 646, 65, fill, 'none', 0, 12)
        c.label(title, x+20, 150, 250, 30, 24, color, True, 'left')
        c.label(subtitle, x+270, 157, 350, 32, 18, muted, False, 'right')
    left = [
        ('任务与数据条件', ['E1：28 题 × 3 箱；E2：21 场景 × 3 次',
                       'E3：32 题 × 2 配置 × 3 次；E4：35＋15 场景',
                       'E5：1024 主验证＋96 诊断来源，各两组',
                       'E6：32 任务 × 5 次；不同批次分别归档'], 'docicon'),
        ('参考答案与可见材料', ['分别保留题面、工具说明和参考答案',
                           '记录模型可见面与权限边界',
                           'E1 跨箱可读风险与复跑情况单列'], 'lockicon'),
        ('运行记录与数据来源', ['区分实站快照、固定回包和压力样本',
                           '保存请求、回答、工具轨迹与状态',
                           '区分答案中的调用计划与实际执行'], 'dbicon'),
        ('结果整理与完整性核验', ['统一坐标、参数单位和数据表示',
                             '核对记录身份、来源摘要与归档完整性',
                             '失败保留；完成归档不等于任务成功'], 'checked_dbicon')]
    right = [
        ('六组评价目标', ['E1  工具映射      E2  查询契约      E3  科学语义',
                       'E4  请求边界      E5  独立对照      E6  运行一致性',
                       '每组保留独立统计单位与适用范围'], 'levelsicon'),
        ('程序核验与语义评价', ['工具、参数、字段与行集由程序核验',
                           '科学陈述按证据量规评分',
                           '人工待复核项与程序指标分别标记'], 'barsicon'),
        ('指标、重复与分母', ['按任务、来源、断言或场景确定分母',
                           'E1：逐箱均值与同题同维中位汇总分列',
                           '主验证、诊断、开发与历史批次不混合'], 'nodesicon'),
        ('组间比较与运行一致性', ['按独立任务或来源配对估计区间',
                             'E5：精确 McNemar；次要检验 Holm 校正',
                             'E6：分别比较工具、参数、数据与结论'], 'mini_charticon')]
    for x, color, fill, _, _ in lanes:
        rows = left if x == 36 else right
        for i, (title, lines, icon) in enumerate(rows):
            y = 232 + i*177
            c.rect(x, y, 646, 153, '#FFFFFF', '#D8E3EC', 1.2, 10)
            c.rect(x+1, y+1, 5, 151, color, 'none', 0)
            c.circle(x+34, y+28, 15, fill, 'none', 0)
            c.label(str(i+1), x+20, y+12, 28, 30, 18, color, True)
            c.label(title, x+63, y+11, 555, 38, 24, navy, True, 'left')
            getattr(c, icon)(x+23, y+76, .85, color)
            for j, line in enumerate(lines):
                c.label(line, x+83, y+57+j*23, 540, 27, 18, muted, False, 'left')
            if i < 3:
                c.line(x+323, y+156, x+323, y+173, '#A7B8C7', 1.5, arrow=True)
    c.rect(36, 964, 1328, 60, '#EFF6F2', 'none', 0, 10)
    c.label('从条件、记录到结论保留证据关联；各组结果分别报告',
            58, 975, 1284, 38, 23, '#376A54', True)
    return c
