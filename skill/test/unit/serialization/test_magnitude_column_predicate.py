# -*- coding: utf-8 -*-
"""星等列判据的回归: 误差列不得被当成星等列 (后缀匹配的固有漏洞)。

守的缺陷: :func:`src.serialization.is_magnitude_column` 原本是纯
``endswith(MAGNITUDE_SUFFIXES)`` 判定, 而**误差列名往往以星等列名结尾** ——
``splus_dr4_e_u_pstotal`` 以 ``u_pstotal`` 结尾, ``ps1_gpsf_err`` 以 ``gpsf``
结尾。于是后缀匹配把误差列判成星等列。

两处真实后果:

  1. ``votable_document`` 给误差列挂上 ``unit="mag"``, TOPCAT 侧会把 0.003
     角秒的不确定度当星等换算;
  2. 按列取「代表星等」的调用点 (``BestProcessor._best_magnitude``) 可能把
     0.003 当成一颗 0.003 等的极亮源 —— 而亮度筛选正是拿它排序的。

本件的判据全部来自协议层权威表 (``CATALOG_MAG_COLUMNS`` /
``CATALOG_MAG_ERROR_COLUMNS``), 不另写清单, 故新增星表自动受保护。
"""
from __future__ import annotations

# 本地: 被测判据 + 消费者 (取代表星等的调用点)
from src.core.source_postprocess import BestProcessor
from src.serialization import is_magnitude_column


class TestErrorColumnIsNotMagnitude:
    """误差列必须被排除出星等判定 (尽管它的名字以星等列名结尾)。"""

    def test_e_prefixed_error_column_is_excluded(self):
        """``splus_dr4_e_u_pstotal`` 以 ``u_pstotal`` 结尾, 但它是误差列。"""
        assert is_magnitude_column("splus_dr4_e_u_pstotal") is False  # 反例成对: 同表真值列仍是 True

    def test_suffix_err_column_is_excluded(self):
        """``ps1_gpsf_err`` 以 ``gpsf`` 结尾, 同样是误差列。"""
        assert is_magnitude_column("ps1_gpsf_err") is False  # 反例成对: ps1_gpsf 仍是 True

    def test_value_columns_still_recognised(self):
        """反向对照: 真星等列必须仍被认出来 (防「一律判否」那种假修)。"""
        assert is_magnitude_column("ps1_gpsf") is True  # ps1 发布列, 名字里没有 "mag"
        assert is_magnitude_column("splus_dr4_u_pstotal") is True  # splus 发布列
        assert is_magnitude_column("gaia_dr3_18_phot_g_mean_mag") is True  # gaia 发布列


class TestRepresentativeMagnitudeIgnoresErrorColumns:
    """取代表星等的调用点不得挑中误差列。"""

    def test_error_only_row_reads_as_no_photometry(self):
        """整行只有误差列时必须判「无测光」, 而不是把 0.003 当成亮星。"""
        assert BestProcessor._best_magnitude({"ps1_gpsf_err": "0.003"}) is None  # 缺测即 None, 调用方据此剔除该行

    def test_error_column_does_not_win_over_value_column(self):
        """误差列与真值列同现时取真值 (排序后 gpsf 在前, 误差列本就不该被选中)。"""
        row = {"ps1_gpsf_err": "0.003", "ps1_gpsf": "15.0"}
        assert BestProcessor._best_magnitude(row) == 15.0  # 不是 0.003

    def test_error_column_does_not_survive_brightness_filter(self):
        """只剩误差列的行不得通过亮度筛选 (它没有任何测光可判)。"""
        assert BestProcessor.bright_sources([{"ps1_gpsf_err": "0.003"}], 16.0) == []


class TestRealCatalogColumnNamesAreRecognised:
    """真实站点列名必须被认出来 —— 判据认不得就等于亮度筛选对整表空转。

    这是另一侧的回归: 原判据只认 ``endswith("mag")``, 而站点实际发布的是
    ``ps1_gpsf`` / ``splus_dr4_u_pstotal`` 这类名字, 于是 ``bright_sources``
    对绝大多数星表是空操作 (一行真实的 ps1 源被判成「无测光」而整行剔除)。
    """

    def test_ps1_psf_columns_are_magnitude(self):
        """ps1 发 ``psf`` 系列, 名字里没有 "mag"。"""
        assert is_magnitude_column("ps1_gpsf") is True  # 与 test_suffix_err_column_is_excluded 成对
        assert is_magnitude_column("ps1_rpsf") is True  # r 波同理

    def test_splus_pstotal_columns_are_magnitude(self):
        """splus_dr4 发 ``*_pstotal`` 系列。"""
        assert is_magnitude_column("splus_dr4_u_pstotal") is True

    def test_brightness_filter_now_works_on_real_ps1_rows(self):
        """一行真实 ps1 源 (gpsf=15.0) 在 mag_limit=16 下必须被留下。"""
        rows = [{"ps1_gpsf": "15.0"}, {"ps1_gpsf": "18.0"}]
        kept = BestProcessor.bright_sources(rows, mag_limit=16.0)
        assert kept == [rows[0]], "亮度筛选对真实 ps1 列名应当生效"
