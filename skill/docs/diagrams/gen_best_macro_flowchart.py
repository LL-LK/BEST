#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_best_macro_flowchart.py
---------------------------
astro-best (BEST 数据源主理 · 国家天文科学数据中心实测标准数据库)
单张超宽全景白盒化宏观架构流程图原生生成与无损渲染脚本。

技术标准 (V2 全面扩容与防重叠版):
  - 画布规格: 单张超宽全景 4400px x 3200px (原 3200x2200 扩大 1.5 倍)
  - 泳道净空间: 各核心层级（泳道）垂直间隙扩充至 120px (原 30px)
  - 卡片横向通道: 卡片间横向间距扩充至 85~94px (原 50px)
  - 架构拓扑: 5 大核心横向泳道贯通 + 数据口径表 + 闭环反馈走廊 (人 - LLM - 外部台站)
    (走廊与口径表是后补的结构: 前者把第一版就声明、却只落成一条边缘
    连线的闭环提为可见容器; 后者把量纲/单位/门限数值从治理面横幅里提为一级
    元素 — 两者均参考数模国赛 A 题全景架构图的口径表 + 外框轨道范式)
  - 走线铁律: 纯正交 Manhattan 走线 + 显式锚点约束，彻底杜绝穿框与重叠
  - 视觉规范: 专业 Slate 学术工程调色盘; 零 Emoji; 零卡片重叠
  - 产物构建: 纯 Python stdlib drawio_builder.py (零外部 pip 依赖)
  - 本地渲染: 调用本地 Draw.io CLI (路径可由环境变量 ASTRO_BEST_DRAWIO_EXE
    指定, 缺省为本机安装位置) 输出原生 .drawio, 矢量 SVG, 高清 2x PNG 与整页 PDF。

拆分说明 (budget doc §3.5 已登记方案): 字体/配色/画布尺寸/坐标/卡片文案/连线
定义等纯数据已全部抽到 layout_data.py 的 FLOWCHART_* 表, 本文件只保留渲染代码
(样式构造 + 表驱动组装 + 前置审计 + 无损导出)。拆分硬性验收: 产物逐字节不变。
"""

from __future__ import annotations

# 标准库组:
#   os         —— F1: 读环境变量 (builder 目录 / 渲染器 exe / 输出目录均可配置)
#   subprocess —— 调本机 draw.io CLI 做离线渲染 (外部进程, 非 Python 库)
#   sys        —— 注入 builder 目录到 sys.path; 退出码
#   time       —— 渲染计时与写盘延迟等待
#   pathlib    —— builder 目录探测与输出路径拼装
import os
import subprocess
import sys
import time
from pathlib import Path

# 引入项目标准 Draw.io 构建库 (drawio-diagram-author skill, 纯 stdlib)。
# F1: 环境变量 ASTRO_BEST_DRAWIO_BUILDER_DIR (os.pathsep 分隔多个目录) 优先,
# 未设时回落本机两个历史安装位置 (.gemini/config 与 .agents, 逐个探测选取)。
BUILDER_DIRS = [Path(p) for p in  # env 用 os.pathsep 分隔, 允许多个候选目录
                os.environ.get("ASTRO_BEST_DRAWIO_BUILDER_DIR", "").split(os.pathsep)
                if p] or [                                                                          # 从环境变量取父目录, 缺省用脚本所在目录
    Path(r"<USER_HOME>\.gemini\config\skills\drawio-diagram-author\scripts"),
    Path(r"<USER_HOME>\.agents\skills\drawio-diagram-author\scripts"),
]
for d in BUILDER_DIRS:  # 逐个试, 命中的都挂上; 幂等靠 sys.path 判重
    if d.exists() and str(d) not in sys.path:                                                       # 已注入就不重复
        sys.path.insert(0, str(d))                                                                  # 插首位: 本地模块要优先于环境里的同名包

# 本地第三方脚本: drawio_builder 的公开构建件 (当前版本只用到这两个;
# 容器/连线类不在其公开面上, 本图一律用 drawio_io 侧的落盘出口)
from drawio_builder import DrawioFile, DrawioNode  # noqa: E402

# 本目录共用落盘出口: 落盘后剥离构建库写死的 host/agent/version 工具元数据
# (铁律 3 不容三段式版本号字面量, 理由见图目录 drawio_io.py 模块 docstring)
from drawio_io import save_clean  # noqa: E402

# 布局数据组: 本图专用的字体/色板/画布/容器/卡片/连线常量表 (纯数据, 无逻辑,
# 表结构见 layout_data.py 模块 docstring)。常量是数据不是接口, 直接引用
from layout_data import (  # noqa: E402
    FF,                                                                                             # 字体
    FLOWCHART_BANNER,                                                                               # 横幅文案
    FLOWCHART_CANVAS,                                                                               # 画布尺寸
    FLOWCHART_CONTAINERS,                                                                           # 容器清单
    FLOWCHART_EDGES,                                                                                # 边清单
    FLOWCHART_LOOP_CONTAINER,                                                                       # 泳道容器
    FLOWCHART_NODES,                                                                                # 节点清单
    FLOWCHART_PALETTE,                                                                              # 配色表
    FLOWCHART_UNITS_STRIP,                                                                          # 单位条
)


def st(
    kind: str,                                                                                      # 节点种类
    align: str = "left",
    valign: str = "top",
    size: float = 11.5,                                                                             # 字号缺省
    bold: bool = False,                                                                             # 是否加粗
    sl: int = 16,                                                                                   # 左内边距
    sr: int = 16,                                                                                   # 右内边距
    stp: int = 10,                                                                                  # 上内边距
    sbp: int = 10,                                                                                  # 下内边距
) -> str:
    """生成标准化节点样式字符串。

    Args:
        kind: ``FLOWCHART_PALETTE`` 的语义色键。
        align: 水平对齐。
        valign: 垂直对齐。
        size: 字号 (px) —— 默认 11.5, 与卡片高度核定规则里的行高配套。
        bold: 是否加粗。
        sl/sr/stp/sbp: 左/右/上/下内边距 (px)。

    Returns:
        draw.io style 属性串。
    """
    fill, font, stroke, sw = FLOWCHART_PALETTE[kind]  # 色键解包成四元组, 键不存在即 KeyError 而不是静默中性色
    s = (  # 分段拼: 固定串与插值段交替, 便于对读调色板
        f"whiteSpace=wrap;html=1;fontFamily={FF};rounded=1;arcSize=6;"
        f"fillColor={fill};fontColor={font};strokeColor={stroke};strokeWidth={sw};"
        f"fontSize={size};align={align};verticalAlign={valign};"
        f"spacingLeft={sl};spacingRight={sr};spacingTop={stp};spacingBottom={sbp};"
    )
    if bold:  # 只在加粗态追加, 免得每处都写 bold=0
        s += "fontStyle=1;"  # 追加而非重拼整串, 省掉一次重复的长模板
    return s


def container_style(title_bg: str = "#E2E8F0") -> str:
    """生成泳道容器样式字符串。

    Args:
        title_bg: 标题栏底色 (当前实现用固定调色板, 该参数为历史签名保留,
            不影响输出 —— 改动它属于代码变更, 本次只补注释)。

    Returns:
        draw.io swimlane style 属性串。

    Note:
        ``collapsible=0`` 刻意禁用折叠: 全景图要一眼看全五个泳道,
        折叠态会让读者以为内容缺失。
    """
    return (
        f"swimlane;whiteSpace=wrap;html=1;fontFamily={FF};rounded=1;arcSize=4;"
        f"fillColor=#F8FAFC;fontColor=#0F172A;strokeColor=#CBD5E1;strokeWidth=1.5;"
        f"startSize=36;fontSize=14;fontStyle=1;collapsible=0;align=center;"
    )


def edge_style(color: str = "#2563EB", dashed: bool = False, sw: float = 1.8, font_color: str = "#1E3A8A") -> str:
    """生成纯正交 Manhattan 走线样式。

    Args:
        color: 连线色 (按语义分流: 蓝=正常流, 青=协议流, 红=阻断/降级,
            靛=委派路由, 紫=闭环反馈)。
        dashed: 是否虚线 (虚线专用于"异常/回退/反馈"这类非主路径)。
        sw: 线宽 (px) —— 闭环回路加到 2.4 以突出"外环"地位。
        font_color: 连线标签字体色。

    Returns:
        draw.io edge style 属性串。

    Note:
        ``orthogonalEdgeStyle`` 是走线铁律: 曲线连接在超宽画布上极易穿过
        无关卡片, 只有正交走线能被机械校验 (见 check_macro_collisions.py)。
    """
    dash_part = "dashed=1;" if dashed else ""  # 虚线专供异常/回退/反馈路径, 主路径必须实线
    return (
        f"edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;{dash_part}"
        f"strokeColor={color};strokeWidth={sw};fontSize=10.5;fontColor={font_color};"
        f"labelBackgroundColor=#FFFFFF;fontFamily={FF};"
    )


def build_macro_flowchart() -> DrawioFile:
    """[VERIFIED_ALGO] 组装 astro-best 4400x3200 宏观全景流程图。

    五个横向泳道自上而下贯通, 对应数据从"人/入口"到"存证/闭环"的流向:
      1. 多端接入与交互层 (6 卡: 决策中心/CLI/SDK/OOP 套件/轻量脚本/云端+RAG)
      2. 调度编排与五状态机治理层 (6 状态卡 + 12 横切治理面横幅)
      3. 两阶段异步 REST 通信引擎 (6 卡: POST 表单/提交端点/sqlid 清洗/分页/计数/传输控制)
      4. 12 张可查定标星表全景体系与外部数据源 (12 星表 + 2 外部服务端点)
      5. 安全防御、产物交付、委派路由与闭环回退 (6 卡)

    所有卡片内容逐字转写自 SKILL.md / architecture.md / 契约文件,
    本函数不做二次概括 —— 图与文档不一致即视为缺陷。

    本函数是纯渲染代码: 布局数据全部来自 layout_data.py 的 FLOWCHART_* 表,
    只按表驱动 drawio_builder。表的行序即图上添加顺序, 直接决定 .drawio
    XML 里 <mxCell> 的排列 (drawio_builder 序列化顺序为 容器->节点->连线),
    所以渲染顺序必须与表序一致, 不得自行排序。

    Returns:
        未落盘的 DrawioFile; 由 ``main()`` 保存并送审。
    """
    doc = DrawioFile("astro-best-macro-flowchart.drawio")  # 产物名固定, 输出目录由 main 决定
    canvas_w, canvas_h = FLOWCHART_CANVAS  # 画布尺寸来自布局表, 脚本不写死
    page = doc.add_page(  # 单页图: 拆页会割裂五条泳道的流向
        name="astro-best 宏观全景架构流程图",
        page_id="best_macro_flowchart",
        width=canvas_w,                                                                             # 横幅宽度取满画布
        height=canvas_h,                                                                            # 横幅高度
    )

    bx, by, bw, bh, banner_html = FLOWCHART_BANNER  # 画布级节点, 不挂在任何泳道下
    page.add_node(  # 标题条是普通节点: 折叠与挂靠语义都不适用
        node_id="top_banner",
        value=banner_html,                                                                          # 横幅的 HTML 文案
        x=bx,                                                                                       # 横幅 x
        y=by,                                                                                       # 横幅 y
        width=bw,                                                                                   # 横幅宽
        height=bh,                                                                                  # 横幅高
        style=(                                                                                     # 横幅样式
            f"whiteSpace=wrap;html=1;fontFamily={FF};rounded=1;arcSize=4;"
            "fillColor=#0F172A;fontColor=#FFFFFF;strokeColor=#1E293B;strokeWidth=2;"
            "fontSize=15.5;fontStyle=1;align=center;verticalAlign=middle;"
            "spacingLeft=16;spacingRight=16;spacingTop=6;spacingBottom=6;"
        ),
    )

    ux, uy, uw, uh, units_html = FLOWCHART_UNITS_STRIP  # 量纲口径表: 每个数值都要能在源码对上号
    page.add_node(  # 同为画布级节点, 样式走 st() 的 banner 色键
        node_id="units_strip",
        value=units_html,                                                                           # 单位条的文案
        x=ux,                                                                                       # 单位条 x
        y=uy,                                                                                       # 单位条 y
        width=uw,                                                                                   # 单位条宽
        height=uh,                                                                                  # 单位条高
        style=st("banner", align="left", valign="middle", size=11.5),
    )

    # 五大能力泳道 + 一条闭环走廊容器: 按 FLOWCHART_CONTAINERS 表序渲染, 先建
    # 容器后放卡片 —— drawio_builder 序列化时容器永远排在其子节点之前 (背景在
    # 后, z 序正确)。lanes: 容器 id -> DrawioContainer (子卡片按父容器 id 挂靠)
    lanes = {}  # 容器 id -> DrawioContainer, 子卡片按父 id 挂靠
    for cid, title, x, y, w, h in FLOWCHART_CONTAINERS:  # 表序即添加序, 不得自行排序
        lanes[cid] = page.add_container(  # 先建容器后放卡片, 序列化时容器永远排在子节点之前
            container_id=cid,                                                                       # 容器 id
            title=title,                                                                            # 容器标题
            x=x,                                                                                    # 容器 x
            y=y,                                                                                    # 容器 y
            width=w,                                                                                # 容器宽
            height=h,                                                                               # 容器高
            style=container_style(),                                                                # 容器样式统一由一个函数给
        )
    lc_id, lc_title, lc_x, lc_y, lc_w, lc_h = FLOWCHART_LOOP_CONTAINER  # 第 6 条横带: 横切回退通道, 不属能力层
    lanes[lc_id] = page.add_container(                                                              # 泳道容器登记
        container_id=lc_id,                                                                         # 泳道 id
        title=lc_title,                                                                             # 泳道标题
        x=lc_x,                                                                                     # 泳道 x
        y=lc_y,                                                                                     # 泳道 y
        width=lc_w,                                                                                 # 泳道宽
        height=lc_h,                                                                                # 泳道高
        style=container_style(),                                                                    # 泳道样式
    )

    for pid, nid, x, y, w, h, kind, value in FLOWCHART_NODES:  # 子卡坐标是容器局部系, 父 id 查 lanes
        lanes[pid].add_child(  # lanes 缺 key 说明数据表与容器表不一致, 该立刻炸出来
            DrawioNode(nid, value, x=x, y=y, width=w, height=h, style=st(kind))                  # 节点按 (种类, 位置, 尺寸, 样式) 落图
        )

    # 纯正交 Manhattan 走线体系: 全部连线集中在 7 组, 每组走一条专用纵向走廊
    # (Y=530..650 / 1150..1270 / 1710..1830 / 2350..2470 等 120px 间隙), 靠
    # waypoints 显式锚点固定路径 —— 不写锚点的话 draw.io 自动布线会在密集
    # 卡片间乱穿。无锚点的边传 None (等价于 drawio_builder 的缺省值)
    for eid, src, tgt, value, color, dashed, sw, font_color, anchor, waypoints in FLOWCHART_EDGES:  # 十元组: 锚点与折点全在表里
        page.add_edge(  # anchor 拼在样式串尾部; None 等价于构建库缺省
            eid,                                                                                    # 边 id
            source=src,                                                                             # 起点
            target=tgt,                                                                             # 终点
            value=value,                                                                            # 边上的文案
            style=edge_style(color, dashed, sw, font_color) + anchor,                            # 边样式由颜色/虚线/线宽/字色合成, 再加锚点
            waypoints=waypoints,                                                                    # 折点
        )

    return doc  # 只返回不落盘: 写点收在 main 一处


def export_diagram(drawio_file: Path) -> bool:
    """[VERIFIED_ALGO] 调用本地安装的 Draw.io CLI 进行多格式无损渲染。

    依次导出 2x PNG (位图预览)、SVG (矢量, 可进文档)、PDF (整页打印)。
    三种格式共用同一份 .drawio 源, 保证"所见即所出"。

    Args:
        drawio_file: 待渲染的 .drawio 路径。

    Returns:
        三种格式全部产出且大于 10000 字节返回 True; 任一失败返回 False
        (调用方据此中止流水线, 不把半成品当交付物)。

    Note:
        CLI 不在 PATH 里时只告警并返回 False, 不抛异常 —— 渲染是可选步骤,
        缺 CLI 的机器仍应能完成"生成 .drawio"这一步。
    """
    # F1: 渲染器路径可配置 — 环境变量 ASTRO_BEST_DRAWIO_EXE 优先, 未设时
    # 回落本机安装位置 (保留以使本机仍可跑); CLI 缺失只告警不抛异常
    drawio_exe = Path(os.environ.get("ASTRO_BEST_DRAWIO_EXE") or r"<TOOL_ROOT>\draw.io.exe")
    if not drawio_exe.exists():  # 缺依赖只退渲染阶段, 生成 .drawio 不受影响
        # 渲染器缺失 = 环境缺依赖, 不是图有问题: 告警后退出门渲染阶段
        print(f"[WARN] Local Draw.io CLI not found at {drawio_exe}, skipping raster export.", file=sys.stderr)
        return False

    flags = ["--no-sandbox", "--disable-gpu"]  # 缺任一 flag: GPU 子进程崩溃且不产出任何文件
    formats = [  # 三格式共用同一份源, 保证所见即所出
        ("png", ["-x", "-f", "png", "--scale", "2", "-o"]),
        ("svg", ["-x", "-f", "svg", "-o"]),
        ("pdf", ["-x", "-f", "pdf", "-o"]),
    ]

    out_dir = drawio_file.parent  # 产物与源同目录, 渲染时找得到相对资源
    base_name = drawio_file.stem                                                                    # 输出基名取自 drawio 源文件名
    success_all = True  # 与门禁: 任一格式失败即整体判失败

    print("\n" + "=" * 70)
    print(f"Starting Headless Export via Local Draw.io: {drawio_exe}")
    print("=" * 70)

    for fmt_name, fmt_args in formats:  # 每格式一趟; 参数表驱动, 不写三份重复
        out_file = out_dir / f"{base_name}.{fmt_name}"  # 目标名由格式名拼出, 便于成套归档
        if out_file.exists():  # 删旧产物, 否则上次的残留会被当成本次成功
            out_file.unlink()                                                               # 旧产物先删: 否则 draw.io 会跳过重写而留下旧图

        cmd = [str(drawio_exe)] + flags + fmt_args + [str(out_file), str(drawio_file)]  # 输入在前输出在后, 顺序不能反
        t0 = time.time()                                                                            # 计时起点
        res = subprocess.run(cmd, capture_output=True, cwd=str(drawio_exe.parent), timeout=180)  # cwd 指到 exe 旁, 180s 超时
        dt = time.time() - t0                                                                       # 生成耗时
        time.sleep(0.8)  # 渲染器写盘有延迟, 进程退出不代表文件已落盘

        # 判成功看产物不看退出码: exit 0 但 0 字节的情况真实发生过
        if out_file.exists() and out_file.stat().st_size > 10000:  # 判成功看产物不看退出码: exit 0 但 0 字节真实发生过
            print(f"[PASS] {fmt_name.upper():<4} Exported: {out_file.name} ({out_file.stat().st_size:,} bytes, {dt:.1f}s)")
        else:
            success_all = False  # 记一次失败即污染整体, 不做提前跳出
            err = res.stderr.decode("utf-8", errors="replace").strip()  # 只取 stderr; 失败常静默, 报错全在这里
            print(f"[FAIL] {fmt_name.upper():<4} Export failed! Error: {err}", file=sys.stderr)

    return success_all  # 三格式全过才算成功, 半成品不算交付物


def audit_diagram(drawio_path: Path) -> bool:
    """[VERIFIED_ALGO] 严格几何碰撞、Emoji 与安全合规审计。

    渲染前的硬闸: 卡片坐标全是手写魔法数字, 一次改动就可能让两张卡压在一起,
    而这类问题在 .drawio 里肉眼极难发现, 所以先机械审再渲染。

    Args:
        drawio_path: 刚生成的 .drawio 路径。

    Returns:
        全部通过返回 True; 任一违规返回 False (调用方中止渲染, 不交付半成品)。

    Note:
        三道关: 官方 verify_drawio_security.py (安全+容器包含) -> 零 emoji
        -> AABB 两两碰撞 (绝对坐标, 跨泳道也查)。
    """
    print("\n" + "=" * 70)
    print("Starting Pre-Flight Geometry, Security & Compliance Audit")
    print("=" * 70)

    # 1. 运行官方 verify_drawio_security.py
    import verify_drawio_security
    valid, violations = verify_drawio_security.verify_drawio_file(drawio_path)  # 官方脚本给出安全与容器包含两类判定
    if not valid:                                                                                   # 几何校验不过就先报违规
        print("[FAIL] Security & Container Containment Violations Found:")
        for v in violations:                                                                        # 逐条打印违规
            print(f"  - {v}")
        return False
    print("[PASS] Security & Container Bounds: 0 violations (100% offline & safe)")

    # 2. 零 Emoji 审查
    content = drawio_path.read_text(encoding="utf-8")  # emoji 检查必须看原文, XML 解析会丢实体信息
    emojis = [                                                                                      # 收集 emoji
        c for c in content                                                                          # 逐字符
        if (0x1F300 <= ord(c) <= 0x1FAFF)                                                           # emoji 主区段
        or (0x1F1E6 <= ord(c) <= 0x1F1FF)                                                           # 国旗区段
        or (0x2700 <= ord(c) <= 0x27BF and ord(c) not in (0x2794, 0x27A1))                          # 符号区段 (排除两个箭头)
    ]
    if emojis:  # 命中即判红: 跨平台缺字形会变豆腐块
        print(f"[FAIL] Forbidden Emoji detected: {set(emojis)}")
        return False
    print("[PASS] Zero Emojis: 0 forbidden unicode characters")

    # 3. 严格包围盒 AABB 碰撞检测 (包含同泳道兄弟卡片及全局绝对坐标碰撞)
    # 读点: 同一份文件再按 XML 解析 —— 几何判定需要 DOM, 与上面的文本
    # 通道分开 (两条通道覆盖的故障类型不同)
    import xml.etree.ElementTree as ET
    from itertools import combinations

    root = ET.fromstring(content)  # 几何判定要 DOM, 与文本通道是两条独立通道
    diagram = root.find("diagram")
    model = diagram.find("mxGraphModel")
    # 画布尺寸本函数不消费: 碰撞判定走绝对坐标两两比对, 越界由
    # verify_drawio_security 负责 (F2: 原先这里取了 W/H 两个从未使用的变量)

    # 提取容器绝对坐标
    containers = {}                                                                                 # 容器几何表
    cards = []  # 元素元组: (id, 绝对 x, 绝对 y, 宽, 高, 父容器 id)

    for cell in model.findall(".//mxCell"):  # 全树取: 顶点可能嵌在分组里, 非直接子级
        if cell.attrib.get("vertex") != "1":
            continue
        cid = cell.attrib.get("id")
        geo = cell.find("mxGeometry")
        if geo is None:                                                                             # 拿不到几何即无法校验
            # 无几何信息的顶点 (如标签节点) 无法参与空间判定, 跳过
            continue
        x = float(geo.attrib.get("x", "0"))
        y = float(geo.attrib.get("y", "0"))
        w = float(geo.attrib.get("width", "0"))
        h = float(geo.attrib.get("height", "0"))
        pid = cell.attrib.get("parent", "1")  # 缺省 1 = 默认层, 画布级卡片会落在这个 key 上
        style = cell.attrib.get("style", "")

        if "swimlane" in style:  # 按 style 判角色: 泳道进容器表, 其余进卡片表
            containers[cid] = (x, y, w, h)                                                          # 记容器矩形
        elif cid not in ("0", "1"):  # 0/1 是 mxGraph 根节点与默认层, 不是卡片
            # id 0/1 是 mxGraph 根节点与默认层, 不是真实卡片
            cards.append((cid, x, y, w, h, pid))                                                    # 记卡片 (含所属容器)

    # 计算卡片绝对坐标
    # 子卡片坐标是父容器局部坐标, 必须先加容器原点归一 —— 否则两张分别
    # 属于不同泳道的卡片会被当成都在 (0,0) 附近而误判重叠
    abs_cards = []  # 归一后的绝对坐标表, 两两比对只在同坐标系里做
    for cid, rx, ry, w, h, pid in cards:                                                            # 逐卡片
        if pid in containers:                                                                       # 有父容器才需要换算
            cx, cy, cw, ch = containers[pid]                                                        # 取父容器矩形
            abs_x = cx + rx                                                                         # 绝对 x = 父 x + 相对 x
            abs_y = cy + ry                                                                         # 绝对 y = 父 y + 相对 y
        else:
            abs_x = rx                                                                              # 无父容器就是绝对坐标
            abs_y = ry                                                                              # 纵坐标同理: 无父容器时它本身就是绝对坐标
        abs_cards.append((cid, abs_x, abs_y, w, h, pid))                                            # 收进绝对坐标表

    # 检测同父容器内兄弟卡片碰撞以及跨容器卡片碰撞
    collisions = []  # 同父与跨容器两类碰撞合并进同一张表
    tolerance = 0.5  # 0.5px 容差: 低于此视为"贴边", 是刻意排版不是事故
    for a, b in combinations(abs_cards, 2):  # 两两组合: 页级规模下 O(n^2) 足够
        ida, xa, ya, wa, ha, pa = a                                                                 # 解包 A 卡
        idb, xb, yb, wb, hb, pb = b                                                                 # 解包 B 卡

        # AABB 碰撞条件: overlap_x > 0 and overlap_y > 0 (两个轴都重叠才相交)
        overlap_x = min(xa + wa, xb + wb) - max(xa, xb)                                             # 横向重叠量
        overlap_y = min(ya + ha, yb + hb) - max(ya, yb)                                             # 纵向重叠量

        if overlap_x > tolerance and overlap_y > tolerance:  # 两轴同时越过容差才算真碰撞
            collisions.append((ida, idb, pa, pb, overlap_x, overlap_y))  # 连父 id 一起存, 报告才定位得到

    if collisions:                                                                                  # 有碰撞即报
        print(f"[FAIL] Card collisions detected ({len(collisions)} pairs):")
        for ida, idb, pa, pb, ox, oy in collisions:                                                 # 逐对打印
            print(f"  - Overlap between '{ida}' and '{idb}' (parents: {pa}, {pb}, dx={ox:.1f}, dy={oy:.1f})")
        return False

    print(f"[PASS] Geometry Collision Detection: 0 overlaps across all {len(abs_cards)} cards")
    print("=" * 70 + "\n")
    return True


def main() -> int:
    """流水线入口: 生成 .drawio -> 前置几何审计 -> 无损渲染导出。

    顺序不可换: 先审再渲染。反过来会先把有重叠的图渲出 PNG/SVG/PDF,
    再因审计失败而留下四份都要作废的产物。

    Returns:
        全链路成功返回 0; 审计或渲染失败返回 1 (供 CI / make 当硬闸)。
    """
    # F1: 输出目录可配置 — 环境变量 ASTRO_BEST_DIAGRAM_DIR 优先, 未设时回落
    out_dir = Path(os.environ.get("ASTRO_BEST_DIAGRAM_DIR") or r"<SKILLS_ROOT>\astro-best\docs\diagrams")
    # 本机目录 (保留以使本机仍可跑); 建目录以保证新克隆仓库里也能落盘
    out_dir.mkdir(parents=True, exist_ok=True)                                                      # 输出目录自动建
    drawio_file = out_dir / "astro-best-macro-flowchart.drawio"

    print("=" * 70)
    print("Generating astro-best Macro Panoramic Flowchart (.drawio)")
    print(f"Target file: {drawio_file}")
    print("=" * 70)

    doc = build_macro_flowchart()                                                                   # 构建并落盘
    save_clean(doc, drawio_file)  # 走 save_clean 而非裸 save: 顺手剥掉三段式版本号元数据
    print(f"[SUCCESS] Native .drawio generated: {drawio_file} ({drawio_file.stat().st_size:,} bytes)")

    # 几何与合规前置审查
    if not audit_diagram(drawio_file):  # 先审后渲: 反过来会先产出四份废图
        # 审计不过就不渲染: 避免产出四份都要返工的废图
        print("[ERROR] Audit failed! Halting export pipeline.", file=sys.stderr)
        return 1

    # 无损渲染导出 SVG, PNG, PDF
    if not export_diagram(drawio_file):  # 渲染是可选步骤, 缺 CLI 不算图有缺陷
        print("[ERROR] Headless export failed!", file=sys.stderr)
        return 1

    print("[SUCCESS] All artifacts generated and verified successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())                                                                                # 退出码直接用 main
