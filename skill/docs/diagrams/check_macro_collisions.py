#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_macro_collisions.py
-------------------------
astro-best-macro-flowchart.drawio 的独立几何碰撞校验脚本 (可单文件运行)。

生成的宏观流程图是"人工排版的产物": 卡片坐标全是手写的魔法数字, 一次
改动就可能让两张卡片压在一起, 而这类问题在 .drawio 里肉眼看极难发现。
本脚本把图当数据做机械校验, 是交付前的硬闸。

校验项 (逐项打印 PASS/FAIL, 任一 FAIL 即返回 1):
  1. XML 合法性与结构完整 (<diagram> / <mxGraphModel> 必须在位);
  2. 零禁用 emoji (视觉规范: 跨平台字体缺字形会变豆腐块);
  3. 容器 (泳道) 必须完整落在画布内;
  4. 子卡片必须落在其父容器边界内 (带 1.0px 容差, 抗浮点误差);
  5. 同一容器内的兄弟卡片两两不重叠 (AABB, 0.5px 容差);
  6. 全画布绝对坐标下, 任意两张卡片不重叠 (跨容器也查);
  7. 连线应为正交走线 (非正交只 WARN 不判败 —— 是风格问题不是错误)。

用法:
    python docs/diagrams/check_macro_collisions.py [drawio 路径]
    缺省审 astro-best-macro-flowchart.drawio; 也可传任意 .drawio 复用。
    缺省目标目录可用环境变量 ASTRO_BEST_DIAGRAM_DIR 指定 (F1: 不再只有
    本机硬编码路径一条路)。
"""

from __future__ import annotations

# 标准库组:
#   sys        —— 退出码 (校验失败返回 1) / stderr 分流 / 命令行参数 (F1)
#   os         —— F1: 读环境变量 ASTRO_BEST_DIAGRAM_DIR (目标目录可配置)
#   xml.etree.ElementTree —— 解析 .drawio (mxGraph XML), 只读不写
#   itertools.combinations —— 卡片两两组合, 做 AABB 重叠检测
#   pathlib    —— 目标文件路径处理与存在性判断
import os
import sys
import xml.etree.ElementTree as ET
from itertools import combinations
from pathlib import Path


def is_emoji(c: str) -> bool:
    """判断单字符是否落在禁用 emoji 的 Unicode 区间内。

    覆盖三段区间: 补充符号与象形文字 (1F300-1FAFF)、区域指示符
    (1F1E6-1F1FF, 国旗)、装饰符号 (2700-27BF)。2700-27BF 里放行
    2794/27A1 两个箭头: 流程图里当流程箭头用, 不属于 emoji。

    Args:
        c: 单个字符。

    Returns:
        True 表示该字符属于禁用 emoji。
    """
    cp = ord(c)  # emoji 判定全走码位, 不做字面量枚举
    return (
        (0x1F300 <= cp <= 0x1FAFF)                                                                  # emoji 主区段
        or (0x1F1E6 <= cp <= 0x1F1FF)                                                               # 国旗区段
        or (0x2700 <= cp <= 0x27BF and cp not in (0x2794, 0x27A1))                              # 符号区段 (排除两个箭头, 它们在图里当指示线)
    )


def audit_file(drawio_path: Path) -> int:
    """对单个 .drawio 文件执行全部几何/合规校验。

    校验顺序是"由粗到细": 先文件存在性, 再 emoji, 再 XML 结构, 最后才是
    几何。前序失败就早退 —— 文件都读不到时去算碰撞没有意义, 而且早退能
    给出最贴近根因的一条报错。

    Args:
        drawio_path: 待审 .drawio 文件路径。

    Returns:
        0 = 全部通过; 1 = 任一校验失败 (供 CI / make 当硬闸消费)。
    """
    print("=" * 75)  # 分隔线: 让 PASS/FAIL 段落一眼可切, 也方便 grep 单段
    print(f"Independent Collision & Geometry Audit: {drawio_path.name}")
    print("=" * 75)

    if not drawio_path.exists():  # 文件不存在直接判红, 不当零缺陷放行
        print(f"[ERROR] File not found: {drawio_path}", file=sys.stderr)
        return 1

    # 读点 1: 整份 .drawio 当文本读入 —— emoji 检查必须看原文
    # (XML 解析会丢字符实体, 实体里也可能藏 emoji)
    content = drawio_path.read_text(encoding="utf-8")  # 读点: 整份 XML 进内存, 后面所有检查都从这一份文本出发

    # 检查 1: emoji 禁用 (drawio 跨端渲染会掉字形)
    emojis = [c for c in content if is_emoji(c)]  # 保留重复字符以便看出现次数, 但只报去重后的集合
    if emojis:                                                                                      # 有 emoji 才报
        print(f"[FAIL] Emojis detected: {set(emojis)}", file=sys.stderr)
        return 1
    # 通过: 报告"0 个"是硬编码事实 (上面已 return 1 掉有 emoji 的分支),
    # 这行没有任何插值, 就是普通字符串 (F2: 去掉多余的 f 前缀)
    print("[PASS] Zero Emojis: 0 forbidden characters detected.")

    # 检查 2: 解析 XML (drawio 的 mxfile/mxGraphModel 结构)
    try:
        # 读点 2: 同一份文件再按 XML 解析 —— 几何校验需要 DOM。
        # 与 emoji 的文本通道分开: 两条通道覆盖的故障类型不同
        root = ET.fromstring(content)  # 只解析第一个 <diagram>: 多页图的几何必须逐页分开审
    except Exception as e:
        print(f"[FAIL] XML parsing error: {e}", file=sys.stderr)
        return 1

    # 结构锚点: 单页 .drawio 只有一个 <diagram>, 其下必须挂 <mxGraphModel>
    diagram = root.find("diagram")  # 缺 <diagram> 是结构性损坏, 后面所有几何判定都无意义
    if diagram is None:                                                                             # 取不到 diagram 节点即无法校验
        print("[FAIL] Missing <diagram> element", file=sys.stderr)
        return 1

    model = diagram.find("mxGraphModel")  # 缺 <mxGraphModel> 同判红: 没有模型就没有坐标系
    if model is None:                                                                               # 取不到 model 节点同样
        print("[FAIL] Missing <mxGraphModel> element", file=sys.stderr)
        return 1

    # 画布逻辑尺寸: 后续所有越界/包含判定都以它为界。
    # 缺省值 3200x2200 只是兜底, 正常文件一定显式写了 pageWidth/pageHeight
    W = float(model.attrib.get("pageWidth", "3200"))  # 属性缺省 3200: 与 draw.io 新建图的默认画布一致
    H = float(model.attrib.get("pageHeight", "2200"))  # 属性缺省 2200, 宽高必须同源取, 混用会算出假越界
    print(f"[INFO] Canvas dimensions: {W:.0f}px x {H:.0f}px")

    # 容器与卡片分开收集: 泳道 (swimlane) 是容器, 其余顶点是卡片。
    # 子卡片的坐标是相对父容器的局部坐标, 必须先归一到绝对坐标才能互相比
    containers: dict[str, tuple[float, float, float, float, str]] = {}  # 容器表: id -> 绝对几何, 卡片要靠它换算到画布绝对坐标
    cards: list[tuple[str, float, float, float, float, str, str]] = []  # 卡片表另存父 id: 包含性检查要逐层回溯 parent

    for cell in model.findall(".//mxCell"):  # .//mxCell 全树取: 顶点可能嵌在容器分组里, 非直接子级
        if cell.attrib.get("vertex") != "1":
            continue
        cid = cell.attrib.get("id", "")
        pid = cell.attrib.get("parent", "1")  # parent 缺省 1 = 图层根; 画布级卡片会落到这个 key 上
        style = cell.attrib.get("style", "")
        geo = cell.find("mxGeometry")  # 几何是 mxCell 的唯一子元素; 缺它说明这是容器或边
        if geo is None:                                                                             # 拿不到几何数据就跳过后续三类检查
            # 没有几何信息的顶点 (如某些标签节点) 无法参与空间判定, 跳过
            continue

        x = float(geo.attrib.get("x", "0"))
        y = float(geo.attrib.get("y", "0"))
        w = float(geo.attrib.get("width", "0"))
        h = float(geo.attrib.get("height", "0"))

        if "swimlane" in style:  # 按 style 判角色: swimlane 进容器表, 其余顶点进卡片表
            containers[cid] = (x, y, w, h, style)                                                   # 容器矩形连样式一起存
        elif cid not in ("0", "1"):
            # id 0/1 是 mxGraph 的根节点与默认层, 不是真实卡片
            cards.append((cid, x, y, w, h, pid, style))

    print(f"[INFO] Detected {len(containers)} swimlanes and {len(cards)} cards/nodes.")

    # 3. Canvas Boundary Check for Top-Level Elements
    # 只查容器不查卡片: 卡片可能相对容器是局部坐标, 拿局部坐标跟画布比
    # 会误报; 容器的坐标本身就是画布绝对坐标, 查它才有效
    oob = []                                                                                        # 越界清单
    for cid, (cx, cy, cw, ch, _) in containers.items():  # 容器越界单独一趟: 容器自己跑出画布时里面的卡片判定已无意义
        if cx < 0 or cy < 0 or cx + cw > W or cy + ch > H:                                          # 四边任一越界即记
            oob.append((cid, cx, cy, cw, ch))                                                       # 记一条
    if oob:                                                                                         # 有越界才进入打印
        print(f"[FAIL] Containers out of canvas bounds: {oob}", file=sys.stderr)
        return 1
    print("[PASS] Canvas Containment: All containers within canvas.")

    # 检查 4: 子元素必须落在其容器内 (防卡片溢出容器边界)
    containment_violations = []                                                                     # 包含关系违规清单
    # 1.0px 容差: 手写坐标 + 浮点运算必然有微小误差, 不容差会全是假阳性
    tolerance = 1.0  # 1px 容差: 消除浮点与描边半像素带来的假阳性
    for cid, rx, ry, rw, rh, pid, _ in cards:  # 卡片坐标是容器局部系, 与容器比之前不能直接用
        if pid in containers:                                                                       # 有父容器才谈包含
            px, py, pw, ph, _ = containers[pid]                                                     # 取父容器矩形
            # 逐边核对: 左/上不许负 (不许溢出容器左上角), 右/下不许超容器尺寸
            if rx < -tolerance:                                                                     # 左越界 (留容差)
                containment_violations.append(f"Card '{cid}' x={rx:.1f} < 0 in container '{pid}'")
            if ry < -tolerance:                                                                     # 上越界
                containment_violations.append(f"Card '{cid}' y={ry:.1f} < 0 in container '{pid}'")
            if rx + rw > pw + tolerance:                                                            # 右越界
                containment_violations.append(f"Card '{cid}' x+w={rx+rw:.1f} > container width {pw:.1f}")
            if ry + rh > ph + tolerance:                                                            # 下越界
                containment_violations.append(f"Card '{cid}' y+h={ry+rh:.1f} > container height {ph:.1f}")

    if containment_violations:                                                                      # 有违规才打印
        # 无插值行就是普通字符串 (F2: 去掉多余的 f 前缀); 明细在下一行逐条打
        print("[FAIL] Container containment violations:", file=sys.stderr)
        for cv in containment_violations:                                                           # 逐条打印
            print(f"  - {cv}", file=sys.stderr)
        return 1
    print(f"[PASS] Container Boundary Containment: All {len(cards)} cards safely inside their respective containers.")

    # 5. Sibling Card Collision Check (Inside Same Container)
    # 先按父容器分组, 只在同父的卡片之间比: 跨容器的两张卡即使视觉上挨着,
    # 也属于不同泳道的合法排版, 不算冲突 (那种情况由第 6 项的全局坐标查)
    sibling_collisions = []                                                                         # 兄弟碰撞清单: 同父容器内的卡片互相压
    cards_by_parent: dict[str, list] = {}  # 先按父分组, 跨容器比较是另一趟 (全局碰撞)
    for card in cards:                                                                              # 逐卡片
        pid = card[5]                                                                               # 取父容器 id
        cards_by_parent.setdefault(pid, []).append(card)                                            # 按父分组

    for pid, sibs in cards_by_parent.items():                                                       # 逐父容器
        for a, b in combinations(sibs, 2):                                                          # 同组内两两组合
            ida, xa, ya, wa, ha, _, _ = a
            idb, xb, yb, wb, hb, _, _ = b

            # AABB 重叠量: 两个轴上都是正数才算真的相交
            overlap_x = min(xa + wa, xb + wb) - max(xa, xb)  # 一维投影重叠量: 负值即这一轴上分开
            overlap_y = min(ya + ha, yb + hb) - max(ya, yb)  # 两轴都算, 缺一个会把上下相邻误判成压叠

            # 0.5px 阈值: 低于此视为"贴边", 是刻意排版不是事故
            if overlap_x > 0.5 and overlap_y > 0.5:  # 0.5px 阈值: 小于此的擦边不算缺陷, 视觉上也看不出来
                sibling_collisions.append((ida, idb, pid, overlap_x, overlap_y))                    # 记一对重叠

    if sibling_collisions:                                                                          # 有碰撞才打印
        print(f"[FAIL] Sibling card collisions found ({len(sibling_collisions)} pairs):", file=sys.stderr)
        for ida, idb, pid, ox, oy in sibling_collisions:                                            # 逐对打印
            print(f"  - Overlap: '{ida}' vs '{idb}' in parent '{pid}' (dx={ox:.1f}px, dy={oy:.1f}px)", file=sys.stderr)
        return 1
    print("[PASS] Sibling Collision Check: 0 collisions across sibling cards inside all containers.")

    # 6. Global Absolute Coordinate Collision Check
    # 局部坐标归一成绝对坐标: 在容器内的卡要加上容器的 (x, y);
    # 不在容器内的顶级卡本身就是绝对坐标
    global_collisions = []                                                                          # 全局碰撞: 跨父容器的绝对坐标碰撞
    abs_cards = []                                                                                  # 绝对坐标卡片表
    for cid, rx, ry, rw, rh, pid, _ in cards:  # 换算成画布绝对坐标, 跨容器的卡片才能同框比较
        if pid in containers:                                                                       # 有父容器
            cx, cy, _, _, _ = containers[pid]                                                       # 取父容器 x/y
            abs_x = cx + rx                                                                         # 绝对 x
            abs_y = cy + ry                                                                         # 绝对 y
        else:
            abs_x = rx                                                                              # 无父容器即自身坐标
            abs_y = ry                                                                              # 纵坐标同理: 无父容器时它本身就是绝对坐标
        abs_cards.append((cid, abs_x, abs_y, rw, rh, pid))                                          # 收进绝对表

    for a, b in combinations(abs_cards, 2):                                                         # 绝对表上两两组合
        ida, xa, ya, wa, ha, pa = a                                                                 # 解包 A
        idb, xb, yb, wb, hb, pb = b                                                                 # 解包 B

        overlap_x = min(xa + wa, xb + wb) - max(xa, xb)                                             # 横向重叠量
        overlap_y = min(ya + ha, yb + hb) - max(ya, yb)                                             # 纵向重叠量

        if overlap_x > 0.5 and overlap_y > 0.5:                                               # 两个方向都超过 0.5px 才算真压 (抗浮点噪声)
            global_collisions.append((ida, idb, pa, pb, overlap_x, overlap_y))                      # 记一条

    if global_collisions:                                                                           # 有碰撞才打印
        print(f"[FAIL] Global card collisions found ({len(global_collisions)} pairs):", file=sys.stderr)
        for ida, idb, pa, pb, ox, oy in global_collisions:                                          # 逐对打印
            print(f"  - Overlap: '{ida}' (in {pa}) vs '{idb}' (in {pb}) (dx={ox:.1f}px, dy={oy:.1f}px)", file=sys.stderr)
        return 1
    print(f"[PASS] Global Collision Check: 0 collisions across all {len(abs_cards)} cards globally on canvas.")

    # 7. Check Edges
    # 只 WARN 不判败: 正交走线是排版风格要求, 曲线连接不影响数据正确性,
    # 把它设成 FAIL 会让本闸从"防错位"膨胀成"管审美"
    edges = model.findall(".//mxCell[@edge='1']")  # 连线只查是否正交, 不查端点是否真的连到卡片
    print(f"[INFO] Total connectors / edges: {len(edges)}")
    for e in edges:                                                                                 # 逐条边做端点检查
        style = e.attrib.get("style", "")
        if "orthogonalEdgeStyle" not in style:  # 曲线连线在密集卡片间会穿框, 这里降级为 WARN 不判红
            print(f"[WARN] Edge '{e.attrib.get('id')}' is not orthogonalEdgeStyle!")

    print("=" * 75)
    print("ALL GEOMETRY & COLLISION CHECKS PASSED: 0 DEFECTS DETECTED")
    print("=" * 75)
    return 0


def main() -> int:
    """入口: 取命令行指定的 .drawio (缺省审宏观流程图) 并执行校验。

    目标路径三级解析 (F1): 命令行第 1 个参数 > 环境变量
    ``ASTRO_BEST_DIAGRAM_DIR`` 拼上固定文件名 > 本机默认绝对路径
    (保留以使原开发机上零参数仍可跑)。

    Returns:
        校验通过返回 0; 文件缺失或任一校验失败返回 1。
    """
    if len(sys.argv) > 1:                                                                           # 命令行给了目录就用它
        target = Path(sys.argv[1])  # 显式传参复用: 审别的图不必改代码
    else:
        env_dir = os.environ.get("ASTRO_BEST_DIAGRAM_DIR")  # env 优先, 缺省回落本机绝对路径 (换机靠设变量覆盖)
        default_dir = Path(env_dir) if env_dir else Path(                                           # 否则环境变量, 都没有才用缺省路径
            r"<SKILLS_ROOT>\astro-best\docs\diagrams")
        target = default_dir / "astro-best-macro-flowchart.drawio"
    return audit_file(target)


if __name__ == "__main__":
    sys.exit(main())                                                                                # 退出码直接用 main
