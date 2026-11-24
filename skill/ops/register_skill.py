#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ops/register_skill.py — astro-best 技能登记辅助。

能力边界: 向 StarWhisper/twskills 技能登记表输出 astro-best 登记条目 (YAML)。
仅本地登记辅助: 零网络、零凭据、零副作用 (只打印, 不写共享登记表——防多 Agent 并发写冲突)。

沿革: 合并原 bridge/register-astro-best.ps1 + .sh 双脚本 (Q-32):
  - 原脚本路径多跳两级 (..\\..\\..\\_shared) → 修正为相对本脚本一级上跳;
  - 原脚本硬编码登记版本号 → 按全仓禁版本号铁律移除;
  - conda_env 取 astro-base (与共享环境登记表 _shared/environments/ 一致,
    **不是** environment.yaml 里的 astro-best —— 那个环境从未被创建, 见下方注释)。

conda_env 口径 (本仓与共享登记表分处两个 git root, 以**共享登记表**为准):
`_shared/skill-engine/runtime/dep_resolver.py` 的 ``SkillEnvDeclaration.conda_env``
缺省值是 ``astro-base``; `_shared/environments/create_envs.ps1`` 只会创建那 9 个
环境, 目录里**没有** astro-best.yaml。故 ``astro-best`` 是一个不存在的环境名 ——
照它装环境必然失败。此前本脚本写 astro-best、共享登记表写 astro-base, 两边分叉,
宿主按表选环境时装错环境。现两侧统一为 astro-base。
"""
from __future__ import annotations

# 标准库组:
#   argparse —— --check 开关 (只探测共享登记表是否存在, 不打印条目)
#   pathlib  —— 定位共享登记表 skill-registry.yaml (相对本脚本一级上跳)
import argparse
from pathlib import Path

OPS_DIR = Path(__file__).resolve().parent           # 本文件所在目录: 定位共享登记表的第一跳
SKILL_ROOT = OPS_DIR.parent                        # astro-best 根: 条目 path 字段就按这个目录名登记
# 共享登记表: 位于 skill 仓库根的 _shared/ 下, 由多 skill 共同维护。
# 本脚本只读它判断存在性, 从不写入 —— 防多 Agent 并发写互相覆盖。
REGISTRY_PATH = SKILL_ROOT.parent / "_shared" / "skill-registry.yaml"  # 共享登记表在母仓: 本 skill 是独立 git root, 但登记表是跨 skill 的公共件

# 登记条目 (无版本号字段——版本信息由 CHANGELOG.md 承载, 该文件已入版本控制)
ENTRY: dict[str, object] = {                                                                       # 登记条目: 只登记身份信息, 零网络零凭据
    "name": "astro-best",
    "path": "astro-best",                          # 相对技能仓库根的目录名, 宿主按它定位 skill
    "domain": "collection",
    "description": "BEST database high-precision photometry query (two-phase REST/lightcurve/crossmatch)",  # 与共享登记表逐字一致 (那边是本字段的 SSOT)
    "maturity": "alpha",                           # 生命周期字段: 治理文档裁定它随强度不联动, 保持 alpha
    "conda_env": "astro-base",                     # 以 _shared/environments/ 的实况为准 (只有 astro-base 被创建); 宿主据此选环境
    # mcp_service: 2026-10-06 起本仓**不再提供** MCP 入口 (server 实现连同其
    # E1 评测场景已整体移除)。字段保留为显式 null 而不是删键, 是因为共享
    # 登记表 `_shared/skill-registry.yaml` 里这一条仍然存在 —— 删键会让对账
    # 把它当成"本仓漏填"而不是"如实为空"。null 在此表达的是"本仓没有这个
    # 能力", 与"有实现但未接线"是两回事, 不要再按后者解读。
    "mcp_service": None,
}


def render_entry() -> str:
    """渲染登记条目为 YAML 文本 (缩进两级, 适配 skills 列表)。

    Returns:
        可直接粘进 skill-registry.yaml 的 `skills:` 列表下的 YAML 片段。
        含空格或破折号的值加双引号, 避免 YAML 把这些字符当语法。
    """
    lines: list[str] = []                                                                           # 输出行累积
    for key, value in ENTRY.items():                 # 按声明顺序输出: 粘表的人按这个顺序读
        if value is None:                                                                   # None 也要打印: 让人知道这项确实没有, 而不是没查
            # mcp_service 显式 null: 本仓已移除 MCP 入口 (实现与评测场景一并
            # 下线), null 表达的是"本仓没有这个能力", 不是"还没接线"。
            lines.append(f"    {key}: null")
        elif isinstance(value, str) and (" " in value or "—" in value):
            lines.append(f'    {key}: "{value}"')    # 含空格/破折号必须加引号, 否则 YAML 会被拆行
        else:
            lines.append(f"    {key}: {value}")
    return "\n".join(lines)


def registry_entry_fields() -> dict[str, object] | None:
    """读共享登记表里 astro-best 那一条的字段; 读不到即返回 None。

    只按文本行解析, 不 import yaml: 本脚本的边界是"零第三方依赖的登记辅助"
    (见模块 docstring), 为一次对账引入 pyyaml 会把那个边界破掉。登记表是
    单层 ``- name: xxx`` 列表 + 两级缩进字段, 逐行扫足够且不会误取别的条目。

    Returns:
        该条目的字段字典; 文件缺失 / 该条目不存在时返回 None。
    """
    if not REGISTRY_PATH.is_file():  # 登记表不在 (本仓可独立 checkout) → 无从比对
        return None
    fields: dict[str, object] = {}
    inside = False  # 是否已越过本条目的起始行
    for raw in REGISTRY_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()  # 只看内容, 缩进另算
        if line.startswith("- name:"):  # 新的列表条目 → 先判断是不是本条目
            inside = line.split(":", 1)[1].strip() == ENTRY["name"]
            if inside:
                fields["name"] = ENTRY["name"]  # 条目名本身也是受对账的字段, 不能漏采
            continue
        if not inside or not line or line.startswith("#"):
            continue  # 未进入本条目 / 空行 / 注释行都跳过
        key, sep, value = line.partition(":")  # 只认 ``key: value`` 形态
        if sep:
            fields[key.strip()] = value.strip()
    return fields or None


def check_consistency() -> tuple[list[str], bool]:
    """逐字段比对本脚本的 ENTRY 与共享登记表里的实况条目。

    这道对账存在的理由: ``--check`` 原先只判"表在不在", 于是本脚本写
    ``conda_env: astro-best``、表里写 ``astro-base`` 这种分叉能一直绿着 ——
    而注释明写"宿主据此选环境", 分叉的后果是宿主装错环境, 且要到运行期
    ImportError 才暴露。

    Returns:
        ``(不一致项列表, 登记表是否可读)``。登记表不可读时列表为空且第二项为
        False —— 调用方须据此**显式告知**而不是静默当成通过 (铁律 5)。
    """
    fields = registry_entry_fields()               # 读实况条目 (读不到即返回 None)
    if fields is None:
        return [], False  # 无从比对: 不是"一致", 是"没查成"
    drift: list[str] = []
    for key, mine in ENTRY.items():  # 逐字段比: 本脚本认定的值 vs 表里的值
        theirs = fields.get(key)      # 表里该字段的原始取值
        if key == "mcp_service" and theirs in ("null", ""):
            theirs = None  # 表里显式写 null 与不写键同义, 归一后再比 (本仓该字段恒为 null)
        if str(theirs) != str(mine):
            drift.append(f"{key}: 本脚本 {mine!r} vs 登记表 {theirs!r}")
    return drift, True


def main() -> int:
    """登记辅助入口: 打印条目供人工/宿主粘表; --check 做逐字段一致性对账。

    Returns:
        --check: 登记表缺失或字段不一致返回 1, 全部一致返回 0;
        普通模式恒 0 (只打印, 没有失败态)。
    """
    parser = argparse.ArgumentParser(description="astro-best 技能登记辅助 (打印登记条目)")
    parser.add_argument(                                                                            # 命令行参数定义
        "--check",
        action="store_true",
        help="检查共享登记表是否存在, 且其 astro-best 条目与本脚本 ENTRY 逐字段一致",
    )
    args = parser.parse_args()                                                                      # 取实参

    if args.check:                                  # --check 存在的理由: 宿主要能无副作用地问"表在不在、且登记的还对不对"
        drift, readable = check_consistency()
        if not readable:                            # 表读不到: 非零退出, 不当成通过
            print(f"registry not found or unreadable: {REGISTRY_PATH}")
            return 1
        print(f"registry found: {REGISTRY_PATH}")
        if drift:                                  # 有分叉即非零: 宿主据此判定"登记表需修"
            print("registry entry drifts from ops/register_skill.py ENTRY:")
            for item in drift:
                print(f"  - {item}")
            print(f"修复目标: {REGISTRY_PATH} (astro-best 条目)")
            return 1
        print("registry entry matches ENTRY (field-by-field)")
        return 0

    print(f"astro-best skill ready at: {SKILL_ROOT}")  # 先报本地位置: 粘表的人常在这一步找错目录
    if REGISTRY_PATH.is_file():                                                                     # --check 模式: 只报状态, 不写
        print(f"To register, add the following to {REGISTRY_PATH}:")
    else:
        # 登记表缺失时给出两条线索: 表路径 + 本 skill 路径, 便于人工补表
        print(f"Skill registry not found at {REGISTRY_PATH}")
        print("astro-best located at:", SKILL_ROOT)
    print()                                                                                     # 末尾空行: 让 shell 提示符不贴在输出后面
    print("skills:")
    print(render_entry())                           # 片段原样打印: 粘到共享表哪个位置由人决定
    return 0                                        # 普通模式恒 0: 本脚本没有失败态


if __name__ == "__main__":
    raise SystemExit(main())                        # 退出码直接透传给调用方 shell
