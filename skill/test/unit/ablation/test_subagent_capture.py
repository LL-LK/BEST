# -*- coding: utf-8 -*-
"""E5 子代理采集表 —— 承重测试 (来源声明 fail-closed + JSON 往返 + 消费链贯通)。

被测命题: ``--require-live`` 门禁要有**通过路径**, 且这条路产出的采集表必须
自证来源。

背景: :class:`~evals.ablation.harness.captured_llm.CapturedLLM` 的契约早就在, 但
仓内**没有任何东西能产出它所需的采集文件** —— 实测 ``evals/ablation/`` 下那两个
``live-*.json`` 是报告 (含 blockers/cards) 而非采集表, 且都没有 provenance 段
(审计: 78 份 live 轨迹零模型字段)。于是 ``--require-live`` 至今无通过路径。

三条用例对应三条会真出事的失效:

1. **缺 provenance 必须拒收**: 一份不说清谁跑的 live 批次, 分数无从归因到任何
   模型能力 —— 那正是审计点名的问题。
2. **JSON 往返必须完好**: attempt 键曾建成 ``int``, 内存里查得到、落盘读回就
   查不到。那个 bug 表现为"跑批通过但复跑失败", 极难归因。
3. **消费链必须贯通**: 产出的表要真能被 ``CapturedLLM`` 按 attempt 分槽取到。

另有阳性对照: 合法的子代理采集表必须被接受 —— 没有这一组, "永远抛异常"也能让
前两条全绿。
"""
from __future__ import annotations

import json  # JSON 往返: 采集表真正的运输形态就是它
import sys  # sys.path 锚定
from pathlib import Path  # 路径拼装

import pytest  # 断言与异常

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本件在 test/unit/ablation/ 下三级
if str(SKILL_ROOT) not in sys.path:  # 幂等: 让本件能 import evals.*
    sys.path.insert(0, str(SKILL_ROOT))

from evals.ablation.harness.captured_llm import (  # noqa: E402  被测消费方
    CapturedLLM,
    CaptureMissingError,
)
from evals.ablation.harness.subagent_capture import (  # noqa: E402  被测生产端
    ALLOWED_MODEL_KINDS,
    CaptureProvenanceError,
    build_capture,
    check_capture_provenance,
    decisions_from_records,
    strip_provenance,
)


def _records(n_attempts: int = 3) -> list[dict]:
    """造一份逐 run 记录 (系统 B1 × 任务 A1 × N 轮)。"""
    return [
        {"system": "B1", "item_id": "A1", "attempt": attempt,
         "decision": {"route": "answer", "tool_calls": [{"tool": "cone_search", "args": {}}],
                      "answer_text": f"round-{attempt}"}}
        for attempt in range(1, n_attempts + 1)
    ]


class TestCaptureProvenanceIsMandatory:
    """来源声明是 fail-closed 的: 缺了就拒收, 不替调用方编一个。"""

    def test_capture_without_provenance_is_rejected(self):
        """无 provenance 的采集表必须抛 —— 否则分数无从归因。"""
        with pytest.raises(CaptureProvenanceError, match="provenance"):
            check_capture_provenance({"B1": {"A1": {"1": {}}}})

    def test_free_text_model_kind_is_rejected(self):
        """自由文本的 model_kind (如具体厂商模型名) 必须拒收。

        放开它等于让"到底是谁跑的"重新变成一句口头声明 —— 而来源一旦不可核查,
        采集表的分数就不能用来支撑任何结论。
        """
        with pytest.raises(CaptureProvenanceError, match="model_kind"):
            build_capture({}, producer="p", model_kind="某个厂商的模型-v3")

    def test_missing_producer_is_rejected(self):
        """缺 producer (说不清谁跑的) 必须拒收。"""
        with pytest.raises(CaptureProvenanceError, match="producer"):
            build_capture({}, producer="", model_kind="subagent")

    def test_allowed_model_kinds_are_exactly_two(self):
        """合法取值只能是 subagent / human —— 集合本身就是一条判据。"""
        assert set(ALLOWED_MODEL_KINDS) == {"subagent", "human"}


class TestCaptureRoundTripsThroughJson:
    """采集表要真能落盘再读回 —— 那是它的实际运输方式。"""

    def test_attempt_keys_survive_json_round_trip(self, tmp_path):
        """attempt 键必须是字符串: 用 int 建键则内存查得到、读回查不到。

        那个缺陷的表现是"跑批通过但复跑失败", 极难归因, 所以用一条专门的用例钉住。
        """
        capture = build_capture(decisions_from_records(_records(3)), producer="mavis-subagent")
        path = tmp_path / "capture.json"
        path.write_text(json.dumps(capture, ensure_ascii=False), encoding="utf-8")
        reloaded = json.loads(path.read_text(encoding="utf-8"))

        llm = CapturedLLM({"id": "B1"}, strip_provenance(reloaded))  # 读回后仍要可消费
        for attempt in (1, 2, 3):  # 逐轮取: 三轮都在才算分槽完整
            route, calls = llm.plan({"id": "A1"}, attempt=attempt)
            assert route == "answer"
            assert calls, f"attempt={attempt} 取不到决策"

    def test_provenance_stays_out_of_the_key_namespace(self):
        """provenance 不得被当成一个名叫 provenance 的"系统"。"""
        capture = build_capture(decisions_from_records(_records(1)), producer="mavis-subagent")
        check_capture_provenance(capture)  # 校验能读到 -> 说明它在顶层而非 decisions 内
        decisions = strip_provenance(capture)
        assert "provenance" not in decisions, "provenance 混进了决策键空间"
        assert "schema_version" not in decisions


class TestCaptureIsConsumable:
    """产出端与消费端必须贯通, 否则 --require-live 依然没有通过路径。"""

    def test_captured_llm_reads_subagent_decisions(self):
        """合法子代理采集表必须被 CapturedLLM 正常消费 (阳性对照)。"""
        capture = build_capture(decisions_from_records(_records(2)), producer="mavis-subagent")
        llm = CapturedLLM({"id": "B1"}, strip_provenance(capture))
        route, calls = llm.plan({"id": "A1"}, attempt=1)
        assert route == "answer"
        assert calls[0]["tool"] == "cone_search"

    def test_missing_attempt_still_fails_closed(self):
        """采集表缺某一轮时必须抛, **不得**拿第 1 轮顶替。

        顶替会把 N 次重复压成 1 次, 直接毁掉"重复数不足不得谈显著性"那条阻断项。
        """
        capture = build_capture(decisions_from_records(_records(1)), producer="mavis-subagent")
        llm = CapturedLLM({"id": "B1"}, strip_provenance(capture))
        with pytest.raises(CaptureMissingError, match="attempt=2"):
            llm.plan({"id": "A1"}, attempt=2)

    def test_same_family_bias_is_disclosed(self):
        """同源偏差必须在采集表里显式声明 (用户裁定: 接受但必须披露)。"""
        capture = build_capture(decisions_from_records(_records(1)), producer="mavis-subagent")
        prov = check_capture_provenance(capture)
        assert prov["same_family_bias"] is True, "子代理与判定器同族, 该偏差必须写在表里"
        assert "不可用于声称" in prov["claim_scope"], "claim_scope 必须限定这份表的用途"


if __name__ == "__main__":  # 手动跑也能看结论
    sys.exit(pytest.main([__file__, "-v"]))
