# -*- coding: utf-8 -*-
"""evals.ablation.harness.captured_llm — E5 真模型决策的采集回放适配器 (live 臂)。

能力边界: 用**真实模型跑批采集下来的决策**替换 :class:`ScriptedLLM` 的确定性
替身, 让 ``--require-live`` 门禁第一次有通过路径。边界与三条硬纪律:
  1. **只换模型层, 不换任何判据**: 执行仍走 :func:`make_adapter` 的工具面与
     快照回放, 打分仍走 metrics/composite.py, 本模块只提供 ``plan`` 与
     ``render`` 两个方法的真实模型产物。
  2. **缺采集即抛, 绝不回落替身** (铁律 5 禁 fail-open): 采集文件缺某个
     (系统, 任务) 组合时直接抛, **不**退回 ScriptedLLM —— 静默回落会让一个
     标着 mode=live 的批次里混进替身结果, 那正是 ``--require-live`` 要防的事。
  3. **按 attempt 分槽**: 采集文件以 attempt 编号索引多轮采样, 缺该轮即抛,
     绝不用第 1 轮顶替 (那会把 N 次重复压成 1 次, 直接毁掉 §11 阻断项 7)。

采集文件形态 (由仓外采集脚本产出, 本仓不生成):
``{ "<系统 id>": { "<任务 id>": { "<attempt>": {"route": "answer",
"tool_calls": [{"tool": ..., "args": {...}}], "answer_text": "..."} } } }``

白盒锚点: docs/eval-E5-baseline-ablation.md §14 (接真模型是待写代码, 本模块
即该待写项的落地) / evals/ablation/harness/adapters.py ``make_llm`` (留缝的
唯一构造点, 本模块通过它热替换) / E5 §11 阻断项 7 (重复数不足不得谈显著性)。
"""
from __future__ import annotations

# 标准库: 类型标注 (采集表的 JSON 由 runner 侧读好传进来, 本模块不碰文件)
from typing import Any

# 本地: 模型替身抽象与运行结果容器 (本模块是 LLMAdapter 的第二个实现)
from evals.ablation.harness.adapters import LLMAdapter, RunOutcome


class CaptureMissingError(KeyError):
    """采集文件缺 (系统, 任务, attempt) 组合 — fail-closed, 不回落替身。

    独立成异常类型而不是直接用 KeyError: 调用方要能只捕获"采集缺失"这一种
    失败并原样上抛, 而把别的 KeyError (比如某条记录内部缺键) 误当成同一件事
    去回落替身 —— 那正是纪律 2 要防的静默换臂。
    """


class CapturedLLM(LLMAdapter):
    """回放真实模型采集决策的模型层 (E5 live 臂)。

    与 :class:`ScriptedLLM` 的分工: ScriptedLLM 按 ``items.yaml`` 的
    ``expect_tools`` 合成轨迹, 测的是**装配表**的相对排序; 本类回放真实模型
    当时的决策, 测的是**模型在该装配下**的表现。两者跑的是同一套执行层与
    判据, 所以成绩卡可以横向对读。
    """

    def __init__(self, system: dict, capture: dict) -> None:
        """绑定装配与整份采集表 (整表传进来: 覆盖率检查在 plan 逐次做)。

        Args:
            system: 装配字典 (取 ``id`` 作采集表的顶层键)。
            capture: 已解析的采集字典, 形态见模块头。
        """
        self.system = system                                                          # 装配存下: 报错信息与覆盖率记账都要用
        self.system_id = str(system.get("id") or "")                                  # 采集表顶层键就是装配 id
        self.capture = capture or {}                                                 # 整表持有: 缺组合要在 plan 里现查现抛
        self._seen: set[tuple[str, int]] = set()                                     # 已消费的 (任务, attempt): 末尾据此报覆盖率

    def _slot(self, item: dict, attempt: int) -> dict:
        """取某 (任务, attempt) 的采集记录; 缺任一层即抛 CaptureMissingError。

        Raises:
            CaptureMissingError: 装配未采集 / 任务未采集 / 该轮未采集 (三种都算
                覆盖不完整, 都不许用别的轮次或别的替身顶替)。
        """
        by_item = self.capture.get(self.system_id)
        if not isinstance(by_item, dict):  # 整个装配都没采: 顶层就断
            raise CaptureMissingError(f"采集文件缺装配 {self.system_id!r} 的任何决策")
        by_attempt = by_item.get(str(item.get("id")))
        if not isinstance(by_attempt, dict):  # 装配采了但这条任务没采
            raise CaptureMissingError(f"采集文件缺 {self.system_id}/{item.get('id')}")
        record = by_attempt.get(str(attempt))
        if not isinstance(record, dict):  # 采了这条任务但缺这一轮: 不得拿第 1 轮顶替
            raise CaptureMissingError(
                f"采集文件缺 {self.system_id}/{item.get('id')} 的 attempt={attempt}"
                f" (已采集轮次: {sorted(by_attempt)})")
        self._seen.add((str(item.get("id")), int(attempt)))   # 记账在取到之后: 抛了不算已覆盖
        return record

    def plan(self, item: dict, attempt: int = 1) -> tuple[str, list[dict]]:
        """产出 (路由, 工具调用序列) — 原样回放采集决策, 不做任何加工。

        与父类签名的差异: 父类是 ``plan(self, item)``, 这里多一个 ``attempt``。
        这是刻意的: 真实模型的多次采样只能靠 attempt 索引, 而 ScriptedLLM 的
        确定性输出不需要。:func:`run_once` 通过 try/except 兼容两种签名。
        """
        record = self._slot(item, attempt)
        calls = record.get("tool_calls") or []                     # 缺该键当零调用: 该问/该拒的模型确实零调用
        return str(record.get("route") or "answer"), list(calls)   # 路由缺省 answer: 与 ScriptedLLM 同口径

    def render(self, item: dict, outcome: RunOutcome, attempt: int = 1) -> str:
        """回放采集时的答案文本 (多 attempt 同形覆盖)。

        刻意**不用** outcome 重渲染: 真实模型的措辞是该次采样的产物, 事后用
        模板重写等于把模型答案换成脚本答案, live 批就名不副实。执行层观测到的
        行集仍然完整进 RunOutcome, 判据照常用。
        """
        return str(self._slot(item, attempt).get("answer_text") or "")

    def coverage(self) -> dict[str, Any]:
        """已消费覆盖率 — 供 runner 写进报告, 让"采了多少"可见而非靠猜。"""
        total = sum(len(v) for v in self.capture.values() if isinstance(v, dict))
        return {"consumed": len(self._seen), "captured": total,
                "complete": len(self._seen) == total and total > 0}
