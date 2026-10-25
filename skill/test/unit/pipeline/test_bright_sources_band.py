# -*- coding: utf-8 -*-
"""D4 承重测试: ``bright_sources`` 的波段口径 (显式 band / 兜底代表列)。

**为什么这组断言是承重的**: 旧实现的缺陷不是"算错了", 而是"**算得像对**" ——
它按键名排序取第一个星等列当代表值。gaia 的列按字母序 ``phot_b_mean_mag`` 恒定
排最前, 于是**恒定拿蓝带判所有源的亮度**; 蓝带缺测的行被当"没有测光"整行剔除,
实测 1000 行只剩 13 行。那 13 行不是"这批星最亮", 而是"这批星恰好在蓝带有测光",
而报表读起来完全像一次正常的亮度筛选。

所以这里钉的不是某个数值, 而是**口径本身**:
- 显式 ``band`` 时, 只有该波段的列算数, 且**不跨带兜底**;
- 兜底代表列按**数据完整度**选, 不按字典序, 且该选择**可被检视** (public 函数);
- 三种真实列名形态 (``gmag`` / ``ps1_gpsf`` / ``phot_g_mean_mag``) 都要认。

归属实验: 无 (生产代码的领域正确性, 不是评测面); 白盒锚点见
``src/core/source_postprocess.py::BestProcessor.bright_sources``。
"""
from __future__ import annotations

# 标准库: 无 (只用字面量构造行)
# 第三方: pytest
import pytest

# 本地: 被测后处理器
from src.core.source_postprocess import BestProcessor


def _gaia_batch(n: int = 1000) -> list[dict]:
    """造一批 gaia 形状的行: 蓝带**整列缺测**, 绿/红带有值。

    这正是实测里让旧实现只剩 13 行的形态 —— 蓝带列存在但没值。
    """
    return [
        {"source_id": f"G{i}",
         "phot_b_mean_mag": "",                       # 蓝带: 空串 (站点缺测的真实形态)
         "phot_g_mean_mag": str(10.0 + i * 0.01),     # 绿带: 10.00 ~ 19.99, 一半亮过 16
         "phot_r_mean_mag": str(11.0 + i * 0.01)}     # 红带: 11.00 ~ 20.99
        for i in range(n)
    ]


class TestRepresentativeColumnIsDataDriven:
    """兜底代表列必须按数据完整度选, 不能按字典序。"""

    def test_picks_the_complete_band_not_the_alphabetical_first(self):
        """蓝带整列缺测时, 代表列必须是绿带而非字母序排前的蓝带。"""
        batch = _gaia_batch()
        representative = BestProcessor.representative_magnitude_column(batch)
        assert representative == "phot_g_mean_mag", (
            f"兜底代表列取了 {representative!r}: 蓝带整列缺测却仍被选中, "
            "说明判据还是字典序第一个 —— 那正是旧缺陷")

    def test_brightness_filter_no_longer_drops_the_unmeasured_band(self):
        """实测量的回归: 1000 行在 mag_limit=16 下只剩 13 行 → 必须显著改善。"""
        kept = BestProcessor.bright_sources(_gaia_batch(), mag_limit=16.0)
        assert len(kept) >= 500, (
            f"只留下 {len(kept)}/1000 行: 代表列仍挑中了缺测的那一带, "
            "亮度筛选在事实上仍是空操作")

    def test_tie_is_broken_deterministically(self):
        """两带覆盖数相同时必须按列名定序 —— 否则同输入可能得不同代表列。"""
        batch = [{"g_mean_mag": "10.0", "r_mean_mag": "11.0"} for _ in range(5)]
        first = BestProcessor.representative_magnitude_column(batch)
        # 键序打乱后结果必须不变: 判据不能依赖输入 dict 的插入序
        shuffled = [{"r_mean_mag": "11.0", "g_mean_mag": "10.0"} for _ in range(5)]
        assert BestProcessor.representative_magnitude_column(shuffled) == first
        assert first == "g_mean_mag", f"并列时按列名取首, 实得 {first!r}"

    def test_no_magnitude_at_all_yields_none(self):
        """整批没有任何可用星等 → 没有代表列可言 (而不是挑一个列名凑数)。"""
        assert BestProcessor.representative_magnitude_column(
            [{"ps1_gpsf_err": "0.003"}, {"ps1_gpsf_err": ""}]) is None


class TestExplicitBandIsHonoured:
    """显式 band 时只认该波段, 且缺测**不跨带兜底**。"""

    @pytest.mark.parametrize("band,expected", [("g", 600), ("r", 500), ("b", 0)])
    def test_band_selects_the_photometry(self, band, expected):
        """三个波段各自的结果: b 全缺测故为 0, 绝不悄悄回落到别的带。"""
        kept = BestProcessor.bright_sources(_gaia_batch(), mag_limit=16.0, band=band)
        assert len(kept) == expected, (
            f"band={band!r} 留下 {len(kept)} 行, 期望 {expected}: "
            "跨带兜底会让缺测波段的行被别的带判成亮/暗")

    @pytest.mark.parametrize("row,band,expected", [
        ({"ps1_gpsf": "15.0"}, "g", 15.0),          # 两段列名 (表前缀 + 带名)
        ({"gmag": "16.5"}, "g", 16.5),              # 裸列名
        ({"phot_g_mean_mag": "12.0"}, "g", 12.0),   # 多段列名 (gaia 实形态)
        ({"splus_dr4_u_pstotal": "12.3"}, "u", 12.3),  # band 嵌在中段
    ])
    def test_real_column_shapes_are_recognised(self, row, band, expected):
        """三种真实列名形态都要认得出 band —— 认不出就等于显式 band 是空转。"""
        assert BestProcessor._band_magnitude(row, band) == expected

    def test_error_column_is_never_a_band_match(self):
        """误差列名以星等列名结尾, 显式 band 也不许把误差当星等取。"""
        assert BestProcessor._band_magnitude({"ps1_gpsf_err": "0.003"}, "g") is None

    def test_empty_band_is_not_treated_as_any_band(self):
        """空 band 判缺测 —— 若当"任意带"就退化成不传 band 的那个坑。"""
        assert BestProcessor._band_magnitude({"ps1_gpsf": "15.0"}, "") is None
