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

负对照 (负对照闸, 2026-10-07 落地): 本模块同时是**门禁自检**的唯一真源。
:func:`require_nonempty_scan` 把「扫描面为空必须判红」这条纪律收在一处, 消费方不得
另写一份 —— 详见该函数 docstring 里记录的实测事故 (9 道门禁里 7 道零输入时静默放行)。

依赖: 只用标准库 ``os`` ``sys``; 不读文件内容、不 import 被检查的代码、不依赖 ``ROOT``
定位 (仓根由调用方传入), 因此单测可在任意 ``tmp_path`` 里直接跑, 假仓也不需要
预建任何目录。
"""
from __future__ import annotations

# 标准库: os 遍历目录树 (只用 os.walk / os.path 三件套, 不引 pathlib 以免与调用方的路径风格分叉)
import os

# 标准库: sys 负对照闸要把「扫描面为空」这条判红理由写进 stderr (stdout 留给报告正文)
import sys

# 门槛的**显式覆盖**通道: 判据级测试会造只有两三个文件的假仓, 那是有意为之的最小仓,
# 不该被"扫描面异常稀薄"判红。环境变量是唯一能穿过子进程边界的通道 (门禁都是脚本形态,
# monkeypatch 常量进不去), 且它必须是**显式**的 —— 默认值不动, 不传就是 100。
# 谁设这个变量, 就等于书面承认"我这条判据跑在一个故意很小的仓上"。
MIN_SCAN_OVERRIDE_ENV = "ASTRO_BEST_MIN_SCAN_FILES"  # 覆盖通道的环境变量名 (值是下限)


def _min_expected(default: int) -> int:
    """取本次运行生效的扫描面下限 (环境变量可显式覆盖)。

    Args:
        default: 代码里的默认下限。

    Returns:
        覆盖值 (非负整数) 或默认值。覆盖值非法时**退回默认**并保持 fail-safe:
        一个写错的 ``ASTRO_BEST_MIN_SCAN_FILES=abc`` 绝不能让闸变得比默认更松 ——
        那是"把自己关掉"的方向, 所以只接受整数且不接受负数。
    """
    raw = os.environ.get(MIN_SCAN_OVERRIDE_ENV)  # 现取: 同一进程内改了环境变量也要生效 (测试会改)
    if raw is None:  # 没设就是默认: 本仓日常运行走的就是这条分支
        return default
    try:
        value = int(raw)  # 只认整数: 浮点/字符串比较会引入"看起来能用"的模糊语义
    except ValueError:
        print(f"[scan_roots] {MIN_SCAN_OVERRIDE_ENV}={raw!r} 不是整数, 退回默认下限 {default}",
              file=sys.stderr)
        return default
    if value < 0:  # 负数下限会让"扫描面为空"也判绿 —— 正好是这条闸要防的方向
        print(f"[scan_roots] {MIN_SCAN_OVERRIDE_ENV}={value} 为负数, 退回默认下限 {default}",
              file=sys.stderr)
        return default
    return value

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
    # git worktree 检出目录 (.gitignore:105): 并行工作树里是**另一份**仓库的
    # 完整副本, 含它自己的 .git 与测试目录。不排除的后果实测过一次 ——
    # README 树清单会把 fork 工作树里几十个文件当成"本仓未登记的新增",
    # 逼着 --write 把工作树副本写进 SSOT, 那是把临时产物当资产登记。
    ".worktrees",
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


# 各消费方实测过的「本仓至少应有多少个 .py 进扫描面」下限, 取最小的那档当门槛。
# 321 是九道门禁共同的真实现状 (code_fingerprint 实测 compared=321), 门槛定在 100 是为了
# 给未来的正常删除留余量, 同时让「cwd 上溯到意外位置 / 某次重构搬走源码 / .gitignore
# 规则误伤」这类**扫描面塌成空**的事故必然触发 —— 空面与「仓被删到只剩 100 个文件」
# 在实践上不可区分, 而后者本来就该由人判断。
MIN_EXPECTED_PY_FILES = 100  # .py 面下限: 见本常量上方注释, 刻意留一个数量级余量


def _emit_gate_reason(gate_name: str, text: str) -> None:
    """把门禁的判红理由写成 **UTF-8 字节**再落 stderr (A5 同族修复, 2026-10-07)。

    **为什么必须绕开文本流**: 判红理由是中文, 而 ``print(..., file=sys.stderr)`` 会
    按**控制台 locale** 编码 —— 中文 Windows 是 cp936。父进程按 utf-8 解码时拿到的是
    一串替换字符 (实测 ``\ufffd\ufffd...``), 于是"负对照闸为什么判红"这句话**传不出去**。
    这不是排版瑕疵: `test_gate_negative_control.py` 断的就是它, 而它一红, 7 道门禁
    各自那条最关键的"我没扫到东西是因为…"就都成了不可读证据 ——
    门禁红了但没人知道红在哪, 正是这道闸要消灭的状态。

    直写 ``sys.stderr.buffer`` 令编码与 locale 无关: UTF-8 是门禁与测试之间唯一
    谈定的字符集。``buffer`` 不存在 (被测试替身换掉了) 时回落文本流, 行为不倒退。
    """
    payload = f"[{gate_name}] {text}\n"  # 换行自己带: 直写 buffer 不经过文本层的行缓冲
    buffer = getattr(sys.stderr, "buffer", None)  # 真解释器下是 BufferedWriter; 替身下可能是 None
    if buffer is None:  # 拿不到字节通道就退回文本流: 编码随环境, 但不能因此崩
        print(payload, end="", file=sys.stderr)
        return
    buffer.write(payload.encode("utf-8", errors="replace"))  # replace 兜底: 宁可损一个字符也不让判红理由写不出去
    buffer.flush()  # 立即刷: 门禁随后就要以非零码退出, 不刷可能来不及落到管道


def require_nonempty_scan(gate_name: str, rels: list[str]) -> bool:
    """负对照闸: 扫描面为空或异常稀少时判红, 返回 False (门禁应据此非零退出)。

    背景是 2026-10-07 记录的实测事故: 把九道门禁的扫描面清空后, **7 道 exit 0**。
    也就是说当时的「绿灯」只蕴含「没有触发任何条件」, 不蕴含「检查过且没问题」——
    cwd 不对 / ``parents[2]`` 上溯到意外位置 / 重构搬走源码 / ``.gitignore`` 误伤,
    任何一条都能让门禁齐刷刷报绿而一个文件都没检查。其中
    ``verify_no_version_keys`` 更糟: 0 个文件时它打印「**铁律 1 通过**」,
    而 ``make audit`` 是 fail-fast 的, 偏偏它排在会先判红的门禁之后, 于是**从不登场**。

    仓里已有正确范式 —— :mod:`verify_crossrefs` 与 :mod:`verify_evidence_anchors` 在
    治理文档 / 题集缺失时主动判红 (铁律 5「目标缺失 = FAIL」)。本函数把那两条形态
    提炼成所有扫描面型门禁共用的前置, 免得每道门各写一遍、各漏一遍。

    Args:
        gate_name: 门禁名 (只用于判红理由里指名, 便于定位是哪一道没扫到东西)。
        rels: 该门禁**实际**拿到的扫描面 (通常是 ``[rel for rel, _ in iter_py_files(root)]``)。

    Returns:
        扫描面达到门槛返回 True; 为空或低于门槛时往 stderr 写明理由并返回 False。

    Note:
        门槛刻意**不取实测值 321**: 门禁自己的下限若紧贴现状, 正常的批量删文件就会
        把它推到误报, 而误报的闸会被绕开 —— 那比不设闸更糟。留一个数量级的余量。
        门槛可由 :data:`MIN_SCAN_OVERRIDE_ENV` 显式下调, 但只用于**故意**的小仓
        (判据级测试的假仓), 默认值不受影响。
    """
    floor = _min_expected(MIN_EXPECTED_PY_FILES)  # 每次现取: 同一进程内改了环境变量也要生效 (测试会改)
    if len(rels) >= floor:  # 达到下限: 扫描面成立, 本闸不表态
        return True
    reason = (  # 判红理由按成因分开写: 空面与稀面是两个不同的事故, 排查方向不同
        "扫描面为空: 门禁一个文件都没检查到, 绿灯只蕴含「没有触发任何条件」"
        if not rels else
        f"扫描面异常稀薄: 仅 {len(rels)} 个 .py 进面 (下限 {floor})"
    )
    _emit_gate_reason(gate_name, f"{reason} —— 判红 (负对照闸)")  # 走 stderr 且直写 UTF-8: stdout 是报告正文, 混进去会污染 diff
    return False


# YAML 面门禁的同款下限。实测 verify_no_version_keys 在正常仓里扫到 569 个 YAML;
# 门槛同样留一个数量级余量, 口径与 MIN_EXPECTED_PY_FILES 一致 —— 贴着现状设闸的闸会被绕开。
MIN_EXPECTED_YAML_FILES = 100  # YAML 面下限: 与 .py 面同口径, 免得两类扫描面出现宽窄不一


def require_nonempty_yaml_scan(gate_name: str, paths: list[str]) -> bool:
    """:func:`require_nonempty_scan` 的 YAML 面版本, 门槛与判红理由同源。

    单列一个函数而不是给上面那个加参数: 两类扫描面 (``*.py`` 与 ``*.yaml``) 由**不同**
    的消费方用**不同**的迭代器给出, 混成一个带 ``unit`` 参数的函数会让调用方有机会
    传错组合, 而这类错恰好发生在门禁自己身上时最致命。

    Args:
        gate_name: 门禁名 (用于判红理由里指名)。
        paths: 该门禁实际拿到的 YAML 路径清单。

    Returns:
        扫描面达到门槛返回 True; 为空或低于门槛时写明理由并返回 False。
    """
    if len(paths) >= _min_expected(MIN_EXPECTED_YAML_FILES):  # 达到下限: 扫描面成立, 本闸不表态
        return True
    floor = _min_expected(MIN_EXPECTED_YAML_FILES)  # 现取: 与 .py 面同一条覆盖通道
    reason = (  # 判红理由与 .py 面同文, 只有单位不同: 两道门的排查动作是一样的
        "YAML 扫描面为空: 门禁一个文件都没检查到, 绿灯只蕴含「没有触发任何条件」"
        if not paths else
        f"YAML 扫描面异常稀薄: 仅 {len(paths)} 个 YAML 进面 (下限 {floor})"
    )
    _emit_gate_reason(gate_name, f"{reason} —— 判红 (负对照闸)")  # 同 .py 面: 直写 UTF-8, 理由才传得出去
    return False
