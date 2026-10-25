# -*- coding: utf-8 -*-
r"""ops.audit.scan_roots — 「哪些 .py 进门禁」的唯一真源 (覆盖面层)。

从四道门禁里抽出的扫描范围真源 (2026-10-05, 判据审计 D5-01): ``count_code_lines.py`` /
``comment_audit.py`` / ``verify_doc_consistency.py`` / ``code_fingerprint.py`` 各自抄了
同一份目录白名单 ``SCAN_DIRS = ("src", "ops", ...)``, 而**白名单式扫描的缺口只能靠
不断补**: 实测在 ``agents/`` 下放一个 900 净行的文件, 四道门禁全部 exit 0 ——
一处缺口同时废掉「单文件 400 净行」「注释质量」「文档一致性」「代码零改动」四条判据
(D5 复核于 2026-10-05, 复现结果一致: 三门禁均 exit 0, 文件数不含该文件)。

口径因此改成**黑名单**: 走遍仓内**所有** .py, 只排掉"本来就不是本仓源码"的目录。
排除项是**有限且稳定**的三类 (见下表), 而白名单的缺口随目录增加而无界; 差别在
**默认方向**: 新建一个目录放 .py 时, 黑名单口径下它**自动进门禁**, 白名单口径下它
**自动免检** —— 而"自动免检"正是这次事故的形态。

============================  ====================================================
排除项                          排除理由 (加一项前先答这一列)
============================  ====================================================
``.`` 前缀的全部隐藏目录        版本库与工具状态: ``.git`` / ``.mypy_cache`` /
                               ``.pytest_cache`` / ``.ruff_cache`` / ``.venv`` /
                               ``.workbuddy*``。隐藏目录在本仓一律不是资产
                               (``.gitignore`` 同样按这个口径写), 且已实测
                               ``git ls-files`` 里没有任何以 ``.`` 开头的目录分量
``__pycache__`` / ``*.egg-info`` 解释器与打包缓存: 里面的 .py 是**副本**不是源
``venv`` / ``env`` / ``node_modules`` /                                依赖与构建产物
``site-packages`` / ``build`` /                                     (装一个包不该让门禁变红;
``dist`` / ``eggs`` / ``htmlcov``                                    覆盖率报告随跑随变)
``temp``                       铁律 3 的临时区 (gitignored): 突变实验的**探针故意**
                               在这里写超限文件, 计它进门禁等于让取证手段自伤
``best_data`` / ``statcatalog`` /                                   gitignored 的运行时数据
``output``                     与外部星表素材区: 是数据不是代码
============================  ====================================================

对外接口: ``iter_py_files(root)`` 返回 ``(相对路径, 绝对路径)`` 的**已排序**列表
(相对路径一律正斜杠, 与 README 树清单逐字可比); ``is_excluded_dir(name)`` 供需要
自己剪枝的消费方复用。消费方**一律不另列目录清单** —— 那是本模块存在的全部理由。

依赖: 只用标准库 ``os``; 不读文件内容、不 import 被检查的代码、不依赖 ``ROOT``
定位 (仓根由调用方传入), 因此单测可在任意 ``tmp_path`` 里直接跑, 假仓也不需要
预建任何目录。
"""
from __future__ import annotations

# 标准库: os 遍历目录树 (只用 os.walk / os.path 三件套, 不引 pathlib 以免与调用方的路径风格分叉)
import os

# 显式排除的目录名 (逐项理由见模块头表格; 隐藏目录与 *.egg-info 由 is_excluded_dir 另判)
EXCLUDED_DIRS = frozenset({
    # 依赖与第三方环境: 这些目录里的 .py 不是本仓资产
    "venv", "env", "site-packages", "node_modules",
    # 构建与安装产物
    "build", "dist", "eggs", "htmlcov",
    # 解释器与打包缓存
    "__pycache__",
    # 铁律 3 的临时区: 突变探针故意在这里写超限/违规文件
    "temp",
    # gitignored 的运行时数据与外部素材区 (与 .gitignore 同口径)
    "best_data", "statcatalog", "output",
})


def is_excluded_dir(name: str) -> bool:
    """判断一个目录名是否应被排除在门禁扫描面之外 (判据的单一出口)。

    三条判据, 顺序即优先级: 显式名单 → 隐藏目录 (``.`` 前缀) → ``*.egg-info``
    打包缓存。放在同一个函数里是因为**三处判据的并集就是"覆盖面"**, 拆开写
    就等于允许某个消费方只抄其中一条 —— 那正是 D5-01 的成因。

    Args:
        name: 裸目录名 (不含路径)。

    Returns:
        True 表示该目录不进门禁; False 表示要继续走。
    """
    if name in EXCLUDED_DIRS:                       # 显式名单优先: 理由逐条写在模块头表格里
        return True
    if name.startswith("."):                        # 隐藏目录 = 版本库/工具状态/虚拟环境, 本仓一律不是资产
        return True
    return name.endswith(".egg-info")               # 打包缓存: setup.py 产出的元数据目录


def iter_py_files(root: str) -> list[tuple[str, str]]:
    """列出 ``root`` 之下**全部**应当进门禁的 .py (黑名单口径, 非目录白名单)。

    走遍整棵树, 只按 :func:`is_excluded_dir` 剪枝; 因此"新建一个目录放 .py"
    会被自动纳入覆盖面, 而不需要在这里补任何名字 —— 这与旧的白名单口径正好相反。

    Args:
        root: 扫描根 (通常是仓根)。刻意做成参数而不是模块常量: 单测与假仓要能
            指向任意目录, 模块级 ``ROOT`` 会把这种复用变成不可能 (line_scope 同理)。

    Returns:
        ``[(相对路径, 绝对路径), ...]``, 按相对路径升序 —— 排序让两次运行的清单
        逐字可比 (determinism 治理面要求)。``root`` 不存在时返回空列表 (裁剪克隆
        不该因此崩掉, 与旧口径"目录缺失即跳过"的行为一致)。
    """
    if not os.path.isdir(root):                     # 根不存在即无文件可列: 裁剪过的克隆不该中断扫描
        return []
    found: list[tuple[str, str]] = []               # 累加器: 边走边攒, 末尾统一排序
    for dirpath, dirnames, filenames in os.walk(root):  # 一次遍历拿全, 避免每个文件再走一次磁盘
        dirnames[:] = sorted(d for d in dirnames if not is_excluded_dir(d))  # 原地剪枝: 重新绑定新列表对 os.walk 无效
        for name in sorted(filenames):              # 排序遍历: 报告顺序稳定, 便于逐次比对
            if not name.endswith(".py"):            # 净行预算与注释规范只管 Python 源文件
                continue
            full = os.path.join(dirpath, name)      # 拼绝对路径: 读盘与度量都基于它
            rel = os.path.relpath(full, root).replace(os.sep, "/")  # 正斜杠: 与 README 树清单逐字可比
            found.append((rel, full))               # 入表: (相对路径, 绝对路径) 一一对应
    found.sort(key=lambda pair: pair[0])            # 末尾按相对路径定序: 跨文件系统的遍历顺序不稳定, 排序是唯一的稳定源
    return found
