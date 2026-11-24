# -*- coding: utf-8 -*-
"""evals.ablation.tests.test_e5_prereg_labels — 预登记标签的**证据强度**维度承重断言。

为什么单列一份 (2026-10-10): 实测到**标签与证据强度反相关** ——
A5 的 ``HR_num`` 不一致对 6:7 (抛硬币, p=1.0) 拿到最强标签"反向",
而 A3 的 ``RejectAcc`` 18:0 (全票, p<1e-4) 只记"未命中"。
故标签升级为"方向 × 可辨性", 并把两侧都钉住:
  * 全票效应必须记 ``同向·显著`` (不得被写成"未命中");
  * 抛硬币必须记 ``·不可辨`` (不得被写成裸"反向");
  * **没测过**与**测了不显著**必须区分 (``·未配对`` vs ``·不可辨``) —— 混同即 fail-open。
"""
from __future__ import annotations

# 本地: 被测的配对层与标签层
from evals.ablation.metrics.pairing import SIGNIFICANT_MIN, mcnemar_exact
from evals.ablation.metrics.prereg import _aggregate, _label


class TestLabel:
    """标签两维: 方向 × 可辨性。"""

    def test_unanimous_is_significant(self):
        """全票 (b=18, c=0) 必须记显著。"""
        assert _label(True, {"significant": True}) == "同向·显著"

    def test_coin_flip_is_indistinguishable(self):
        """6:7 这种抵消必须记不可辨, 不得记成裸"反向"。"""
        assert _label(False, {"significant": False}) == "反向·不可辨"

    def test_untested_is_not_indistinguishable(self):
        """**关键负对照**: 没做检验 (pair=None) 不得被写成"测了不显著"。"""
        assert _label(False, None) == "反向·未配对"
        assert _label(True, None) == "同向·未配对"

    def test_significance_threshold(self):
        """|b-c| >= 6 才算显著 (n=30 配对题下 McNemar p<0.05 的临界)。"""
        assert SIGNIFICANT_MIN == 6
        assert mcnemar_exact(18, 0) < 0.05          # 全票 -> 显著
        assert mcnemar_exact(6, 7) == 1.0           # 抛硬币 -> 毫不显著
        assert mcnemar_exact(3, 0) > 0.05           # 3:0 未达显著 (实测 p=0.25)
        assert mcnemar_exact(0, 0) == 1.0           # 无不一致对 -> 无信息


class TestAggregate:
    """汇总: 取最强, 且原样沿用; 无方向不得盖过命中。"""

    def test_all_hit(self):
        """全中才记命中。"""
        assert _aggregate(["命中", "命中"]) == "命中"

    def test_reverse_beats_forward(self):
        """反向优先于同向暴露。"""
        assert _aggregate(["同向·显著", "反向·不可辨"]) == "反向·不可辨"

    def test_significant_beats_indistinguishable(self):
        """同为反向时, 显著优先。"""
        assert _aggregate(["反向·不可辨", "反向·显著"]) == "反向·显著"

    def test_untested_label_is_preserved(self):
        """**回归**: 未配对标签必须原样保留, 不得被改写成不可辨。"""
        assert _aggregate(["反向·未配对"]) == "反向·未配对"

    def test_no_direction_does_not_mask_hits(self):
        """**回归**: 有命中 + 某条无变化时记"部分命中", 不记"无方向"。"""
        assert _aggregate(["命中", "无方向"]) == "部分命中"

    def test_pure_null(self):
        """全无变化才记无方向。"""
        assert _aggregate(["无方向"]) == "无方向"
