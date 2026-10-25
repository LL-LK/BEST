# -*- coding: utf-8 -*-
"""三出口哨兵一致性回归 (X7-P0-1 / AK4-004 / W5b-P1-1 / AH1-5 / AH3-04)。

缺陷形态 (主代理在 HEAD 631e72c 亲跑, 见 temp/vfy/ROOT-INDEPENDENT-VERIFICATION.md §2
`AK4-004`): 同一行数据走三个出口给出**不同**的哨兵转换结果 ——

=========================================  ====================  ====================
列 / 取值                                   泛用导出 (delimited)   TAP 出口 (修前)
=========================================  ====================  ====================
``ps1_gpsf_err = -999.0`` (误差列哨兵)      ``-999.0`` 原样落盘     ``nan``
``pmra = -1500.0`` (合法大负自行)           ``-1500.0`` 保住        ``nan`` 抹掉
=========================================  ====================  ====================

同一份事实出现两个版本, 而这两条分别来自**相反方向**的判据缺口:
泛用导出侧只判星等列(漏掉误差列), TAP 侧对所有列无差别套用且**不查豁免名单**
(``src/tap/formats.py:131`` 的 ``if number <= floor`` 对所有列生效)。

本件钉住的是**行为**而不是"某个守卫存在": 三个出口必须对**同一格**给出**同一个**
字符串表示。任何一侧把判据改宽或改窄, 三元组立刻不等。

判据矩阵里特意留了四条**反例** (AH1 §7.2: 没有反例时 `>=99.0` 与全局 `==99` 都能过):
  - ``ps1_rpsf = -30.5``  合法负星等必须存活 (挡"所有负值都算哨兵")
  - ``gaia_dr3_18_phot_g_n_obs = 99.0``  真实观测次数必须存活 (挡"全局 99 即缺测")
  - ``ps1_pmra`` / ``gaiaxp_photinfo_replenish_pmra``  带站前缀的豁免名必须命中
    (挡"裸名比对" —— 那正是 AH1-5 / AH3-04 记的「按列名硬编码」形态)
"""
from __future__ import annotations

import csv  # 标准库: 读回 delimited_text 的正文
import io  # 标准库: 从字符串解析 CSV
import re  # 标准库: 抠 VOTable 的 <TD> 单元格
import sys  # 标准库: 路径锚定
from pathlib import Path  # 标准库: 仓根定位

import pytest  # 参数化: 判据矩阵逐行驱动

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本件在 test/unit/tap/ 下三级
if str(SKILL_ROOT) not in sys.path:  # 单文件跑门禁时也要能 import 仓内模块
    sys.path.insert(0, str(SKILL_ROOT))

from src.serialization import (  # noqa: E402  泛用导出两出口 + 站/列豁免判定
    delimited_text,
    sentinel_exempt_column,
    votable_document,
)
from src.tap.formats import convert_table_rows, serialize_result  # noqa: E402  TAP 出口

# (列名, 取值, 说明) —— 期望值不写死成 True/False, 而是由"三出口互相一致"来表达。
# 这样任何一侧单独漂移都会被抓, 而不是只守住一侧。
MATRIX = [
    ("ps1_gpsf", "-1004.07", "下侧哨兵·星等列 (ps1 g 带带心)"),
    ("ps1_rpsf", "-1003.88", "下侧哨兵·另一波段 (证明判据是带不是点)"),
    ("ps1_gpsf_err", "-999.0", "下侧哨兵·误差列 (AF4-P0-1 的 15,644 格)"),
    ("ps1_parallax", "-999.0", "下侧哨兵·视差 (AH3-04 收窄后不再整类豁免)"),
    ("ps1_rpsf", "-30.5", "反例: 合法负星等必须存活"),
    ("ps1_rpsf", "19.44", "反例: 真实星等必须存活"),
    ("pmra", "-1500.0", "豁免·裸名 (高自行星)"),
    ("ps1_pmra", "-1500.0", "豁免·站前缀 ps1_"),
    ("gaia_dr3_18_pmra", "-999.0", "豁免·站前缀 gaia_dr3_18_"),
    ("gaiaxp_photinfo_replenish_pmra", "-999.0", "豁免·共享表单表前缀 (xpsp)"),
    ("stripe82_pmdec", "-1200.0", "豁免·站前缀 stripe82_"),
    ("landolt_radial_velocity", "-3000.0", "豁免·站前缀 landolt_"),
    ("ps1_rpsf", "99.0", "上侧哨兵·星等列"),
    ("splus_dr4_e_u_pstotal", "99.0", "上侧哨兵·误差列 (与星等列 99.0 逐列同数)"),
    ("gaia_dr3_18_phot_g_n_obs", "99.0", "反例: 观测次数 99 是真实值, 不得判缺测"),
]


def _csv_cell(text: str, column: str) -> str:
    """从 delimited_text 正文里读回指定列的单元格。"""
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    return dict(zip(header, next(reader), strict=True))[column]


def _votable_cell(column: str, value: str) -> str:
    """走 VOTable 出口取该格的字符串表示。"""
    xml = votable_document([{column: value}], catalog="ps1")
    return re.findall(r"<TD>(.*?)</TD>", xml)[0]


class TestThreeExportsAgreeOnOneFact:
    """同一格在三个出口必须给出同一个版本 (X7-P0-1 的正面判据)。"""

    @pytest.mark.parametrize("column,value,note", MATRIX, ids=[f"{c}={v}" for c, v, _ in MATRIX])
    def test_cell_is_identical_across_exports(self, column: str, value: str, note: str):
        """delimited_text / votable / convert_table_rows 三处必须逐字相同。

        判据取"三处互相一致"而非"等于某个写死的期望": 后者只能守住被写死的那一侧,
        正是两侧各写一份判据却能长期共存的原因。
        """
        tap = str(convert_table_rows([{column: value}])[0][column])  # TAP 出口
        generic = _csv_cell(delimited_text([{column: value}], ","), column)  # 泛用导出 CSV
        votable = _votable_cell(column, value)  # 泛用导出 VOTable
        assert tap == generic == votable, (
            f"{note}: 同一格 {column}={value} 三个出口给出三个版本 "
            f"(TAP={tap!r}, delimited={generic!r}, votable={votable!r})"
        )


class TestLowerSentinelStillConverts:
    """收口不得变成"什么都不转" —— 真哨兵仍必须变 NaN (防 fail-open 式修复)。"""

    @pytest.mark.parametrize(
        "column,value",
        [
            ("ps1_gpsf", "-1004.07"),  # 星等列
            ("ps1_gpsf_err", "-999.0"),  # 误差列 (AF4-P0-1)
            ("ps1_parallax", "-999.0"),  # 视差 (AH3-04)
        ],
    )
    def test_sentinel_becomes_nan_in_every_export(self, column: str, value: str):
        """哨兵在三个出口都变 NaN; 只看一个出口会漏掉另外两个。"""
        assert _csv_cell(delimited_text([{column: value}], ","), column).lower() == "nan"
        assert _votable_cell(column, value).lower() == "nan"
        tap = convert_table_rows([{column: value}])[0][column]
        assert tap != tap, f"{column}={value} 在 TAP 出口未转 NaN: {tap!r}"


class TestTapCsvExportMatchesGenericExport:
    """X7-P0-1 的原始形态: 生产实际走的两条 CSV 落盘路必须同值。

    ``FORMAT=csv`` 是 TAP 的零依赖出口、也是生产落盘实际走的那一条; 泛用导出的
    ``delimited_text`` 是下载路径的落盘层。两者对同一格给出不同哨兵结果, 正是
    W5b / X7 各自命中的那条。
    """

    @pytest.mark.parametrize("column,value,note", MATRIX, ids=[f"{c}={v}" for c, v, _ in MATRIX])
    def test_tap_csv_cell_equals_generic_csv_cell(self, column: str, value: str, note: str):
        """两条 CSV 出口的单元格必须逐字相同。"""
        body = serialize_result([{column: value}], "csv").body.decode("utf-8")  # TAP CSV 出口
        tap_cell = _csv_cell(body, column)
        generic_cell = _csv_cell(delimited_text([{column: value}], ","), column)  # 泛用导出
        assert tap_cell == generic_cell, (
            f"{note}: {column}={value} 两条 CSV 出口不同值 (TAP={tap_cell!r}, 泛用={generic_cell!r})"
        )


class TestLowerBandKeepsItsExemptions:
    """W5b-P1-1 的原始反例: 审计那一行 7 列里 3 列必须保住。"""

    def test_audit_row_has_three_survivors(self):
        """``pmra``/``pmdec``/``radial_velocity`` 保住, 其余 4 列仍判缺测。

        修前这 7 列**全部**变 nan (G3 实测), 即高自行星的自行被静默抹掉;
        修后不得反向退化成"全都保住" —— 那会让真哨兵漏网。
        """
        row = {
            "pmra": -1500.0, "pmdec": -1200.0, "radial_velocity": -1500.0,
            "parallax": -1500.0, "ra_err": -1500.0, "dec_err": -1500.0, "ps1_gpsf": -1500.0,
        }
        out = convert_table_rows([row])[0]
        survivors = {k for k, v in out.items() if not (isinstance(v, float) and v != v)}
        assert survivors == {"pmra", "pmdec", "radial_velocity"}, (
            f"豁免列集合应为三个自行/RV 列, 实得 {sorted(survivors)}"
        )
        # 且保住的是**原值**不是"没转": 值必须等于输入
        for key in survivors:
            assert out[key] == row[key], f"{key} 保住的应是原值 {row[key]}, 实得 {out[key]!r}"


class TestSentinelExemptionIsPerStation:
    """豁免按 (站, 列) 语义判定, 不是按裸列名硬编码 (AH1-5 / AH3-04)。"""

    @pytest.mark.parametrize(
        "column",
        [
            "pmra",  # 裸名 (uss_dr1 的响应就是裸名)
            "ps1_pmra",  # 站前缀
            "gaia_dr3_18_pmra",  # 站前缀
            "gaiaxp_photinfo_replenish_pmra",  # 共享表单表前缀 (xpsp 的自行列在这里)
            "stripe82_pmdec",
            "landolt_radial_velocity",
            "jpas_u_pmra",  # 长前缀优先才剥得对
        ],
    )
    def test_prefixed_exempt_names_are_recognised(self, column: str):
        """7 个真实需要豁免的列名必须全部命中 —— 任一单侧前缀规则都会漏。"""
        assert sentinel_exempt_column(column) is True, f"{column} 应判豁免: 剥站前缀后是豁免裸名"

    @pytest.mark.parametrize(
        "column",
        ["ps1_rpsf", "xpsp_ra", "ps1_parallax", "ps1_gpsf_err", "gaia_dr3_18_phot_g_mean_mag"],
    )
    def test_non_exempt_names_stay_convertible(self, column: str):
        """反例: 名字里带站前缀但语义不是自行/RV 的列不得被豁免。"""
        assert sentinel_exempt_column(column) is False, f"{column} 不应豁免: 哨兵必须还能判掉它"

    def test_upper_sentinel_never_touches_counting_columns(self):
        """``phot_g_n_obs = 99.0`` 是真实观测次数 —— 全局 99 判据会把它抹掉。"""
        assert convert_table_rows(
            [{"gaia_dr3_18_phot_g_n_obs": "99.0"}]
        )[0]["gaia_dr3_18_phot_g_n_obs"] == 99.0
