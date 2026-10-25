"""audit_local.py — .drawio 架构图的本地几何/合规体检脚本。

用途: 在把架构图交付/渲染之前, 对单个 .drawio 文件做一次本地静态审计,
把"图面质量问题"挡在评审之前。数据来源是被审的 .drawio 文件本身
(XML), 不连网、不依赖 draw.io 桌面端。

审计项 (逐条打印, 人工判读):
  1. 禁用 emoji: 视觉规范要求零 emoji (跨平台字体缺字形会变豆腐块);
  2. 路径泄漏: 图内不应出现 src/ scripts/ references/ 等真实目录路径或
     .py/.yaml/.md 文件名 —— 架构图只讲语义组件, 不讲文件布局,
     否则一次目录重构就要改图;
  3. 页数统计 (多页 .drawio 一页一个视图);
  4. 每页画布尺寸 + 顶点/边数量;
  5. 越界检测 (oob): 顶点跑到 pageWidth/pageHeight 外面;
  6. 重叠检测 (overlaps): 同层卡片两两 AABB 相交 (泳道容器与子卡片
     的有意重叠已排除, 见 cont_ids 过滤)。

用法:
    python docs/diagrams/audit_local.py [drawio 路径]
    缺省审 astro-best-legacy-architecture.drawio; 目标目录也可用环境变量
    ASTRO_BEST_DIAGRAM_DIR 指定 (F1: 不再硬编码本机绝对路径)。
"""

# 标准库组:
#   os                     —— F1: 读环境变量 ASTRO_BEST_DIAGRAM_DIR (路径可配置)
#   re                     —— 路径泄漏正则 (F2: 原延迟到 import 区之后, 触发 E402;
#                            "只在一处用"不构成延迟导入的理由, 顶层导入零成本)
#   sys                    —— 读命令行第 1 个参数 (显式指定被审文件)
#   xml.etree.ElementTree  —— 解析 .drawio (本质是 mxGraph XML), 只读不写
#   itertools.combinations —— 卡片两两组合, 做 AABB 重叠检测
#   pathlib                —— 把 env/argv/默认值三种来源统一成 Path 对象
import os
import re
import sys
import xml.etree.ElementTree as ET
from itertools import combinations
from pathlib import Path

# 本机默认图表目录 (F1 保留值): 环境变量与命令行参数都缺省时用它,
# 保证原开发机上零配置仍可跑
DEFAULT_DIAGRAM_DIR = Path(r"<SKILLS_ROOT>\astro-best\docs\diagrams")  # F1 的最后一级兜底: 换机后靠 env 或 argv 覆盖
# 环境变量名: 五张图脚本共用的图表目录配置点 (F1)
DIAGRAM_DIR_ENV = "ASTRO_BEST_DIAGRAM_DIR"  # 五张图脚本共用的配置点, 改一处即全链生效


def resolve_target(argv_path: str = "") -> Path:
    """解析被审 .drawio 路径: 命令行参数 > 环境变量目录 > 本机默认目录。

    F1: 原实现把绝对路径写死在模块级常量里, 换机器必然失效。这里按
    "显式参数 -> 环境变量 -> 默认值" 三级解析, 只改路径获取方式,
    不影响任何审计逻辑。

    Args:
        argv_path: 命令行第 1 个参数 (空串表示未提供)。

    Returns:
        被审 .drawio 文件的 Path。
    """
    if argv_path:  # 三级解析的第一级: 显式参数永远压过环境变量
        return Path(argv_path)
    # 先 get 判存在再取下标, 免得环境变量是空串时抛 KeyError
    base = Path(os.environ[DIAGRAM_DIR_ENV]) if os.environ.get(DIAGRAM_DIR_ENV) \
        else DEFAULT_DIAGRAM_DIR  # 末级兜底: env 与 argv 都缺省时的本机路径
    return base / "astro-best-legacy-architecture.drawio"  # 缺省审 legacy 架构图, 与模块头声明一致


def is_emoji(c):
    """判断单字符是否落在禁用 emoji 的 Unicode 区间内。

    覆盖三段区间: 补充符号与象形文字 (1F300-1FAFF)、区域指示符
    (1F1E6-1F1FF, 国旗)、装饰符号 (2700-27BF)。2700-27BF 里放行
    2794/27A1 两个箭头: 它们在架构图里当流程箭头用, 不是 emoji。

    Args:
        c: 单个字符。

    Returns:
        True 表示该字符属于禁用 emoji。
    """
    cp = ord(c)                                                                                     # 取码位
    return (0x1F300 <= cp <= 0x1FAFF) or (0x1F1E6 <= cp <= 0x1F1FF) or (
        0x2700 <= cp <= 0x27BF and cp not in (0x2794, 0x27A1)                           # emoji 区段判定, 但要排除两个箭头符号 (图里当指示线用)
    )


F = resolve_target(sys.argv[1] if len(sys.argv) > 1 else "")  # 读点 1: 整份文件当纯文本, emoji 与路径泄漏必须吃原文
raw = open(F, encoding="utf-8").read()                                                              # 读原始文本
em = sorted({c for c in raw if is_emoji(c)})                                                        # 收集去重后的 emoji 集合
print("emoji:", em if em else "NONE")                                                               # 有就列出来, 没有明确说 NONE
print("paths leaked (src/ or .py or .yaml/.md refs):", end=" ")                                     # 开始查路径泄漏

hits = re.findall(r"(?:src/|scripts/|references/|rag/|contracts/|tests/|\.py\b|\.yaml\b|\.md\b)", raw)  # 命中即说明图里泄露了实现细节
print(sorted(set(hits)) if hits else "NONE")                                                        # 有命中就列, 没有说 NONE

root = ET.parse(F).getroot()  # 读点 2: 几何审计要 DOM, 与文本审计是两条独立通道
# 多页 .drawio: 每个 <diagram> 是一个页面/视图
pages = root.findall("diagram")                                                                     # 取全部 page
print("pages:", len(pages))                                                                         # 页数
grand_v = grand_e = 0                                                                               # 顶点/边总数从零累加
for d in pages:                                                                                     # 逐页
    name = d.get("name")
    m = d.find("mxGraphModel")
    W, H = float(m.get("pageWidth")), float(m.get("pageHeight"))  # 画布逻辑尺寸, 越界判定以它为界而非以内容占用为界
    verts, edges, oob, ids = [], 0, [], []                                                          # 本页的顶点列表/边数/越界项/重复 id
    for c in m.find("root").findall("mxCell"):
        if c.get("vertex") == "1":
            g = c.find("mxGeometry")
            x, y, w, h = (float(g.get(k)) for k in ("x", "y", "width", "height"))
            ids.append((c.get("id"), x, y, w, h))  # 越界与重叠检测都靠这个五元组
            if x < 0 or y < 0 or x + w > W or y + h > H:                                            # 越界即记: 出画布的节点会在导出后错位
                # 越界: 顶点整体或部分跑出画布, 渲染时会被裁掉
                oob.append(c.get("id"))
        elif c.get("edge") == "1":
            edges += 1                                                                              # 累加边数
    # containers are intentionally overlapped by their children
    # 泳道容器的子卡片本就画在容器内部 (坐标系是容器局部), 所以容器自身
    # 必然与子卡片"重叠" —— 先把容器剔出卡片集, 否则重叠检测全是假阳性
    cont_ids = {c.get("id") for c in m.find("root").findall("mxCell")
                if c.get("vertex") == "1" and "swimlane" in (c.get("style") or "")}
    cards = [t for t in ids if t[0] not in cont_ids]  # 剔容器后再两两组合, 否则重叠检测全是假阳性
    ov = []                                                                                         # 重叠对清单
    for a, b in combinations(cards, 2):                                                             # 两两组合
        # AABB 相交判定: 两个轴上的投影都重叠才算真的压在一起
        if a[1] < b[1] + b[3] and b[1] < a[1] + a[3] and a[2] < b[2] + b[4] and b[2] < a[2] + a[4]:  # 矩形相交判定 (a 在 b 上下左右都交叠)
            ov.append((a[0], b[0]))                                                                 # 记一对重叠
    # also: cards must sit inside their container (if any) - approximate by canvas bounds
    # 本脚本只近似到"画布边界"一级的包含性检查; 严格的"卡片必须在其父泳道内"
    # 由 check_macro_collisions.py 做 (它读 parent 属性逐层校验)
    print(f"  [{name}] canvas={W:.0f}x{H:.0f} vertices={len(ids)} edges={edges} "
          f"oob={oob or 'NONE'} overlaps={len(ov)}")
    for o in ov[:10]:  # 只列前 10 对, 成片重叠全列会刷屏
        print("      OVERLAP:", o)
    grand_v += len(ids)                                                                             # 累加顶点数
    grand_e += edges                                                                                # 累加边数
print(f"TOTAL vertices={grand_v} edges={grand_e}")                                                  # 总判: 顶点数与边数是几何审计的核心指标
