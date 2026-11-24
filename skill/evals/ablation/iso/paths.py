# -*- coding: utf-8 -*-
"""evals.ablation.iso.paths — 隔离批**根目录的唯一真源** (SSOT), 以及"够不着仓"的断言。

**为什么根目录必须是 SSOT**: 2026-10-11 实测事故是"投放器搬了家、审计器没跟着搬" ——
``stage`` 用 ``%TEMP%/e5_scratch`` 而 ``audit`` 仍用 ``ROOT/temp/scratch``, 结果后验审计
对新位置的 10 个批次一律回"没有该批次", **检测门全程空转**。两边各写一个字面量,
就没有一处能拦住这种漂移; 把它收成一个函数, 漂移在结构上不可能发生。

**为什么 scratch 必须在仓库之外**: D-17 的实测取证是 scratch 原来在 ``temp/scratch/<批次>/``,
从那里**向上走三级**就是仓根, 代理读到了 ``evals/ablation/items.yaml`` (答案键) 并把
24 条 route 对齐到键 (与键一致率 100%, 未污染的两轮只有 58–63%)。口头禁令"不要往上级
目录走"已被反复证伪, 所以改成**结构上够不着**: 向上逐层都找不到仓根与答案键。

对外接口: ``scratch_root()`` / ``batch_dir()`` / ``prompt_root()`` / ``assert_outside_repo()``。
"""
from __future__ import annotations

# 标准库: 环境变量覆盖 (单测与跨机复跑要能换根)
import os

# 标准库: 路径类型与逐层上溯
import pathlib

# 标准库: 系统临时目录定位 (scratch 的默认落点)
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[3]                       # 仓根: evals/ablation/iso/ 上溯三级
ABLATION_DIR = ROOT / "evals" / "ablation"                                # 实验包根: 答案键住在这里, 隔离面以它为界
ANSWER_KEY = ABLATION_DIR / "items.yaml"                                  # 答案键: 隔离断言要逐层确认它够不着

_SCRATCH_NAME = "e5_scratch"                                              # scratch 目录名: 与 D-17 修法后的实测落点一致
ENV_SCRATCH = "E5_SCRATCH_ROOT"                                           # 环境变量: 单测与跨机复跑靠它换根
ENV_PROMPTS = "E5_ISO_PROMPTS"                                            # 环境变量: 逐格提示词源目录 (默认 temp/decision_iso)


def scratch_root() -> pathlib.Path:
    """隔离批的根目录 (``%TEMP%/e5_scratch``; 可用环境变量覆盖)。

    Returns:
        scratch 根路径。**结构保证**: 默认落点在系统临时目录下, 向上逐层都到不了仓根
        —— 这是 D-17 的修法, 不是禁令。
    """
    override = os.environ.get(ENV_SCRATCH, "").strip()                    # 显式覆盖优先: 单测要能指向 tmp_path
    if override:
        return pathlib.Path(override)                                     # 覆盖值不校验位置: 调用方自行保证隔离
    return pathlib.Path(tempfile.gettempdir()) / _SCRATCH_NAME            # 默认: 系统临时目录, 与仓库不同盘不同根


def batch_dir(batch: str) -> pathlib.Path:
    """某一批次的目录。

    Args:
        batch: 批次名 (投放与审计共用同一解析口径, 不再各拼一次路径)。

    Returns:
        ``<scratch_root>/<batch>``。
    """
    return scratch_root() / batch                                         # 单一拼法: 投放器与审计器都走这里


def prompt_root() -> pathlib.Path:
    """逐格提示词的源目录 (默认 ``temp/decision_iso``, 可用环境变量覆盖)。

    Returns:
        提示词源目录。**诚实标注**: 该目录在 gitignored 的 ``temp/`` 下, 由
        ``temp/build_isolated_prompts.py`` 从 ``items.yaml`` 现导 —— 生成器本身
        **尚未入库**, 属已知可追溯性缺口 (见 ``docs/e5-isolation-gate-verification``)。
    """
    override = os.environ.get(ENV_PROMPTS, "").strip()                    # 覆盖优先: 提示词源换了位置不用改代码
    if override:
        return pathlib.Path(override)
    return ROOT / "temp" / "decision_iso"                                 # 默认: 逐格单文件提示词的现导产物


def assert_outside_repo(path: pathlib.Path) -> None:
    """断言该目录**向上任意层都够不到仓库** (D-17 的结构性判据, fail-closed)。

    Args:
        path: 待判定的 scratch 目录。

    Raises:
        ValueError: 该目录自身或其任一层祖先就是仓根, 或该层下存在答案键 —— 即"够得着"。
    """
    resolved = path.resolve()                                             # 先归一: 软链与 .. 都会骗过逐层比较
    cursor: pathlib.Path | None = resolved
    while cursor is not None:                                             # 逐层上溯到文件系统的根
        if cursor == ROOT:                                                # 撞到仓根 = 代理从这里能走到答案键
            raise ValueError(f"scratch 落在仓库内: {resolved} (祖先 {cursor} 即仓根 —— D-17 会重演)")
        if (cursor / "evals" / "ablation" / "items.yaml").is_file():      # 撞到答案键 = 同一失效模式的另一形态
            raise ValueError(f"scratch 的祖先层有答案键: {cursor} —— D-17 会重演")
        parent = cursor.parent
        cursor = None if parent == cursor else parent                     # 到文件系统根即停: 根的 parent 是自身
