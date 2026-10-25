# -*- coding: utf-8 -*-
"""evals.equivalence.import_isolation — 铁律 6「零跨实验 import」静态守护。

纪律: ``evals/<exp>/`` 六个实验各自自包含, 不得互相 import; 唯一允许的
跨实验引用是纯数据字典 ``evals/_data/`` 与本守卫所在的 ``evals/equivalence/``。

为什么需要它: 铁律 6 的机械守护只能落在这里 —— 别的关卡都留了口子:
``ops/audit/verify_import_graph.py`` 唯一的分层判据是"可导入层不得 import ops
层", 对 ``head in IMPORTABLE_BASES`` 的模块只验"能否导入", 因此
``evals.semantics.x`` → ``evals.ablation.y`` 完全放行; 唯一的 AST 禁 import
守卫 ``evals/groundtruth/gold/guard_no_src_imports.py`` 作用域只限 E2 的
``gold/`` 一个目录。

一旦跨实验 import 发生, 同一段逻辑会在两处独立演化并悄悄漂移, 而"等价性由
evals/equivalence 守护"这类声明也就失去意义 (E5 的 transport 与 prescreen 两处
声明即属悬空: equivalence/ 下并没有任何断言覆盖它们)。

本守卫沿用同目录 sentinel.py 的 AST 扫描范式。

相对导入的判定 (2026-10-04 突变实验后补): 原实现对 ``ast.ImportFrom`` 一见
``node.level`` 非零就 ``continue``, 等于**无条件放行全部相对导入** —— 实测往
``evals/nl2tool/`` 注入 ``from ..repro import stats`` 后该 import 真的可用,
而本守卫、verify_import_graph、equivalence 断言与 E1 测试全绿 (铁律 6 被
完全绕过)。现在相对导入一律**先解析成绝对点分模块名再判**: 落在
``evals/`` 内另一实验即违规, 落在本实验内 (``.helpers`` / ``..sibling`` /
``from . import x``) 才放行。判据从"level 大小"换成"解析出的目标包归属"。
"""
from __future__ import annotations

# 标准库: AST 静态解析 / 正则 (剥掉 evals 前缀做实验归属判定) / 路径
import ast
from pathlib import Path

EVALS_ROOT = Path(__file__).resolve().parents[1]  # 扫描根 = evals/ 本身, 不是本目录

# 六个实验目录名 (evals/ 下的顶层子包 = 实验)
_EXPERIMENTS = ("nl2tool", "groundtruth", "semantics", "robustness",
                "ablation", "repro")  # 名单写死: 新增实验须显式登记, 漏登记等于免检

# 允许被跨实验 import 的目标前缀 (纯数据字典 + 守门设施自身)
_ALLOWED_PREFIXES = ("evals._data", "evals/equivalence", "evals.equivalence")  # 白名单只此三类; src 不在其中


def _experiment_of(path: Path, root: Path) -> str:
    """文件所属实验名 (不在任何实验目录下则返回空串)。

    必须相对**传入的 root** 计算: 守卫自证要用临时目录造违规样本, 若写死
    ``EVALS_ROOT`` 会在 ``relative_to`` 上直接抛 ValueError。
    """
    rel = path.relative_to(root)     # 相对传入的 root, 绝不写死: 自证样本在临时目录里
    parts = rel.parts                                                                         # 相对路径的第一段即实验名, 嵌套多深都不影响归属判定
    return parts[0] if parts and parts[0] in _EXPERIMENTS else ""  # 顶层段不在名单 = 共享件 (_data/paths)


def _normalize(module: str) -> str:
    """把模块路径归一: 反斜杠/正斜杠统一成点号, 去掉首尾多余的点。

    **不剥掉前导的 ``evals.``** —— 白名单 ``_ALLOWED_PREFIXES`` 本身就带
    ``evals.`` 前缀, 剥掉会让所有共享件判成"不在白名单"从而全量误报。
    归一只统一分隔符与首尾多余点号, 不做任何语义上的前缀删减。
    """
    return module.replace("\\", ".").replace("/", ".").strip(".")  # 两种分隔符都收: 白名单里有斜杠形态


def _is_allowed(module: str) -> bool:
    """是否属于允许跨实验引用的白名单目标。"""
    norm = _normalize(module)                                                                 # 先归一再比前缀: 斜杠形态的导入语句也要能命中白名单
    return any(norm.startswith(p) for p in _ALLOWED_PREFIXES)  # 前缀匹配: 白名单自身还有子模块


def _package_of(path: Path, root: Path) -> str:
    """文件自身所属的点分包名 (``evals`` 之前的部分由调用方拼回)。

    ``evals/nl2tool/x.py`` -> ``nl2tool``; ``evals/nl2tool/sub/y.py`` ->
    ``nl2tool.sub``。``__init__.py`` 多一层语义 (包本身), 故按父目录计, 深度
    仍与 level 对得上。示例路径是**形态说明**, 不是对仓内文件的断言。
    """
    rel = path.relative_to(root)                       # 相对 root: 自证样本在临时目录里, 写死 EVALS_ROOT 会抛 ValueError
    parts = list(rel.with_suffix("").parts)            # 去掉扩展名, 逐段作为包路径
    if parts and parts[-1] == "__init__":              # __init__ 代表包自身, 不是包里的一个模块
        parts.pop()                                    # 于是包路径就是它的父目录
    else:
        parts.pop()                                    # 普通模块: 包路径 = 去掉文件名的目录链
    return ".".join(parts)


def _resolve_relative(path: Path, root: Path, node: ast.ImportFrom) -> str | None:
    """把 ``from ..X import y`` 解析成 ``evals.`` 命名空间下的绝对点分包名。

    越出 evals/ 根 (退层过头) 时返回 None —— 那种形态在真实代码里本身就是错
    的, 但把它与"跨实验"判据混在一起会让报错指错方向, 故交由导入图/运行期去管。

    **必须补 ``evals.`` 前缀**: 包路径是相对 evals/ 根算的, 未经前缀化时
    ``from ..repro import stats`` 解析出的是裸 ``repro``, 下游按 ``evals.`` 的
    第二段取实验归属就会取到空串而漏判 (这正是 2026-10-04 突变实验暴露的形态)。
    """
    pkg = _package_of(path, root)                      # 当前包, 点分形式
    depth = len(pkg.split(".")) if pkg else 0           # 退 level 层后剩下的层数
    up = node.level - 1                                 # level=1 退 0 层, 停在当前包
    if up > depth:                                      # 退过头 = 越出 evals 根
        return None                                     # 射程外, 不由本守卫判
    base = ".".join(pkg.split(".")[: depth - up])       # 退层后的绝对包前缀
    if node.module:                                     # from ..X 形态: 再接上模块名
        base = f"{base}.{node.module}" if base else node.module
    if not base:                                        # from . import x 且退到 evals 根本身
        return None                                     # 指向 evals/ 根, 不是任何实验, 射程外
    return f"evals.{base}"                              # 归一到 evals 命名空间: 下游判定统一按第二段取实验名


def scan_cross_experiment_imports(root: Path = EVALS_ROOT) -> list[str]:
    """扫描 evals/ 下的跨实验 import (返回违规清单, 逐条带 file:line)。"""
    problems: list[str] = []        # 空清单 = 通过; 非空 = 有实验越界 (铁律 6 被破)
    for path in sorted(root.rglob("*.py")):  # 排序遍历: 清单顺序稳定, CI diff 才有意义
        owner = _experiment_of(path, root)                                                     # 先定位归属: 不属于任一实验的共享件才谈得上被跳过
        if not owner:                                                                      # 顶层共享件与 _data 不属任一实验, 不在本守卫射程内
            continue  # evals/ 顶层的共享执行器与 _data 不属任一实验
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            problems.append(f"{path.name}: 语法错误 {exc}")  # 解析不了也必须报: 静默跳过等于放行
            continue
        for node in ast.walk(tree):                                                         # 全树遍历: 函数体内的延迟 import 同样要被抓出来
            modules: list[str] = []  # 本节点声明的模块名 (Import 与 ImportFrom 取法不同)
            if isinstance(node, ast.ImportFrom):                                            # from 形态: 相对导入要先解析成绝对包名
                if node.level:                                                              # 相对导入: 解析出真实目标再判, 不再无条件放行
                    resolved = _resolve_relative(path, root, node)                           # 把 ..repro 这类形态还原成 repro.something
                    if resolved is None:                                                    # 退到 evals/ 之上: 射程外, 不由本守卫判
                        continue
                    modules = [resolved]                                                   # 解析成功即按绝对包名走下面同一套判定
                elif node.module:                                                           # 绝对 from 导入才直接取主模块名
                    modules = [node.module]                                                 # from 形态只取主模块名, 导入进来的子模块从属于它
                # from . import x (level 非零且 module 为空) 已由上面的 _resolve_relative 处理
            elif isinstance(node, ast.Import):
                modules = [a.name for a in node.names]  # 逗号导入逐个判: 混进一个越界模块也要抓
            for mod in modules:                                                                 # 逗号导入逐个判定: 一次里混进一个越界模块也要报
                if _is_allowed(mod):                                                            # 白名单优先: 纯数据字典是铁律 6 唯一开的口子
                    continue
                norm = _normalize(mod)                                                            # 归一只做一次, 后面两处判定共用同一串模块名
                if not norm.startswith("evals."):
                    continue      # 兄弟裸导入是 SA-P3-7 约定, 属实验内引用
                target = norm.split(".")[1] if len(norm.split(".")) > 1 else ""  # 第二段 = 实验归属名
                if target in _EXPERIMENTS and target != owner:                                  # 自引用不算越界: 同实验内部的互相引用本来就允许
                    problems.append(                                                        # 带 file:line 记录: 违规要能一键跳到那一行看
                        f"{path.relative_to(root).as_posix()}:{node.lineno}: "
                        f"实验 {owner} 跨实验 import {mod} (铁律 6: 实验须自包含, "
                        f"只允许 evals/_data 纯数据字典与 evals/equivalence)"
                    )  # 带 file:line: 违规要能一键定位到那一行
    return problems


def selftest() -> bool:
    """守卫自证: 当前 evals/ 树必须零跨实验 import (有即清单)。"""
    problems = scan_cross_experiment_imports()   # 零参 = 扫全树; 只读 AST 不执行被扫模块, 故天然离线零请求
    for p in problems:                                                                            # 逐条打印不截断: 一次跑批就把全部越界点看清
        print(f"- {p}")  # 逐条打印不截断: 一次跑批就能看清全部越界点
    return not problems   # 空清单才通过, 与"0 干净 / 1 有违规"的退出码契约一致


if __name__ == "__main__":
    raise SystemExit(0 if selftest() else 1)  # 退出码契约: 0 干净 / 1 有违规
