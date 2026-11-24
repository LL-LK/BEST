# -*- coding: utf-8 -*-
"""verify_no_version_keys.py — 禁版本号铁律 (铁律 1) 的**阻断式**全仓门禁。

为什么需要它 (2026-10-04 突变实验 A6-02): 铁律 1 只在四个 SSOT 目录
(``contracts/`` ``templates/`` ``references/`` ``rag/knowledge/``) 加上
``evals/ablation`` 上有**阻断**检查, 而 ``make audit`` 的六条硬门禁里**不含
任何版本号门禁** —— 唯一看得见的 ``ops/audit/version_scan.py`` 恒 ``return 0``
(报告型)。实测往 ``evals/cases/*.yaml`` (30+ 份, 全在 SSOT 之外) 加
``version: 9.9.9``: 七道门禁全 exit 0、29 条版本专项测试全过、全量 pytest
仍绿。绕过铁律 1 的成本是一行 YAML, 代价是零。

因此本门禁把口径钉死在**判据本身**上: 全仓递归扫 ``*.yaml``/``*.yml``
(不是四个白名单目录 —— 白名单口径本身就是后门), 命中即 exit 1。

与 ``version_scan.py`` 的分工: 那两个脚本 (``version_scan.py`` /
``version_scan2.py``) 扫的是**文本形态**的版本字面量 (``vX.Y.Z`` / ``X.Y.Z``
/ Master Plan), 噪声大且需人判读, 因此刻意保持报告型; 本门禁只判**键名**
这一种高置信形态 —— 键名没有"需人判读"的余地, 存在就是违规, 可以阻断。

判据口径 (刻意窄, 宁可不报不误报):
  - 命中的必须是**行首的键** (可带缩进 / YAML 列表项破折号 / 键引号),
    与 ``evals/audit/__init__.py`` 的 ``VERSION_MARKER_RE`` 同口径;
  - 键名取整词, 故 ``api_version_string`` 这类**词中缀**不命中;
  - **``data_version`` 属数据血缘, 铁律 1 明确豁免** (全仓现存 42 处合规声明,
    误杀它等于把数据溯源信息也一并禁掉)。

对外接口: ``scan(root)`` 返回违规清单, ``main()`` 返回退出码。两者都以
``root`` 为显式参数 —— 门禁的判据必须能在**临时目录**里被注入缺陷后实跑
验证, 否则"它能不能抓住自己该抓的东西"永远没人知道 (这正是本门禁自己
要修的那类假绿)。
所属子系统: 仓库治理层 ops/audit/ 的**硬门禁** (make audit 接线)。只读不写:
命中即报, 修不修由人决定, 门禁自己绝不擦除现场。
"""
from __future__ import annotations

# 标准库: re 版本键形态 / pathlib 仓根定位
import io
import re
import sys
from pathlib import Path

# 同目录裸名导入: 直跑时 sys.path[0] 就是 ops/audit/ (与 count_code_lines 同理)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_roots import require_nonempty_yaml_scan  # noqa: E402  负对照闸的唯一出处

ROOT = str(Path(__file__).resolve().parents[2])  # 仓根上溯两级 (相对定位: 硬编码绝对路径换机即失效)

# 版本号键的判定正则: 行首(可缩进) + 可选列表项破折号 + 可选键引号 + 键名 + 冒号。
# 键名用 (?:...) 整词组锚定, 故 api_version_string 这类词中缀不命中 (反向误报防线)。
VERSION_KEY_RE = re.compile(
    r"^[ \t]*(?:-[ \t]*)?['\"]?"
    r"(schema_version|template_version|config_version|"
    r"scoring_rubric_version|manifest_version|version)"
    r"['\"]?[ \t]*:",
    re.M,
)
# 铁律 1 的数据血缘例外: data_version 记录的是**数据来源快照**, 不是本仓发布号。
# 单独成常量而非就地内联, 是为了让"为什么放过它"在代码里可查, 而不是靠读者
# 恰好看漏 (审计实验证明: 靠读代码发现例外条款, 迟早会被人顺手删掉)。
EXEMPT_KEYS = frozenset({"data_version"})

# 扫描范围: 全仓递归。不设目录白名单 —— 白名单口径本身就是 A6-02 的病根
# (SSOT 之外的 30+ 份 evals/cases/*.yaml 正是靠它免检的)。
SKIP_DIRS = frozenset({
    ".git", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules",
    "temp", "best_data", ".checkpoints", ".progress", ".logs", ".agents",
})
SCAN_EXTS = (".yaml", ".yml")


def iter_yaml_files(root: str) -> list[str]:
    """递归列出 root 下全部待扫 YAML (跳过缓存/临时/数据目录)。

    排序返回: 报告顺序必须可复现, 否则同一份违规在两次跑批里长得不一样,
    整改者就没法用 diff 确认"是不是同一批"。
    """
    base = Path(root)
    hits: list[str] = []
    for path in sorted(base.rglob("*")):  # 整树递归: 目录白名单已被刻意取消
        if not path.is_file() or path.suffix not in SCAN_EXTS:  # 只收 YAML: 键名判据只对 YAML 有意义
            continue
        # 逐段判断是否落在跳过目录里: 用 parts 而不是字符串包含, 否则
        # "src/temporary_pkg/x.yaml" 这类正当路径会被 ".tmp" 之类的子串误伤
        if SKIP_DIRS.intersection(path.relative_to(base).parts):  # 命中任一跳过目录即剪枝
            continue
        hits.append(str(path))
    return hits


def scan(root: str = ROOT) -> list[str]:
    """扫全仓 YAML 的版本号键 (返回违规清单, 逐条带 file:line)。

    Args:
        root: 扫描根。**必须是显式参数** —— 判据级测试要把缺陷注入临时目录
            后实跑本函数, 写死 ROOT 会让"门禁能不能抓住该抓的"永远无法验证。

    Returns:
        违规行清单; 空清单 = 通过 (与 "0 干净 / 1 有违规" 的退出码契约一致)。
    """
    problems: list[str] = []
    for full in iter_yaml_files(root):
        try:
            text = io.open(full, encoding="utf-8-sig", errors="replace").read()  # utf-8-sig 吃掉 Windows BOM
        except OSError:  # noqa: PERF203
            # 读不到即"未检查": 不报违规, 但这属于已知盲区 (见模块 docstring)
            continue
        rel = Path(full).relative_to(Path(root)).as_posix()  # 正斜杠: 与 README 树清单逐字可比
        for idx, line in enumerate(text.splitlines(), start=1):
            m = VERSION_KEY_RE.search(line)
            if not m:  # 非键名形态 (行内提及 / 词中缀) 按设计不命中
                continue
            if m.group(1) in EXEMPT_KEYS:  # data_version = 数据血缘, 铁律 1 豁免
                continue
            problems.append(f"{rel}:{idx}: {line.strip()[:100]}")
    return problems


def main() -> int:
    """入口: 扫全仓 YAML 版本键, 有违规即非零 (硬门禁退出码契约)。

    返回: int —— 0 = 干净, 1 = 有违规。本门禁**必须**阻断: 铁律 1 若只靠人
    读报告, 它的实际效力就等于 A6-02 突变实验里测出的零。
    """
    yaml_files = iter_yaml_files(ROOT)  # 扫描面先落变量: 负对照闸与 scan 必须用同一份清单
    # 负对照 (2026-10-07): 本门禁曾被列为**最误导**的一道 —— 扫描面为 0 时它照样
    # 打印「铁律 1 通过」并 exit 0, 而 make audit 是 fail-fast 的、它排在会先判红的
    # 门禁之后, 于是「最该拦住违规的那道门, 在最需要它的场景下从不登场」。
    # 闸放在 scan() 之前: 先确认扫到了东西, 才有资格谈「没发现违规」。
    if not require_nonempty_yaml_scan("verify_no_version_keys", yaml_files):
        return 1
    problems = scan(ROOT)  # 扫全仓 (不是四个 SSOT 目录): 白名单口径就是病根
    if not problems:  # 干净时也打印查了多少文件: 空转门禁比没有门禁更危险
        checked = len(yaml_files)
        print(f"checked={checked} 个 YAML: 未发现版本号键 (铁律 1 通过)")
        return 0
    print(f"发现 {len(problems)} 处版本号键 (违反铁律 1: 任何 YAML 不得声明发布版本号):")
    for p in problems:  # 逐条不截断: 门禁红时要能直接定位到那一行
        print(" -", p)
    return 1  # 阻断: 恒返回 0 的门禁挡不住任何东西


if __name__ == "__main__":
    raise SystemExit(main())  # 退出码契约: 0 干净 / 1 有违规
