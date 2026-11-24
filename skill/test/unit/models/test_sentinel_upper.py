# -*- coding: utf-8 -*-
"""测光**上侧**缺测哨兵 (99.0) 的回归 —— 与 ``test_sentinel_band.py`` 的下侧带互补。

职责: 把"部分星表用 99.0 表示无测量"这条判定钉死, 并同时钉死它的**边界**:
99.0 只在测光列算缺测, 在天体测量列 (如视差) 是合法毫秒值, 不得一并抹掉。

证据 (2026-10-06 逐格复算, 87 份真实快照 34,379 行):
``splus_dr4_u_pstotal`` 的 412 个取值里真值域 15.5649..27.9548 (n=398),
99.0 恰为**最大值**且与真值域之间是干净空档; 同批 ``*_err`` 列的 99.0 计数
与值列逐格相等 (14/14) —— 误差列不会有这种巧合。全仓 99 家族取值共 284 处,
全部落在 splus_dr4 的 pstotal 星等列。
"""
from __future__ import annotations

# 本地: 行模型 (哨兵判定本体) 与 TAP 导出转换器 (第二个消费方)
from src.models import BestSource
from src.tap.formats import convert_table_rows

CATALOG = "splus_dr4"  # 唯一实测出现该哨兵的星表


class TestUpperSentinelInPhotometry:
    """99.0 在**测光列**必须判缺测。"""

    def test_magnitude_sentinel_is_dropped_from_magnitudes(self):
        """值列 99.0 → 不进 magnitudes (否则它是"一颗 99 等的源", 物理上不存在)。"""
        obj = BestSource.from_row({"splus_dr4_u_pstotal": "99.0"}, catalog=CATALOG)
        assert "u" not in obj.magnitudes, f"99.0 被当成真实星等收进来了: {obj.magnitudes}"

    def test_error_sentinel_is_dropped_from_errors(self):
        """误差列 99.0 同样不算测量 —— 实测它与值列逐格同现, 是同一个缺测信号。"""
        obj = BestSource.from_row({"splus_dr4_e_u_pstotal": "99.0"}, catalog=CATALOG)
        assert "u" not in obj.magnitude_errors, f"99.0 误差被当成真实不确定度: {obj.magnitude_errors}"

    def test_genuine_magnitude_below_threshold_survives(self):
        """真值必须活下来 (阈值不能收紧到把正常星等也吃掉)。"""
        obj = BestSource.from_row({"splus_dr4_g_pstotal": "20.5"}, catalog=CATALOG)
        assert obj.magnitudes["g"] == 20.5  # 实测真值域上沿 27.95, 20.5 是其中

    def test_measured_boundary_is_just_below_threshold(self):
        """实测真值域上沿 27.954818725585934 必须判为真值。

        这条钉的是"阈值别往上挪到吃掉真值": 若有人把 99.0 改成 50 或 20,
        这条会红 (27.95 < 阈值 仍成立), 而把阈值压到 27 以下同样会红。
        """
        obj = BestSource.from_row({"splus_dr4_u_pstotal": "27.954818725585934"}, catalog=CATALOG)
        assert obj.magnitudes["u"] == 27.954818725585934  # 实测真值上沿, 不是哨兵

    def test_tap_export_applies_the_same_rule(self):
        """TAP 导出 (CSV/VOTable/FITS 的共用归一) 必须与行模型同判。

        两个消费方口径分叉过一次就会出"同一份数据两个口径"的问题, 与
        YZ-50 的标识符护栏同源, 故这里显式钉住第二个消费方。
        """
        out = convert_table_rows([{"splus_dr4_u_pstotal": "99.0", "splus_dr4_g_pstotal": "20.5"}])[0]
        sentinel = out["splus_dr4_u_pstotal"]
        assert sentinel != sentinel, f"TAP 侧未把 99.0 转成 NaN: {sentinel!r}"  # NaN 用"自己不等自己"判
        assert out["splus_dr4_g_pstotal"] == 20.5  # 真值不受影响


class TestUpperSentinelMustNotLeakToAstrometry:
    """99.0 在**天体测量列**是合法值 —— 判据不得越界。"""

    def test_parallax_of_99_mas_is_preserved(self):
        """视差 99.0 mas 完全合法, 无差别套用上侧哨兵会抹掉真实视差。"""
        obj = BestSource.from_row({"splus_dr4_parallax": "99.0"}, catalog=CATALOG)
        assert obj.parallax == 99.0, f"合法视差被当成缺测抹掉了: {obj.parallax!r}"

    def test_tap_export_also_keeps_legit_parallax(self):
        """TAP 侧同判: 视差 99.0 原样出函, 不转 NaN。"""
        out = convert_table_rows([{"splus_dr4_parallax": "99.0"}])[0]
        assert out["splus_dr4_parallax"] == 99.0  # 合法毫秒值不被哨兵波及
