# -*- coding: utf-8 -*-
"""BEST-Skill 论文柱状图重绘（渐变 + 浅立体 + 虚线网格 + 芯片图例）。

依赖 chartkit.py / svgkit.py。运行后输出 fig_c1..fig_c4 的 .svg。
数据来源：上级目录 source_data.json；源文件保持原包的 SVG 工具与渐变绘图机制。

v2 版式原则：绘图区尽量撑满画布、外围留白压到最小，柱体加粗以提升可读性。
"""
import os, sys, json
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from svgkit import text
from chartkit import (Canvas, txt, frame, gridline_h, gridline_v, tick_left,
                      tick_bottom, vbar3d, hbar3d, hdot, legend_chip,
                      legend_title, _tw, RAMPS, INK_AXIS, INK_TICK, INK_VAL,
                      GRID, lighten, darken, DX, DY)

OUT = os.path.dirname(os.path.abspath(__file__))
NAVY = "#173763"
DATA = json.loads((Path(__file__).resolve().parent.parent / "source_data.json").read_text(encoding="utf-8"))

# 画布宽度固定 1200（导出时按论文单栏 6.941 cm 落版）
W = 1200
# 绘图区左右边界：左留出刻度/轴标题，右留出立体面偏移
X0S, X1S = 205, 1160


def lin(v, v0, v1, a0, a1):
    return a1 - (v - v0) / (v1 - v0) * (a1 - a0)


def linx(v, v0, v1, a0, a1):
    return a0 + (v - v0) / (v1 - v0) * (a1 - a0)


def ylabel(cv, x, y, s, size=20, fill=INK_AXIS):
    cv.add(f'<g transform="translate({x},{y}) rotate(-90)">'
           + text(0, 0, s, size=size, fill=fill, weight="700",
                  anchor="middle")
           + '</g>')


def title(cv, x, y, s, size=28):
    txt(cv, x, y, s, size=size, fill=NAVY, weight="800", ls=0.6)


def panel(cv, x, y, s):
    cv.add(f'<rect x="{x}" y="{y - 20}" width="30" height="30" rx="7" '
           f'fill="{NAVY}"/>')
    txt(cv, x + 15, y + 2, s, size=19, fill="#FFFFFF", weight="800",
        anchor="middle")


def note(cv, x, y, s, size=19):
    txt(cv, x, y, s, size=size, fill="#4A5F78", weight="600")


def vlabels(cv, xc, ytop, s, size=22):
    txt(cv, xc, ytop - DY - 13, s, size=size, fill=INK_VAL, weight="800",
        anchor="middle")


def hbar_value(cv, bx0, wlen, yc, s, size=17):
    """value label inside the bar when it fits, otherwise just outside"""
    tw = _tw(s, size)
    if wlen > tw + 46:
        txt(cv, bx0 + wlen - 15, yc + size * 0.36, s, size=size,
            fill="#FFFFFF", weight="800", anchor="end")
    else:
        txt(cv, bx0 + wlen + DX + 13, yc + size * 0.36, s, size=size,
            fill=INK_VAL, weight="700")


def save(cv, name):
    p = os.path.join(OUT, name + ".svg")
    open(p, "w", encoding="utf-8").write(cv.svg())
    print("wrote", p)


# ===========================================================================
# 图 3 / E1  三批答案的工具映射加权分
# ===========================================================================
def chart_e1():
    cv = Canvas(W, 1150)
    title(cv, 70, 58, "E1 工具映射：综合得分与六项指标")
    panel(cv, 70, 112, "A")
    txt(cv, 130, 112, "加权总分", size=22, fill=NAVY, weight="800")
    X0,X1=330,1160
    def row(y,value,label,gate,ramp,h=58):
        txt(cv,X0-20,y+h/2+7,label,size=18,fill=INK_TICK,weight="600",anchor="end")
        wlen=(X1-X0)*value
        hbar3d(cv,X0,y,wlen,h,ramp)
        hbar_value(cv,X0,wlen,y+h/2,f"{value:.4f}",size=19)
        gx=X0+(X1-X0)*gate
        for ya,yb in [(y-15,y-4),(y+h+4,y+h+15)]:
            cv.add(f'<line x1="{gx}" y1="{ya}" x2="{gx}" y2="{yb}" stroke="{NAVY}" stroke-width="3.2"/>')
    def grid(ya,yb):
        for v in [0,.25,.5,.75,1]:
            x=X0+(X1-X0)*v;gridline_v(cv,ya,yb,x);tick_bottom(cv,yb,x,f"{v:.2f}")
        frame(cv,X0,ya,X1, yb)
    grid(164,290);row(195,DATA['E1']['weighted'],'28 题·三箱均值',.9,'teal',58)
    panel(cv,70,400,'B');txt(cv,130,400,'分维度得分',size=22,fill=NAVY,weight='800')
    grid(445,1030)
    labels=['工具集合匹配','参数正确率','单位转换正确率','冗余调用控制','澄清','拒绝']
    gates=[.9,.85,1,.9,1,1]
    for i,(k,label,g) in enumerate(zip(DATA['E1']['dims'],labels,gates)):
        row(470+i*94,DATA['E1']['dims'][k],f"{label} (n={DATA['E1']['n'][k]})",g,'teal' if i%2==0 else 'peri',55)
    txt(cv,(X0+X1)/2,1110,'深蓝标记为参考线；n 为各箱适用任务数',size=18,fill=INK_TICK,anchor='middle')
    save(cv,'fig_c1_E1_batches')


# ===========================================================================
# 图 4 / E3  科学语义忠实度：主指标与五项辅助指标
# ===========================================================================
def chart_e3():
    # A、B 两个面板使用同一套左右边界（X0S..X1S），上下对齐、不留空档
    cv = Canvas(W, 1290)
    title(cv, 70, 58, "E3 科学语义忠实度：主指标与五项辅助指标")

    X0, X1 = X0S, X1S
    CXM = (X0 + X1) / 2

    # ---------------- panel A
    panel(cv, 70, 112, "A")
    txt(cv, CXM, 116, "差值 +23.94 个百分点", size=22, fill=NAVY, weight="800",
        anchor="middle")
    txt(cv, CXM, 146, "95% CI 12.68–33.33 个百分点", size=15.5,
        fill="#4A5F78", weight="600", anchor="middle")

    AY0, AY1 = 168, 520          # A 面板压扁，把高度让给 B
    for i in range(5):
        v = i * 25
        y = lin(v, 0, 100, AY0, AY1)
        gridline_h(cv, X0, X1, y)
        tick_left(cv, X0, y, str(v))
    frame(cv, X0, AY0, X1, AY1)
    pa = [("完整配置  S-A", DATA["E3"]["medians"]["S-A"]["sfa"]*100, "teal"), ("基础包装器  S-B", DATA["E3"]["medians"]["S-B"]["sfa"]*100, "peri")]
    slot = (X1 - X0) / 2
    for i, (lab, v, ramp) in enumerate(pa):
        xc = X0 + slot * (i + 0.5)
        bw = 330
        ytop = lin(v, 0, 100, AY0, AY1)
        vbar3d(cv, xc - bw / 2, ytop, bw, AY1, ramp)
        vlabels(cv, xc, ytop, f"{v:.2f}%")
        tick_bottom(cv, AY1, xc, lab, size=19)
    ylabel(cv, 70, (AY0 + AY1) / 2, "关键科学断言命中率（%）")

    # ---------------- panel B
    panel(cv, 70, 611, "B")
    lx = 650
    lx += legend_chip(cv, lx, 605, "完整配置  S-A", "teal", size=18)
    legend_chip(cv, lx, 605, "基础包装器  S-B", "peri", size=18)

    BX0, BX1, BY0, BY1 = X0S, X1S, 644, 1180   # B 面板高度最大化
    for i in range(5):
        v = i * 25
        x = linx(v, 0, 100, BX0, BX1)
        gridline_v(cv, BY0, BY1, x)
        cv.add(f'<line x1="{x}" y1="{BY1}" x2="{x}" y2="{BY1 + 7}" '
               f'stroke="{INK_AXIS}" stroke-width="1.8"/>')
        txt(cv, x, BY1 + 30, str(v), size=18, fill=INK_TICK, anchor="middle",
            weight="600")
    frame(cv, BX0, BY0, BX1, BY1)

    # 行标签用「空格 + 箭头」替代全角括号，宽度收窄后可与 A 面板同一起点对齐
    names=['无来源数值 ↓','无支撑主张 ↓','时间序列误述 ↓','必要限定语 ↑','严格合格率 ↑']
    keys=['ungr','ucr','slr','rqc','pass_rate']
    rows=[(name,DATA['E3']['medians']['S-A'][k]*100,DATA['E3']['medians']['S-B'][k]*100) for name,k in zip(names,keys)]
    gh = (BY1 - BY0) / len(rows)
    bh, bg = 40, 16
    for i, (lab, va, vb) in enumerate(rows):
        yc = BY0 + gh * (i + 0.5)
        txt(cv, BX0 - 16, yc + 7, lab, size=16, fill=INK_TICK, anchor="end",
            weight="600")
        for j, (v, ramp) in enumerate([(va, "teal"), (vb, "peri")]):
            y = yc - bh - bg / 2 + j * (bh + bg)
            wlen = linx(v, 0, 100, BX0, BX1) - BX0
            if v > 0: hbar3d(cv, BX0, y, wlen, bh, ramp)
            hbar_value(cv, BX0, wlen, y + bh * 0.5, f"{v:.1f}", size=17)
    txt(cv, CXM, BY1 + 82, "比例（%）", size=21, fill=INK_AXIS,
        weight="700", anchor="middle")
    save(cv, "fig_c2_E3_semantics")


# ===========================================================================
# 图 5 / E4  请求边界处置结果
# ===========================================================================
def chart_e4():
    cv = Canvas(W, 1150)
    title(cv, 70, 58, "E4 请求边界处置结果")

    # A、B 面板同宽同起点
    AX0, AX1 = 255, X1S
    CXM = (AX0 + AX1) / 2

    # ---------------- panel A
    panel(cv, 70, 112, "A")
    AY0, AY1 = 150, 430
    for i in range(5):
        v = i * 25
        x = linx(v, 0, 100, AX0, AX1)
        gridline_v(cv, AY0, AY1, x)
        cv.add(f'<line x1="{x}" y1="{AY1}" x2="{x}" y2="{AY1 + 7}" '
               f'stroke="{INK_AXIS}" stroke-width="1.8"/>')
        txt(cv, x, AY1 + 30, str(v), size=18, fill=INK_TICK, anchor="middle",
            weight="500")
    frame(cv, AX0, AY0, AX1, AY1)
    ga = [('协议故障场景',100.,'15/15  •  100.00%','teal'),
          ('自然语言请求',DATA['E4']['language']['correct']/DATA['E4']['language']['total']*100,'25/35  •  71.43%','peri')]
    gh = (AY1 - AY0) / 2
    for i, (lab, v, tag, ramp) in enumerate(ga):
        yc = AY0 + gh * (i + 0.5)
        h = 78
        txt(cv, AX0 - 18, yc + 8, lab, size=18.5, fill=INK_TICK, anchor="end",
            weight="600")
        wlen = linx(v, 0, 100, AX0, AX1) - AX0
        hbar3d(cv, AX0, yc - h / 2, max(wlen, 2), h, ramp)
        hbar_value(cv, AX0, wlen, yc, tag, size=18)
    txt(cv, CXM, AY1 + 82, "处置正确率（%）", size=21,
        fill=INK_AXIS, weight="700", anchor="middle")

    # ---------------- panel B
    panel(cv, 70, 566, "B")
    BX0, BX1 = AX0, AX1
    BY0, BY1 = 600, 1040
    for i in range(5):
        v = i * 25
        x = linx(v, 0, 100, BX0, BX1)
        gridline_v(cv, BY0, BY1, x)
        cv.add(f'<line x1="{x}" y1="{BY1}" x2="{x}" y2="{BY1 + 7}" '
               f'stroke="{INK_AXIS}" stroke-width="1.8"/>')
        txt(cv, x, BY1 + 30, str(v), size=18, fill=INK_TICK, anchor="middle",
            weight="600")
    frame(cv, BX0, BY0, BX1, BY1)
    gb = [(c['label'],c['correct']/c['total']*100,c['total'],'teal' if i%2==0 else 'peri') for i,c in enumerate(DATA['E4']['categories'])]
    gh = (BY1 - BY0) / len(gb)
    h = 56
    for i, (lab, v, n, ramp) in enumerate(gb):
        yc = BY0 + gh * (i + 0.5)
        txt(cv, BX0 - 18, yc + 8, lab, size=18, fill=INK_TICK, anchor="end",
            weight="600")
        wlen = linx(v, 0, 100, BX0, BX1) - BX0
        hbar3d(cv, BX0, yc - h / 2, max(wlen, 2), h, ramp)
        hbar_value(cv, BX0, wlen, yc, f"{v:.2f}%  •  n={n}", size=17.5)
    txt(cv, CXM, BY1 + 82, "处置正确率（%）", size=21,
        fill=INK_AXIS, weight="700", anchor="middle")
    save(cv, "fig_c3_E4_disposition")


# ===========================================================================
# 图 6 / E6  原批次内条件一致性（题号 Bootstrap 95% CI）
# ===========================================================================
def chart_e6():
    cv = Canvas(W, 768)
    title(cv, 70, 58, "E6 重复运行一致性")
    legend_title(cv, 925, 46, "teal", kind="dot")
    txt(cv, 955, 60, "固定回包重放", size=17, fill=INK_TICK, weight="600")

    X0, X1, Y0, Y1 = 150, X1S, 132, 696
    V0, V1 = 0.55, 1.07
    ticks = [0.6, 0.7, 0.8, 0.9, 1.0]
    for v in ticks:
        y = lin(v, V0, V1, Y0, Y1)
        gridline_h(cv, X0, X1, y)
        tick_left(cv, X0, y, f"{v:.1f}")
    frame(cv, X0, Y0, X1, Y1)

    metrics = ["TSC", "PAC", "RDC", "FCC"]
    keys=['TSC','PAC_call','RDC','FCC']
    r3=tuple(DATA['E6'][k]['point'] for k in keys)
    r3lo=tuple(DATA['E6'][k]['ci'][0] for k in keys)
    r3hi=tuple(DATA['E6'][k]['ci'][1] for k in keys)

    slot = (X1 - X0) / len(metrics)
    cap = 19
    for i, m in enumerate(metrics):
        xc = X0 + slot * (i + 0.5)
        tick_bottom(cv, Y1, xc, m, size=20)
        for k, (vals, los, his, ramp, off) in enumerate(
                [(r3, r3lo, r3hi, "teal", 0.0)]):
            x = xc + off * slot
            yv = lin(vals[i], V0, V1, Y0, Y1)
            ylo = lin(los[i], V0, V1, Y0, Y1)
            yhi = lin(his[i], V0, V1, Y0, Y1)
            b, t = RAMPS[ramp]
            cv.add(f'<line x1="{x}" y1="{yhi}" x2="{x}" y2="{ylo}" '
                   f'stroke="{t}" stroke-width="3.4" stroke-linecap="round"/>')
            cv.add(f'<line x1="{x - cap}" y1="{yhi}" x2="{x + cap}" y2="{yhi}" '
                   f'stroke="{t}" stroke-width="3.4" stroke-linecap="round"/>')
            cv.add(f'<line x1="{x - cap}" y1="{ylo}" x2="{x + cap}" y2="{ylo}" '
                   f'stroke="{t}" stroke-width="3.4" stroke-linecap="round"/>')
            hdot(cv, x, yv, ramp, r=10)
            txt(cv, x + 26, yv - 16, f"{vals[i]:.4f}",
                size=16, fill=darken(t, 0.12), weight="700", anchor="start")
    ylabel(cv, 70, (Y0 + Y1) / 2, "重复一致性（95% 置信区间）", size=19)
    save(cv, "fig_c4_E6_repeatability")


if __name__ == "__main__":
    chart_e1()
    chart_e3()
    chart_e4()
    chart_e6()
