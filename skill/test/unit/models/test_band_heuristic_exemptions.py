# -*- coding: utf-8 -*-
"""N7 承重测试: 星等启发式回退不得把**带符号的真实物理量**当成波段星等。

**缺陷本体 (2026-10-07 实测)**: :meth:`BestSource.from_row` 在星表没有显式测光映射表时
(未知星表, 或 ``catalog=""``) 回退到"按键名首字母归波段"。``known_bands`` 含 ``r``,
而 ``radial_velocity`` 以 ``r`` 开头, 于是它被判成 **r 波段星等**:

    BestSource.from_row({"radial_velocity": "-1500.0"}, catalog="").magnitudes
    # 修前: {"r": -1500.0}      ← 自行速度成了星等
    # 修后: {}

后果不是"多了一个键", 而是**物理量纲被换掉了**: 下游按 r 波段筛亮度会拿到一个
``-1500`` mag 的源 —— 比任何真实恒星暗一千多倍, 是纯噪声。而
``_SENTINEL_EXEMPT_COLUMNS`` 这份名单存在的理由恰恰是"别碰这几列", 启发式支却
把它们当成了测光, 与该名单的意图正好相反。

归属: 生产代码的领域正确性; 白盒锚点见
``src/models/__init__.py::_is_exempt_bare``。
"""
from __future__ import annotations

# 本地: 被测行模型
from src.models import BestSource

# 豁免窄名单里的三列 (与 src.models._SENTINEL_EXEMPT_COLUMNS 同源, 这里只作断言的入参表)
EXEMPT_BARE = ("pmra", "pmdec", "radial_velocity")


class TestHeuristicBandFallbackRespectsExemptions:
    """无显式测光表时, 豁免列一律不进 ``magnitudes`` / ``magnitude_errors``。"""

    def test_radial_velocity_is_not_a_magnitude(self):
        """核心回归: ``radial_velocity`` 绝不能落进 ``magnitudes['r']``。"""
        obj = BestSource.from_row({"radial_velocity": "-1500.0"}, catalog="")
        assert "r" not in obj.magnitudes, (
            f"radial_velocity 被当成了 r 波段星等: magnitudes={obj.magnitudes} —— "
            "-1500 km/s 是自行速度, 不是星等")
        assert not obj.magnitude_errors, "误差支同样不得收下它"  # 两条支都要断: 误差支的键空间同样被污染过

    def test_error_variant_also_excluded(self):
        """``radial_velocity_err`` 走的是误差支 (首字母同为 r), 也必须被排除。"""
        obj = BestSource.from_row({"radial_velocity_err": "-1500.0"}, catalog="")
        assert not obj.magnitude_errors, (
            f"radial_velocity_err 进了 magnitude_errors: {obj.magnitude_errors}")

    def test_exempt_bare_columns_never_become_bands(self):
        """名单里每一列都断一遍 —— 防止将来加列时只修一列。"""
        for column in EXEMPT_BARE:
            obj = BestSource.from_row({column: "-1500.0"}, catalog="")
            assert not obj.magnitudes, f"{column} 不该进 magnitudes: {obj.magnitudes}"
            assert not obj.magnitude_errors, f"{column} 不该进 magnitude_errors"  # 逐列点名: 一次只报是哪列


class TestRealPhotometryStillResolves:
    """反向自证: 豁免守卫不许把真正的测光列一并挡掉。

    这一组的作用是**双向**: 上面几组证明"不该收的没收", 这一组证明"该收的照收"。
    只有前者的话, 一个什么都不收的实现也能全绿 —— 而那会把启发式支整个废掉。
    """

    def test_bare_band_column_still_maps(self):
        """裸名 ``gmag`` 在无显式表时仍按启发式归 g 波段 (守卫不许一刀切)。"""
        obj = BestSource.from_row({"gmag": "15.0"}, catalog="")
        assert obj.magnitudes == {"g": 15.0}  # 走权威表, 不经启发式 —— 守卫更不该影响它, "真实测光列必须照常解析"  # 键即波段字母: 启发式的原始语义

    def test_bare_band_error_still_maps(self):
        """裸名 ``gmag_err`` 在无显式表时仍按启发式归 g 波段误差。"""
        obj = BestSource.from_row({"gmag_err": "0.01"}, catalog="")
        assert obj.magnitude_errors == {"g": 0.01}  # 键即波段字母: 与星等支同构, "真实误差列必须照常解析"

    def test_explicit_catalog_map_still_wins(self):
        """有显式表时走权威表, 根本不该进启发式支 (守卫更不该影响它)。"""
        obj = BestSource.from_row({"ps1_gpsf": "15.0"}, catalog="ps1")
        assert obj.magnitudes == {"g": 15.0}  # 走权威表, 不经启发式 —— 守卫更不该影响它

    def test_prefixed_exempt_column_never_matched(self):
        """带站前缀的豁免列也不该被启发式收下 (前缀没剥中时首字母仍是 r)。"""
        obj = BestSource.from_row({"landolt_radial_velocity": "-1500.0"}, catalog="")
        assert not obj.magnitudes, f"带前缀的豁免列仍被收下: {obj.magnitudes}"
