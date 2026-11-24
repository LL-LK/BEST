"""astro-best 测试包的共享 pytest 配置。

职责:
- 锚定 ``src.*`` 导入根: 无论 pytest 从哪个工作目录启动, 测试导入的都是本
  skill 的实现, 而不是环境里其他同名包;
- 提供规格文件 (skills-spec) 的统一解析入口: 大仓路径优先, 独立交付时降级
  到 skill 内快照, 两者都不可用时显式失败 (Fail-Closed);
- 提供门禁判据级测试共用的**假仓依赖闭包**求解器 ``gate_dependency_closure``:
  详见该函数的 docstring (为什么不能用整目录复制);
- E5 清理: 原先这里的 spec_section / mock_skill_config 两个共享 fixture 零消费者
  (已 grep 全 test/ 树证实), 连同 5 个无消费者的本地同名副本一并删除; 唯一有
  消费者的本地副本 (test/unit/contracts/test_gen_gates.py::spec_section) 保留。
"""

from __future__ import annotations

# 标准库: ast 解析门禁源码取依赖 / sys.path 锚定 (os/sys), 规格解析失败时的显式告警
# (warnings), 路径定位 (pathlib), 类型标注 (typing)
import ast as _ast
import os as _os
import sys as _sys
import warnings
from pathlib import Path
from typing import Any

# 第三方: 规格文件 YAML 解析 (本文件不再定义 fixture, 故不 import pytest —
# E5 清理时随两个死 fixture 一并移除)
import yaml

# 把仓库根 (本文件的上级目录) 插到 sys.path 首位, 保证 ``import src.*`` 在任何
# 启动目录下都解析到本 skill 源码树。
_PKG_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), _os.pardir))  # 包根塞进 sys.path: 让 src.* 在任何工作目录下都能导入
if _os.path.isdir(_PKG_ROOT) and _PKG_ROOT not in _sys.path:                                        # 包根可导入才注入: 已注入就不重复
    _sys.path.insert(0, _PKG_ROOT)  # 判存在再插: 目录缺失时静默跳过, 不让路径污染掩盖真实导入错误

# 两个路径锚点: _SKILL_DIR 指向 astro-best skill 根 (test/ 的上级), _REPO_ROOT
# 指向大仓根 — 规格文件优先从大仓读, skill 独立交付时降级读包内快照。
_SKILL_DIR = Path(__file__).resolve().parent.parent  # skill 根与仓根分两级: 门禁命令按父目录跑, 只认父目录会指错仓
_REPO_ROOT = _SKILL_DIR.parent                                                                      # 仓根锚点: 测试要从仓根找资源

_AUDIT_DIR = _SKILL_DIR / "ops" / "audit"                                     # 门禁脚本真身所在目录


def gate_dependency_closure(gate: str) -> list[str]:
    """算出门禁在 ``ops/audit/`` 内的**同目录依赖闭包** (含它自己), 供造假仓用。

    门禁之间是同目录裸名互导 (``comment_audit`` 导 ``line_scope``, 四道门禁导
    ``scan_roots``), 而它们都用 ``parents[2]`` 定位仓根、没有 root 参数, 所以判据级
    红测试只能靠"把脚本复制进 ``假仓/ops/audit/``"来换扫描面。复制**整目录**会往假仓
    扫描面里塞进一堆与被测命题无关的 ``.py`` (实测两个通道, 见
    ``test_gate_criterion_red.py::build_fake_repo`` 的完整记录): 任一副本自身出现违规
    (注释密度 / DEADPARAM / 超 400 行未登记) 都会让**干净对照组**变红, 而那些用例
    声称测的是落位覆盖面 / Q7 口径 / 版本键 / 错误码契约。只复制闭包, 假仓里剩下的
    每个 ``.py`` 才都是被测对象或它的依赖。

    按**真实 import** 递归算出而不手抄名单: 手抄会在门禁新增依赖时立刻过期, 而过期的
    闭包会 ``ModuleNotFoundError`` —— 那会**伪装成"门禁判红了"** (判据审计 D5-05
    点名的脆弱性), 比缺依赖本身更难查。

    Args:
        gate: 门禁模块名 (不带 ``.py``)。

    Returns:
        需要复制的文件名集合 (含 ``.py``), 已排序 —— 排序让复制次序跨机可复现。
    """
    names: set[str] = set()                                        # 已纳入闭包的门禁名
    queue: list[str] = [gate]                                     # 待解析队列: 从被测门禁起步
    while queue:                                                   # 逐个展开, 直到没有新依赖
        name = queue.pop()                                         # 取一个待解析的门禁
        if name in names:                                          # 已在闭包里: 不重复解析 (也防 import 环)
            continue
        names.add(name)                                            # 先入集合: 环状 import 时也不会无限展开
        tree = _ast.parse((_AUDIT_DIR / f"{name}.py").read_text(encoding="utf-8"))  # 只解析, 不执行
        for node in _ast.walk(tree):                               # 全树收集 import
            mods: list[str] = []
            if isinstance(node, _ast.Import):                      # import x / import x.y
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, _ast.ImportFrom) and node.module and node.level == 0:  # from x import y (相对 import 不算)
                mods = [node.module.split(".")[0]]
            for mod in mods:                                       # 只有同目录真有文件才算依赖
                if (_AUDIT_DIR / f"{mod}.py").is_file() and mod not in names:
                    queue.append(mod)                              # 入队, 下一轮展开它的依赖
    return sorted(f"{n}.py" for n in names)                        # 排序: 复制次序与失败信息跨机可复现

def audit_gate_names() -> list[str]:
    """返回 ``make audit`` 实跑的门禁名 (实现层唯一真源, 2026-10-07 起)。

    **为什么不再解析 Makefile**: 那一版的 ``audit:`` 是九行 recipe, 但 GNU make 的
    多行 recipe 是 **fail-fast** 的 —— 第 5 道 ``verify_crossrefs`` 判红即停, 它后面
    4 道**从不执行**, 含铁律 1 的唯一执行者 ``verify_no_version_keys``。改成单行
    转发到 :mod:`ops.audit.run_all_gates` (九道全跑、末尾汇总), 于是"哪些门禁在跑"
    这个事实搬进了那个模块的 ``HARD_GATES``, Makefile 只剩一行转发。

    测试里**必须**改用本函数而不是继续匹配 ``ops/audit/xxx.py`` 子串: 那样的断言在
    转发之后会恒失败, 而恒失败的断言会被当成"环境问题"忽略 —— 于是"接线核对"这条
    门禁就此静默消失, 正是本仓反复出现的那类腐烂。

    Returns:
        门禁名列表, 按 ``HARD_GATES`` 的声明顺序 (顺序本身有信息: 它是汇总表的行序)。
    """
    if str(_AUDIT_DIR) not in _sys.path:  # 幂等: 同目录裸名导入 (与门禁自身同纪律)
        _sys.path.insert(0, str(_AUDIT_DIR))
    from run_all_gates import HARD_GATES  # noqa: PLC0415  延迟导入: 门禁目录不在默认 sys.path 上

    return [gate for gate, _args in HARD_GATES]


def get_spec_path() -> Path:
    """返回当前生效的规格文件路径 (大仓优先, 随包快照降级)。

    作用: 只回答"用哪一份 spec"这个问题, 不负责解析。关键参数无。
    返回: 存在性未经本函数校验的 Path —— 降级分支只保证给出候选位置,
    真正的"两边都没有就炸"由 :func:`get_spec_data` 承担, 避免两处各判一次
    而出现"有路径但读不出内容"的中间态。
    """
    # 权威源: 大仓统一规格, 多 skill 共享同一份 skills-spec.yaml
    repo_spec = _REPO_ROOT / "scripts" / "refactor" / "spec" / "skills-spec.yaml"
    if repo_spec.is_file():  # 仓内 spec 优先: 裁剪克隆里它才是最新的一份
        return repo_spec
    # 降级源: 本 skill 独立交付时随包的快照, 保证脱离大仓也能跑测试
    # RET504: 直接 return, 不落中间变量
    return _SKILL_DIR / "references" / "skills-spec.local.yaml"


def get_spec_data() -> dict[str, Any]:
    """统一规格解析器 (真实物理文件校验, 拒绝虚假硬编码通过):
    1. 优先尝试大仓路径 REPO_ROOT / scripts/refactor/spec/skills-spec.yaml
    2. 若不存在，读取本地独立交付快照 SKILL_DIR / references/skills-spec.local.yaml
    3. 若两者均不存在，显式抛出 FileNotFoundError 阻断测试 (Fail-Closed)

    Q-35 修复: 大仓 spec 解析失败不再静默 pass, 显式 WARN 后按 local 快照继续。
    """
    repo_spec = _REPO_ROOT / "scripts" / "refactor" / "spec" / "skills-spec.yaml"
    if repo_spec.is_file():                                                                  # 本仓的 spec 存在才注册: 母仓那份不参与本仓测试
        try:
            # utf-8-sig: 容忍大仓规格文件可能带的 BOM 头
            return yaml.safe_load(repo_spec.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            warnings.warn(
                f"repo spec 解析失败 ({repo_spec}: {exc}); 降级读 references/skills-spec.local.yaml",  # 解析失败只降级不断言: 环境问题不该伪装成用例失败
                RuntimeWarning,
                stacklevel=2,
            )

    local_spec = _SKILL_DIR / "references" / "skills-spec.local.yaml"
    if local_spec.is_file():                                                                        # 随包快照存在才解析: 两个规格源都缺时交给下方 fail-closed
        try:
            # 独立交付快照同样按 utf-8-sig 读, 与上方大仓口径一致
            return yaml.safe_load(local_spec.read_text(encoding="utf-8-sig"))
        except Exception as e:
            raise RuntimeError(f"Failed to load references/skills-spec.local.yaml: {e}") from e

    # Fail-Closed: 两个规格源都不可用时, 任何 spec 断言都无法验证 — 必须显式
    # 炸掉, 不能返回空 dict 让测试"假通过"。
    raise FileNotFoundError(
        "No skills specification found! Checked repo spec and references/skills-spec.local.yaml"
    )

