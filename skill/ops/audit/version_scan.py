"""version_scan.py — 全仓扫描"版本号"类违规内容 (禁版本号铁律)。

规则来源: README 治理规则 3 —「全仓不得出现发布版本号 (含 schema_version/
template_version 等标记)。变更历史只记录在 CHANGELOG.md」。

本脚本分两类报告, 由人工裁定处理方式:
  A. 强违规: `*_version:` 形态的键、`vX.Y.Z` / `X.Y.Z` 版本字面量出现在
     docstring/注释/文档正文里
  B. 需判断: `pybest-0.3.2.8` 这类历史打包产物名 — 它同时是 git 可取回的
     锚点 (6f00efeb^, 2026-10-03 实测已不在本仓历史) 已失效, 故 B 类的保留理由
         从「可回溯」降级为「保留原文供考古」; 单列出来由人决定

CHANGELOG.md 是规则明确豁免的载体, 不扫。

职责: 把"发布版本号"从全仓文本里揪出来, 按"明确违规"与"待人裁定"分两类报, 供
  人工决定删还是留。度量对象是文本行与若干正则, 不解析语义, 因此本质是**模式
  匹配器**而非类型检查器 —— 它的价值在于口径统一 (谁扫都扫出同一批)。
所属子系统: 仓库治理层 ops/audit/ 的**报告型**工具, 恒返回 0, 由 make audit 以
  非阻断方式调用。上游无代码依赖; 下游是逐条做人工裁定的人, 以及铁律 1 的执行现场。
对外接口: main() -> int (恒 0, 保持报告型定位); iter_files() 是可依赖的 seam ——
  扫描范围 (SCAN_DIRS + SCAN_FILES - SKIP_DIRS) 全由它决定, 改它等于改覆盖面。
依赖与数据流: 输入 = 工作区磁盘文本 (.py/.md/.yaml/.json/.toml/.cfg/.in/.ini/.txt),
  不读 git、不落盘; 结果只到 stdout 的 A/B 两段清单。
关键契约与不变量: 命中即报, **不自动修** —— 报告型工具一旦改文件, 就再也无法
  区分"本来干净"与"被自己擦过"; 每行只报 A 类里的第一条命中 (内层 break), 防止
  一行被四五个正则重复列出淹没清单; CHANGELOG.md 的豁免必须在代码里显式判, 不能
  靠"扫不到"蒙混。
陷阱与边界: 正则里带 (?<![\\w.\\-]) / (?![\\w.\\-]) 这类前后瞻, 是为了让 1.2.3.4
  这样的四级号和 1.2.3 落在文件路径里的情形不被误切 —— 去掉它会把半个路径当版本号
  报出来, 噪声率立刻翻十倍; 读文件用 utf-8-sig 是为吃掉 Windows 编辑器留的 BOM,
  但代价是遇到真的二进制文件会 UnicodeDecodeError, 靠 except 吞掉即"该文件未检查",
  属已知不完美; B 类 pybest 产物名单列, 因为它同时是 git 可取回的锚点, 自动删除
  等于毁掉追溯链。
"""
from __future__ import annotations

# 标准库: 正则扫描 (版本号铁律的检出层) / 仓根定位 (Path)
import io
import os
import re
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[2])  # 仓根上溯两级 (相对定位: 硬编码 monorepo 绝对路径换机即失效)
SCAN_EXTS = (".py", ".md", ".yaml", ".yml", ".json", ".toml", ".cfg", ".in", ".ini", ".txt")
# 白名单口径: 与 version_scan2.py 的全树口径互补, 两者差集才需要人看
SCAN_DIRS = ("src", "ops", "evals", "test", "examples", "rag", "templates", "contracts",
             "references", "agents", "static", "weights")
SCAN_FILES = ("README.md", "SKILL.md", "manifest.yaml", "architecture.md",
              "pipeline.yaml", "environment.yaml", ".env.example")
SKIP_DIRS = {"__pycache__", ".pytest_cache", "node_modules", ".git", "temp",  # 含 diagrams/: 布局数据满屏坐标数字, 扫进来只会淹没真违规
             "best_data", ".checkpoints", ".progress", ".logs", ".workbuddy-ai",
             ".agents", ".qdeep", "diagrams"}

# A 类: 明确的版本号形态
RE_VERSION_KEY = re.compile(r"^\s*[\"']?(schema_version|template_version|config_version|"
                            r"api_version|skill_version|pipeline_version)[\"']?\s*:", re.I)
RE_VXYZ = re.compile(r"\bv\d+\.\d+(?:\.\d+)?\b")  # 前瞻 \b 防住 rev2 / ipv6 之类被切成版本片段
# 前后否定环视是这里最关键的一处: 三段数字两侧若紧邻词字符/点/连字符, 多半是
# 文件名、模块名或四级号的一部分, 一律不算发布版本号
RE_XYZ = re.compile(r"(?<![\w.\-])\d+\.\d+\.\d+(?![\w.\-])")               # 语义化版本形态; 前后不与单词/减号相邻, 免得把 "v1.2.3-rc" 或 IP 误判
RE_PLAN = re.compile(r"Master Plan\s+v\d+(?:\.\d+)*", re.I)                          # Master Plan 版本声明: 方案文档里的发布号同属禁版本号铁律

# B 类: 历史打包产物名 (git 锚点, 单独列出)
RE_ARTIFACT = re.compile(r"pybest-0\.3\.2\.\d+")                                       # B 类: 历史打包产物名单列, 因为它同时是 git 可取回的锚点

# 标签与正则的对应表即 A 类的判定口径; 顺序 = 报告优先级, 越具体的排越前,
# 免得一个笼统的三段数字正则把 "v1.2.3" 抢先报成普通三段号丢掉 v 前缀信息
VIOLATION_LABELS = (                                                                                # 违规标签表
    ("version_key", RE_VERSION_KEY),
    ("master_plan_v", RE_PLAN),
    ("vX.Y.Z", RE_VXYZ),
    ("X.Y.Z", RE_XYZ),
)  # 兜底排最后: 笼统三段号不许抢报, 否则会丢掉 v 前缀这条信息


def iter_files():
    """遍历扫描目录下的全部文件 (跳过缓存/数据/临时目录)。

    产出一个生成器而非列表: 全仓文件数不小, 流式产出让 main() 边扫边报,
    读者不用等扫完才看到第一条命中。
    """
    for base in SCAN_DIRS:                                                                          # 按配置目录走
        base_dir = os.path.join(ROOT, base)                                                         # 目录锚点
        # 目录不存在要判而不能硬走: os.walk 遇到不存在的路径会静默不产出,
        # 少了 isdir 判断就分不清"没扫到"和"本来就没有"
        if os.path.isdir(base_dir):                                                                 # 目录存在才继续
            for dirpath, dirnames, filenames in os.walk(base_dir):                                  # 一次遍历
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]  # 原地剪枝: 数据目录与缓存里有大量数字串, 扫进来纯噪声
                for name in sorted(filenames):                                                      # 排序遍历: 报告顺序稳定
                    if name.endswith(SCAN_EXTS):                                                    # 只收白名单扩展名
                        yield os.path.join(dirpath, name)
    for name in SCAN_FILES:  # 散在仓根的关键文件不在任何 SCAN_DIRS 下, 只能单点补进来
        full = os.path.join(ROOT, name)                                                             # 拼绝对路径
        if os.path.isfile(full):                                                                    # 单点文件也要判存在
            yield full


def main() -> int:
    """入口: 扫全仓版本号模式 (A 类违规 / B 类裁定保留分别计数)。

    作用: 消费 iter_files() 产出的路径流, 逐行套 A 类与 B 类正则, 把命中分别
    记进 a_hits / b_hits 并分两段打印。关键输入只有模块级的扫描范围常量。
    返回: int 恒为 0 —— 报告型工具不参与退出码判定, 是否有违规由读报告的人裁定。
    抛什么: 读文件时的 UnicodeDecodeError / OSError 已在循环内吞掉 (该文件视为
    未检查), 除此之外不主动抛。
    """
    a_hits: list[str] = []  # 一条命中存成一行纯文本, 无结构, 便于直接 grep 与跨次 diff
    b_hits: list[str] = []                                                                          # B 类命中清单
    checked = 0                                                                                     # 已检查文件数
    for full in iter_files():                                                                       # 逐文件扫
        rel = os.path.relpath(full, ROOT).replace(os.sep, "/")  # 正斜杠: 报告里的路径要能与 README 树清单逐字对上
        if rel == "CHANGELOG.md":  # 变更历史是豁免的明文载体, 必须显式判而不能靠扫不到蒙混
            continue
        checked += 1                                                                                # 累加检查数
        try:
            with io.open(full, encoding="utf-8-sig") as fh:  # utf-8-sig 吃掉 Windows 编辑器留的 BOM, 否则首行会因不可见前缀错位
                lines = fh.readlines()                                                              # 一次读入整文件: 行号要能对上原文
        except (UnicodeDecodeError, OSError):
            # 跳过的文件属于"未检查", 不记入 checked 之外的任何统计, 也不报
            # 违规 —— 这是本工具已知的一处盲区, 靠"只扫文本扩展名"把面缩到最小
            continue
        for idx, line in enumerate(lines, start=1):                                                 # 逐行带行号
            for label, rx in VIOLATION_LABELS:  # 顺序即优先级: 越具体的越靠前, 见 VIOLATION_LABELS 处的说明
                m = rx.search(line)                                                                 # 逐个正则找
                if m:                                                                               # 命中
                    a_hits.append(f"[{label}] {rel}:{idx}  {line.strip()[:100]}")
                    # 一行只报第一条命中: 四个正则叠加报同一行会让人以为有四处问题
                    break
            else:
                if RE_ARTIFACT.search(line):  # for-else: 只有 A 类全部未命中才轮到 B 类, 优先级低于上面
                    b_hits.append(f"{rel}:{idx}  {line.strip()[:100]}")
    print(f"checked={checked}")
    print(f"\n=== A 类: 明确版本号违规 ({len(a_hits)} 处) ===")
    for h in a_hits:                                                                                # A 类逐条
        print("  ", h)
    print(f"\n=== B 类: pybest 历史打包产物名 ({len(b_hits)} 处, git 锚点待裁定) ===")
    for h in b_hits:                                                                                # B 类逐条
        print("  ", h)
    return 0  # 恒返回 0: 报告型工具不参与退出码门禁, 判定权在读报告的人手里


if __name__ == "__main__":
    raise SystemExit(main())
