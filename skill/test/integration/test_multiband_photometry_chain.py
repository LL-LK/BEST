"""光变容器链集成测试: BestMultiBandPhotometry 的构造契约与 summary 统计契约。

空容器必须 0 个点且 source_id 正确落位; summary() 对空容器给出 n_points=0
与 source_id — 下游按这两个键读摘要, 缺键会让统计面静默失真。全部离线:
不发起任何 HTTP 请求。

本文件由原 test_integration.py 按链路拆出 (TestBestMultiBandPhotometry)。拆分
只是搬家, 测试名与断言一条未改。
"""
from __future__ import annotations

# 本地: 光变容器 — 本文件被测对象 (权威实现在 src.multiband_photometry)
from src.multiband_photometry import BestMultiBandPhotometry


class TestBestMultiBandPhotometry:
    """光变容器回归 (空容器构造契约与 summary 统计契约)。"""

    def test_empty_light_curve(self):
        """空光变容器: 0 个点且 source_id 正确落位 (构造契约)。"""
        lc = BestMultiBandPhotometry(source_id="BEST001")
        assert lc.n_points == 0
        assert lc.source_id == "BEST001"

    def test_light_curve_summary_empty(self):
        """空光变的 summary() 必须给出 n_points=0 与 source_id (统计契约)。"""
        lc = BestMultiBandPhotometry(source_id="BEST001")
        summary = lc.summary()                                                                      # 取汇总结论: 判"整条链是否收敛"看它
        assert summary["n_points"] == 0
        assert summary["source_id"] == "BEST001"
