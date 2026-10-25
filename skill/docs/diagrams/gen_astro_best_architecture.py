#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_astro_best_architecture.py
------------------------------
astro-best (BEST 数据源主理) 架构图 —— 多视图拆分版 (版式已按视觉复核收紧)。

结构 (4 个独立视图 / 多页 .drawio):
  Page 1  架构总览 · 三域拓扑与联系     (Overview & Domain Topology)
  Page 2  域 ① 主理能力域与委派路由     (Data-Source Surface & Delegation)
  Page 3  域 ② 五状态机执行链与阻断门禁  (State Machine, Gates & Envelope)
  Page 4  域 ③ 降级 · 错误码 · 证据存证  (Fallback, Error Codes & Evidence)

约定:
  - 图内不标注任何文件/目录路径, 只保留语义化组件名与标识符。
  - 子视图顶部带三域导航条, 高亮当前域, 建立视图间"联系"。
  - 视觉语言沿用既有模板: Slate 中性底 + 蓝/绿/橙/红/紫/青/靛 语义色;
    全部正交连线; 零 emoji。
  - 版式规则: 卡片高度按内容行数核定 (行高 12px≈20 / 11.5px≈17 / 11px≈16.5,
    上下内边距各 9px), 目标填充率 ≥ 70%, 避免大面积空白。

构建器: drawio-diagram-author skill 的 drawio_builder.py (纯 stdlib)

拆分说明 (budget doc §3.5 已登记方案): 字体/配色/三域导航标签/四页的坐标、
卡片文案、连线定义等纯数据已全部抽到 layout_data.py 的 ARCHITECTURE_* 表
(原脚本里按循环生成的组件卡/路由表/状态机/数据流/降级协议/证据清单与两条
传递链已物化为显式行), 本文件只保留渲染代码 (样式构造 + 表驱动组装 +
导航条)。拆分硬性验收: 生成产物 (.drawio) 逐字节不变。
"""
from __future__ import annotations

# 标准库组:
#   os     —— F1: 读环境变量 ASTRO_BEST_DRAWIO_BUILDER_DIR (builder 目录可配置)
#   sys    —— 把 drawio_builder 所在目录注入 sys.path (第三方脚本, 不在本仓)
#   pathlib—— 定位输出目录 (本文件所在目录) 与 builder 目录
import os
import sys
from pathlib import Path

# 本地第三方脚本: drawio-diagram-author skill 的构建库 (纯 stdlib 实现,
# 输出原生 .drawio XML)。该 skill 装在用户目录下, 不属于本仓库。
# F1: 目录可配置 — 环境变量 ASTRO_BEST_DRAWIO_BUILDER_DIR 优先, 未设时回落
# 本机安装位置 (保留以使本机仍可跑); 换机器只需设一个环境变量, 不必改代码。
BUILDER_DIR = os.environ.get("ASTRO_BEST_DRAWIO_BUILDER_DIR") or (  # env 优先, 未设时回落本机 skill 安装位置
    r"<USER_HOME>\.agents\skills\drawio-diagram-author\scripts")
sys.path.insert(0, BUILDER_DIR)  # 构建库不在本仓, 只能靠 sys.path 挂进来
from drawio_builder import DrawioFile  # noqa: E402

# 本目录共用落盘出口: 落盘后剥离构建库写死的 host/agent/version 工具元数据
# (铁律 3 不容三段式版本号字面量, 理由见图目录 drawio_io.py 模块 docstring)
from drawio_io import save_clean  # noqa: E402

# 布局数据组: 本图专用的字体/色板/三域导航标签/四页元素有序表 (纯数据, 无逻辑,
# 表结构见 layout_data.py 模块 docstring)。常量是数据不是接口, 直接引用;
# ARCHITECTURE_DOMAINS 以 DOMAINS 别名引入, 保持 add_nav() 与原版一致
from layout_data import ARCHITECTURE_DOMAINS as DOMAINS  # noqa: E402
from layout_data import (  # noqa: E402
    ARCHITECTURE_P1,                                                                                # 第一页数据 (Page 1)
    ARCHITECTURE_P2,                                                                                # 第二页数据
    ARCHITECTURE_P3,                                                                                # 第三页数据
    ARCHITECTURE_P4,                                                                                # 第四页数据
    ARCHITECTURE_PALETTE,                                                                           # 配色表
    FF,                                                                                             # 字体
)


def st(kind: str, align: str = "left", valign: str = "top", size: float = 12.0,
       bold: bool = False, sl: int = 16, sr: int = 16, stp: int = 9, sbp: int = 9) -> str:          # 节点样式的全部可调参数集中在一处签名里
    """按语义色键生成 draw.io 节点样式串 (填充/字体/描边/对齐/内边距)。

    Args:
        kind: ``ARCHITECTURE_PALETTE`` 的语义色键 (blue/green/amber/...)。
        align: 水平对齐 (left/center/right)。
        valign: 垂直对齐 (top/middle/bottom)。
        size: 字号 (px)。
        bold: 是否加粗。
        sl/sr: 左/右内边距 (px)。
        stp/sbp: 上/下内边距 (px) —— 与模块头"卡片高度按内容行数核定"
            的版式规则配套, 调这里会改变卡片实际占高。

    Returns:
        draw.io style 属性串。
    """
    fill, font, stroke, sw = ARCHITECTURE_PALETTE[kind]  # 色键解包成四元组, 键不存在即 KeyError 而不是静默中性色
    s = (                                                                                           # 样式串拼装起点
        f"whiteSpace=wrap;html=1;fontFamily={FF};rounded=1;arcSize=6;"
        f"fillColor={fill};fontColor={font};strokeColor={stroke};strokeWidth={sw};"
        f"fontSize={size};align={align};verticalAlign={valign};"
        f"spacingLeft={sl};spacingRight={sr};spacingTop={stp};spacingBottom={sbp};"
    )
    if bold:                                                                                        # 加粗时另走一套内边距
        s += "fontStyle=1;"
    return s


def container_style() -> str:
    """生成泳道容器样式串 (swimlane): 标题栏 + 中性底 + 不可折叠。

    ``collapsible=0`` 是刻意的: 架构图要一眼看全, 折叠态会让读者以为
    内容缺失。``startSize=34`` 是标题栏高度。
    """
    return (
        f"swimlane;whiteSpace=wrap;html=1;fontFamily={FF};rounded=1;arcSize=4;"
        "fillColor=#F1F5F9;fontColor=#0F172A;strokeColor=#CBD5E1;strokeWidth=1.5;"
        "startSize=34;fontSize=13;fontStyle=1;collapsible=0;align=center;"
    )


def rhombus_style() -> str:
    """生成菱形 (判定节点) 样式串 —— 专供 Page 3 的两道阻断门禁使用。

    用菱形而不是矩形, 是流程图的惯例语义: 菱形 = 判定/分支, 矩形 = 处理。
    门禁是判定节点, 混用形状会让读者误读为普通步骤。
    """
    return (
        f"rhombus;whiteSpace=wrap;html=1;fontFamily={FF};fillColor=#FFF7ED;fontColor=#9A3412;"
        "strokeColor=#EA580C;strokeWidth=1.8;fontSize=12;fontStyle=1;align=center;verticalAlign=middle;"
    )


def edge_style(color: str = "#334155", font: str = "#0F172A") -> str:
    """生成连线样式串: 纯正交 Manhattan 走线 (禁曲线, 防穿框)。

    Args:
        color: 连线颜色 (按语义分流: 蓝=数据流, 红=失败/降级, 紫=审计回写)。
        font: 连线标签字体色。

    Returns:
        draw.io edge style 属性串。

    Note:
        ``orthogonalEdgeStyle`` 是硬要求: 曲线连接在密集卡片间极易穿过
        无关卡片, 正交走线才可人工核对。调用方常在返回值后追加
        ``exitX/exitY/entryX/entryY`` 锚点约束。
    """
    return (
        "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;"
        f"strokeColor={color};strokeWidth=1.8;fontSize=11;fontColor={font};"
        f"labelBackgroundColor=#FFFFFF;fontFamily={FF};"
    )


# 深色大标题条样式: 只用于每页顶部的总标题 (与 banner 区分层级)
TITLE_STYLE = (  # 深色大标题条: 只用于每页顶部总标题, 与 banner 区分层级
    f"whiteSpace=wrap;html=1;fontFamily={FF};rounded=1;fillColor=#0F172A;fontColor=#FFFFFF;"
    "strokeColor=#1E293B;strokeWidth=2;fontSize=15;fontStyle=1;align=center;verticalAlign=middle;"
    "spacingLeft=16;spacingRight=16;spacingTop=8;spacingBottom=8;"
)


def node_style(spec: tuple) -> str:
    """把布局数据行里的样式规格解析成 draw.io style 属性串。

    Args:
        spec: ``(色键, align, valign, bold)`` 四元组。色键 ``title`` /
            ``rhombus`` 是哨兵, 分别映射 TITLE_STYLE / rhombus_style();
            其余色键走 st(), 字号与内边距用 st() 缺省值 —— 与原脚本
            逐卡调用 st() 的效果一致。

    Returns:
        draw.io style 属性串。
    """
    kind, align, valign, bold = spec  # 四元组解包, 顺序与 layout_data 里的行一致
    if kind == "title":  # title 是哨兵色键, 走独立样式而非 st()
        return TITLE_STYLE
    if kind == "rhombus":  # rhombus 同理, 绕过 st() 才不会被圆角参数改形
        return rhombus_style()
    return st(kind, align=align, valign=valign, bold=bold)  # 其余色键走统一构造函数, 字号与内边距用 st 缺省值


def add_nav(p, y: float, active: int, x0: float = 100.0, total_w: float = 2200.0) -> None:
    """在子视图顶部画三域导航条 —— 建立视图间联系, 高亮当前域。

    Args:
        p: 目标页 (DrawioPage)。
        y: 导航条纵坐标。
        active: 当前高亮的域索引 (0/1/2)。
        x0: 导航条左起点。
        total_w: 导航条总宽 (三等分, 间隙 gap=21px)。

    Note:
        多页图没有原生"页内跳转", 导航条是纯视觉手段: 让读者知道自己在
        四页里的哪一页、以及还有哪两个域没看。高亮用 indigo, 非当前用 muted。
    """
    gap = 21.0  # 三等分后的固定间隙; 改它会整体挪动三域标签
    w = (total_w - 2 * gap) / 3.0                                                                   # 三列均分: 总宽减去两处间隔再除以列数
    for i, name in enumerate(DOMAINS):  # 域标签来自 layout_data, 脚本不写死文案
        on = i == active  # 高亮判据: 索引相等即为当前域
        p.add_node(                                                                                 # 加节点
            f"nav_{i}", x=x0 + i * (w + gap), y=y, width=w, height=42,
            style=st("indigo" if on else "muted", align="center", valign="middle",
                     size=12.5, bold=on, sl=10, sr=10, stp=5, sbp=5),                               # 表头节点字号略小, 内边距也收窄
            value=f"<b>{'▸ ' if on else ''}{name}{'　（当前视图）' if on else ''}</b>",  # 当前域加箭头与后缀, 非当前域只留裸名
        )


def render_page(page, elements: list) -> None:
    """按 ARCHITECTURE_Pn 有序表渲染一页的导航条/容器/节点/连线。

    行序即原生成代码的添加顺序, 必须保持一致: drawio_builder 序列化时按
    容器 -> 节点 -> 连线 分组输出, 组内顺序由添加顺序决定, 改序会改变
    .drawio 产物字节 (拆分验收要求逐字节不变)。

    Args:
        page: 目标页 (DrawioPage)。
        elements: 该页的有序元素表 (layout_data.ARCHITECTURE_P1..P4)。
    """
    for item in elements:  # 元素表是唯一输入, 循环体里不新增任何坐标
        tag = item[0]  # 首字符是类型标签: V/C/N/E 四选一
        if tag == "V":
            add_nav(page, y=115, active=item[1])  # y 固定 115: 三页导航条必须同高对齐
        elif tag == "C":
            _, cid, title, x, y, w, h = item
            page.add_container(cid, title, x=x, y=y, width=w, height=h,                             # 加容器
                               style=container_style())                                             # 容器样式统一入口
        elif tag == "N":
            _, nid, x, y, w, h, spec, value = item  # 节点行比容器多一个样式规格与文案
            page.add_node(nid, x=x, y=y, width=w, height=h,                                         # 加节点
                          style=node_style(spec), value=value)                                      # 节点样式由 spec 决定
        else:  # "E" 连线: 正交走线 + 数据行里的显式锚点后缀
            _, eid, src, tgt, value, color, font, anchor = item  # 连线行八元组, anchor 拼在 style 尾部
            page.add_edge(eid, src, tgt, value=value,  # 锚点后缀决定出入边方向, 缺了线会从卡片中心乱穿
                          style=edge_style(color, font) + anchor)                                   # 边样式 = 线型 + 字色 + 锚点


def build() -> DrawioFile:
    """组装四页架构图并返回 DrawioFile 文档对象 (不落盘)。

    四页的分工 (数据来源全部是 SKILL.md / architecture.md 的既有文字,
    本脚本只做"文字 -> 图面"的转写, 不发明新事实):
      - Page 1 架构总览: 三域拓扑 + 域间联系 + 图例 + 三条不可让步约束;
      - Page 2 域①: 能力组件清单 (提供什么/边界/关键点) + 委派路由表;
      - Page 3 域②: 五状态机 + 阶段数据流 + 双门槛门禁 + 双态信封;
      - Page 4 域③: 优雅降级协议 + 错误码契约 + 不可变证据 + 完成自检。

    本函数是纯渲染代码: 各页元素 (坐标/文案/连线, 含原内容循环物化后的
    显式行) 全部来自 layout_data.py 的 ARCHITECTURE_Pn 表, 只按表驱动
    drawio_builder, 不在这里写任何坐标或文案。

    Returns:
        未保存的 DrawioFile; 由 ``__main__`` 调 ``doc.save()`` 落盘。
    """
    doc = DrawioFile("astro-best-legacy-architecture.drawio")  # 产物名与输出目录无关, env 只改落到哪不改叫什么

    # Page 1 —— 架构总览 · 三域拓扑与联系
    # 布局: 顶部总标题 + 使命横幅 -> 输入/交付产物 -> 三个并排能力域容器
    #       -> 域间双向连线 -> 底部图例与约束。2400x1340 画布按 70% 填充率核定
    p1 = doc.add_page("① 架构总览 · 三域拓扑", "overview", width=2400, height=1340)  # 画布按 70% 填充率核定
    render_page(p1, ARCHITECTURE_P1)                                                                # 渲染第一页

    # Page 2 —— 域 ① 主理能力域与委派路由
    # 布局: 左栏 5 张能力组件卡 (提供/边界/关键点三段式), 右栏委派路由表
    #       + 主理定位声明, 底部横贯一条越权即拒的边界约束
    p2 = doc.add_page("② 域① 主理能力域", "compat", width=2400, height=1420)
    render_page(p2, ARCHITECTURE_P2)                                                                # 渲染第二页

    # Page 3 —— 域 ② 五状态机执行链与阻断门禁
    # 布局: 顶部五状态横排 -> Pass 链 -> 阶段数据流四段 -> 双菱形门禁
    #       -> 双态信封 -> 失败隔离与降级留痕说明
    p3 = doc.add_page("③ 域② 五状态机执行链", "statemachine", width=2400, height=1650)
    render_page(p3, ARCHITECTURE_P3)                                                                # 渲染第三页

    # Page 4 —— 域 ③ 降级 · 错误码 · 证据存证
    # 布局: 左栏降级协议三段 + 错误码契约 + 降级与门禁关系; 右栏不可变证据
    #       组件 + 支撑 (RAG/白盒/门禁/血缘) + 治理强度元数据
    p4 = doc.add_page("④ 域③ 降级·错误码·证据", "fallback", width=2400, height=1200)
    render_page(p4, ARCHITECTURE_P4)                                                                # 渲染第四页

    return doc


if __name__ == "__main__":
    # 输出目录 = 本脚本所在目录 (docs/diagrams/), 保证从任意 cwd 调用
    # 都落到同一处 —— 架构图 SSOT 只有一份, 不允许出现多份副本。
    # F1: 环境变量 ASTRO_BEST_DIAGRAM_DIR 可覆盖该缺省 (换机器/CI 用)。
    out_dir = Path(os.environ.get("ASTRO_BEST_DIAGRAM_DIR")  # env 优先, 缺省用本脚本所在目录, 从任意 cwd 调用都落同一处
                   or Path(__file__).resolve().parent)                                              # 输出目录优先取命令行实参
    doc = build()                                                                                   # 构建整份文档
    # 写点: 唯一的文件输出 (原生 .drawio XML)。渲染成 PNG/SVG/PDF 由
    # export_diagram.py 负责, 两个脚本刻意分开 —— 生成与渲染的失败模式不同
    target = out_dir / "astro-best-legacy-architecture.drawio"  # 唯一输出路径, 架构图 SSOT 只有一份
    # 走 drawio_io.save_clean 而不是裸 doc.save: 顺手剥掉构建库写死的
    # host/agent/version 工具元数据 (见图目录 drawio_io.py 模块 docstring)
    save_clean(doc, target)  # 走 save_clean 而非裸 save: 顺手剥掉三段式版本号元数据
    print(f"[OK] written: {target}  ({target.stat().st_size} bytes)")  # 报字节数: 拆分验收要求产物逐字节不变
