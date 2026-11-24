# -*- coding: utf-8 -*-
"""evals.nl2tool.context_primers — 上下文前缀台账的**唯一**读取口。

存在理由: 28 条里有 5 条用户原话自带指代 ("就在刚才那片天区""这颗星"),
单轮盲测下它们是无解题; 但另有 4 条**缺指代就是考点** (NL2T-18/19/20/22),
给它们补上文会让"应澄清"变成"可作答", 失效方向是**变绿**。所以"给谁补、
补什么"必须由一份台账显式声明, 而不是临场发挥。

本件被两处消费, 两边的需求不同但不能各读各的 (否则台账一改就对不上):
  * ``make_batch_input`` (跑批前): 取 ``turns``, 生成给人粘贴的上文文本;
  * ``runner`` (判分): 取 ``bindings``, 把标注里的 ``<...>`` 占位符**具化**成
    primer 声明的具体值再比对 —— 这是"杜撰坐标现形"的关键, 见下。

能力边界: 只读 yaml, 不联网、不调模型、不改标注 (``tasks.yaml`` 冻结)。
不判分、不生成文本 —— 判分在 graders, 文本生成在 make_batch_input。

白盒锚点: docs/eval-E1-nl2tool.md §9.1 (跑批隔离的操作口径)。
"""
from __future__ import annotations

# 标准库: 路径锚定 / 类型标注
from pathlib import Path
from typing import Any

# 脚本直跑时 sys.path[0] 只含本目录 — 挂 evals/ 供 paths 兄弟裸导入。
# 本件只依赖 paths (YAML 装载), 不 import graders/make_batch_input, 避免与
# 判分核心或生成器形成循环依赖: 它是两者的共同上游。
import sys

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))   # evals/

from paths import load_yaml_file  # noqa: E402

PRIMERS_PATH = _HERE.parent / "context_primers.yaml"


def load_primers(primers_path: Path = PRIMERS_PATH) -> tuple[dict[str, dict], set[str]]:
    """装载台账 → ({题号: 前缀规格}, 禁止补上文的题号集合)。

    两条硬校验, 都是防手滑且**错了方向会让分数假变好**:
    1. ``no_context`` 里的题若配了 primer → 显式失败 (那几题缺指代就是考点);
    2. primer 里出现 ``assistant`` 回合 → 显式失败 (那是上一轮的正确调用示范,
       等于给答案, 比漏题更直接)。
    """
    if not primers_path.is_file():
        return {}, set()
    raw = load_yaml_file(primers_path) or {}
    primers = raw.get("primers") or {}
    no_ctx = set(raw.get("no_context") or [])

    for tid, spec in primers.items():
        if tid in no_ctx:
            raise SystemExit(
                f"{tid} 在 no_context 清单里却配了 primer — 该题缺指代就是考点, "
                f"补上下文会让它从『应澄清』变成『可作答』, 拒绝生成"
            )
        for turn in (spec or {}).get("turns") or []:
            role = str((turn or {}).get("role", "")).strip().lower()
            if role == "assistant":
                raise SystemExit(
                    f"{tid} 的 primer 含 assistant 回合 — 那是上一轮的正确调用示范, "
                    f"等于给答案。primer 只允许 user / tool_result"
                )
            if role not in ("user", "tool_result"):
                raise SystemExit(f"{tid} 的 primer 回合 role='{role}' 非法 — 只允许 user / tool_result")
    return primers, no_ctx


def load_context_bindings(primers_path: Path = PRIMERS_PATH) -> dict[str, dict[str, Any]]:
    """题号 → 占位符具化表, 形如 ``{"NL2T-10": {"ra": 10.68, "dec": 41.27}}``。

    **为什么要有这一步**: 标注里 ``ra: "<上下文天区的 ra>"`` 这类占位符在判定时
    按通配处理 (值来自上一步返回或用户补充, 机比无从下手)。通配本身没错 ——
    错在**单轮盲测下没有任何东西能约束它**: 模型杜撰一个坐标去查, 占位符照样
    通配, 于是"编造上下文"不仅不扣分, 还能因为换算做对而拿到 convert 满分。

    补了 primer 之后, 上文里声明了天区, 占位符就有了确定值 —— 本函数把它取出来,
    判定时替换进去, 杜撰坐标立刻现形 (与硬编码期望值同口径比对)。

    向后兼容: 台账里没配 ``bindings`` 的题返回空表, 该维退回通配。这不是放水,
    而是"没有上文可依"时唯一诚实的处置 —— 报告应把这类题点名为"未具化"。
    """
    primers, _no_ctx = load_primers(primers_path)
    out: dict[str, dict[str, Any]] = {}
    for tid, spec in primers.items():
        b = (spec or {}).get("bindings") or {}
        if b:
            out[tid] = dict(b)
    return out
