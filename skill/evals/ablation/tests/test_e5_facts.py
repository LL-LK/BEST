# -*- coding: utf-8 -*-
"""evals.ablation.tests.test_e5_facts — 事实层的承重断言。

为什么单列一份 (2026-10-10): `critical` 里写死的数值与冻结数据脱钩后, 表述通道
**不可能**被诚实作答者通过 (实测塌缩到 3.4%)。事实层改为从观测现导, 是**判定口径变更**,
必须把两侧都钉住:
  * 观测里**有**的事实, 答案说了 -> 必须判过 (哪怕换了写法);
  * 观测里**没有**的事实 -> **不得**要求陈述 (不许凭空要求);
  * 答案漏说 -> 必须判缺 (不许变成橡皮图章)。
"""
from __future__ import annotations

# 本地: 被测事实层
from evals.ablation.metrics.facts import check_facts, expected_facts, facts_pass


def _run(returned: int, total: int, truncated: bool, uri: str = "", trust: str = "") -> dict:
    """造一条最小 run 记录 (只带事实层要读的信封)。"""
    return {"reported": {"returned_count": returned, "total_count": total, "truncated": truncated,
                         "provenance": {"stable_uri": uri, "content_trust": trust}}}


class TestExpectedFacts:
    """事实必须**从观测现导**, 不许凭空要求。"""

    def test_facts_come_from_observation(self):
        """行数/总数/截断位都从信封取。"""
        facts = expected_facts(_run(174, 174, False))
        labels = [f["label"] for f in facts]
        assert "实返行数" in labels and "服务端总数" in labels and "截断位" in labels

    def test_absent_provenance_is_not_required(self):
        """观测里没有稳定引用 -> **不得**要求答案陈述它 (负对照: 防凭空要求)。"""
        facts = expected_facts(_run(3, 3, False))
        assert not any(f["label"] == "稳定引用" for f in facts)

    def test_present_provenance_is_required(self):
        """观测里确有稳定引用 -> 要求陈述, 且只比 scheme://catalog/path 段。"""
        facts = expected_facts(_run(3, 3, False, uri="best://ps1/cone?ra=180.0&sr=5.0"))
        uri_facts = [f for f in facts if f["label"] == "稳定引用"]
        assert uri_facts and uri_facts[0]["value"] == "best://ps1/cone"


class TestCheckFacts:
    """陈述判定: 表示可换, 事实不可缺。"""

    def test_paraphrase_counts_pass(self):
        """「共 3 个源」要顶得住观测 returned_count=3 (与 critical 同一套概念归一)。"""
        result = check_facts("共 3 个源，服务端总数 3，未截断。", _run(3, 3, False))
        assert result["missing"] == []

    def test_wrong_count_is_missing(self):
        """数值不符即判缺 (负对照: 防橡皮图章)。"""
        result = check_facts("命中 4 行，未截断。", _run(3, 3, False))
        assert "实返行数" in result["missing"]

    def test_stale_assertion_scenario_now_passes(self):
        """**本层存在的理由**: 观测 174 行时, 说 174 就应判过 —— 旧 critical 要的 "2 行" 是错的。"""
        verdict = facts_pass("在 300″ 内检索 ps1 返回 174 行，服务端总数 174，未截断。",
                             _run(174, 174, False))
        assert verdict["pass"] is True and verdict["n_expected"] == 3

    def test_truncated_flag_both_notations(self):
        """``truncated=true`` 与「已截断」是同一个事实; 计数须**带量纲**说出来。"""
        assert check_facts("结果已截断：实返 3000 行，服务端总数 3700 行。",
                           _run(3000, 3700, True))["missing"] == []

    def test_bare_number_without_unit_is_missing(self):
        """**实测口径**: 光写数字不带量纲不算陈述计数 —— 松到"数字出现即可"会让该通道
        通过率顶到 0.966 天花板而失去分辨力 (两版实测对照见 metrics/facts.py)。"""
        assert "服务端总数" in check_facts("服务端总数 3700。", _run(3000, 3700, False))["missing"]

    def test_missing_provenance_is_reported(self):
        """观测有稳定引用而答案没写 -> 判缺 (披露面)。"""
        verdict = facts_pass("返回 3 行。", _run(3, 3, False, uri="best://ps1/cone?ra=1"))
        assert "稳定引用" in verdict["missing"]
