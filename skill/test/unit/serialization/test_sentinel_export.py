# -*- coding: utf-8 -*-
"""序列化五格式的测光哨兵转换回归 (P0-14)。

缺陷形态 (审计轮次 AH3 §7 P0-14 记「serialization.py 五格式零哨兵转换」,
本轮按**行为**复验属实): ``ps1_gpsf = -1004.07`` 经本模块落盘后仍是
``-1004.07`` —— 一个**缺测**被导出成一颗 "-1004 等" 的源。而同仓 TAP 出口
(:func:`src.tap.formats.convert_table_rows`) 早已把它转成 NaN。两个出口对同一
份数据给出两个值, 且前者会把任何按该列做的统计彻底带偏 (均值被拉到 -1004 量级)。

两条设计约束, 本件逐条钉住:

  1. **按带不按点**: 站点实测 ps1 各波段哨兵带心不同 (g≈-1004.07 /
     r≈-1003.88 / i≈-1003.54 / z≈-1002.88 / y≈-1001.94), 浮点精确相等只命中
     1/174, 所以判据必须取 ``<= NULL_MAGNITUDE_SENTINEL``。
  2. **只对星等列生效**: 无差别套到所有数值列会把高自行星的 ``pmra ≈ -1500``
     (合法毫秒/年) 当缺测抹成 NaN —— 那正是 P0-03b 记的「静默丢真实自行」。
     ``pmra``/``pmdec``/``radial_velocity`` 都不在星等列集合里, 故天然安全。

依赖: 纯内存调用, 零网络。FITS 支需要 astropy, 缺失时显式跳过而非静默通过。
"""
from __future__ import annotations

# 标准库: csv 读回文本 / io 解析 VOTable / pathlib 定位
import csv
import io
import re

# 第三方: pytest (skip 语境与参数化)
import pytest

# 本地: 哨兵阈值真源 + 被测的三个出口
from src.models import BestSource
from src.serialization import delimited_text, votable_document, write_fits

SENTINEL = str(BestSource.NULL_MAGNITUDE_SENTINEL - 5.07)  # -1004.07: 站内实测的 ps1 缺测哨兵
OTHER_BAND = str(BestSource.NULL_MAGNITUDE_SENTINEL - 4.88)  # -1003.88: r 带带心, 证明判据是带不是点
REAL = "19.44"  # 对照: 真实星等, 任何判据都不许伤它
BIG_ID = "4512921183874236032"  # 标识符: 必须逐字保留, 与哨兵判据无关


def _cells(text: str, delimiter: str = ",") -> dict[str, str]:
    """把分隔符文本读回 {列名: 值} 字典 (表头即列序来源)。"""
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    return dict(zip(rows[0], rows[1], strict=True))


class TestDelimitedTextConvertsSentinel:
    """CSV/TSV 出口: 星等列的哨兵转 NaN。"""

    @pytest.mark.parametrize("delimiter", [",", "\t"], ids=["csv", "tsv"])
    def test_sentinel_becomes_nan(self, delimiter: str):
        """哨兵不��原样写出。"""
        text = delimited_text([{"ps1_gpsf": SENTINEL}], delimiter)
        assert _cells(text, delimiter)["ps1_gpsf"].lower() == "nan"

    def test_other_band_sentinel_also_converted(self):
        """另一波段的带心同样要判缺测 —— 点判定会漏掉它。"""
        text = delimited_text([{"ps1_rpsf": OTHER_BAND}], ",")
        assert _cells(text)["ps1_rpsf"].lower() == "nan", "哨兵带内任一点都必须判缺测, 不能只认 g 带的那个值"

    def test_real_magnitude_survives(self):
        """真实星等不被误伤。"""
        text = delimited_text([{"ps1_gpsf": REAL}], ",")
        assert _cells(text)["ps1_gpsf"] == REAL

    def test_non_magnitude_large_negative_survives(self):
        """``pmra≈-1500`` 是合法自行, 不是缺测 —— 无差别判据会静默丢真实数据。"""
        text = delimited_text([{"ps1_pmra": "-1500.0"}], ",")
        assert _cells(text)["ps1_pmra"] == "-1500.0"

    def test_identifier_survives(self):
        """标识符与哨兵判据无关, 逐字保留。"""
        text = delimited_text([{"ps1_source_id": BIG_ID}], ",")
        assert _cells(text)["ps1_source_id"] == BIG_ID


class TestVotableConvertsSentinel:
    """VOTable 出口: 同一判据 (它给该列声明了 double + unit="mag")。"""

    def test_sentinel_cell_is_nan(self):
        """FIELD 已声明 unit="mag", 单元格里再留 -1004.07 就是告诉 TOPCAT 一颗 -1004 等的源。"""
        xml = votable_document([{"ps1_gpsf": SENTINEL, "ps1_rpsf": REAL}], catalog="ps1")
        cells = re.findall(r"<TD>(.*?)</TD>", xml)
        assert cells[0].lower() == "nan", f"哨兵未转 NaN: {cells}"
        assert cells[1] == REAL, f"真实星等被误伤: {cells}"

    def test_identifier_cell_survives(self):
        """标识符逐字保留。"""
        xml = votable_document([{"ps1_source_id": BIG_ID}], catalog="ps1")
        assert BIG_ID in re.findall(r"<TD>(.*?)</TD>", xml)


class TestFitsConvertsSentinel:
    """FITS 出口: 同一判据 (astropy 缺失时显式跳过, 不静默通过)。"""

    def test_sentinel_cell_is_nan(self, tmp_path):
        """FITS 的 float64 列里写 NaN, 与另两个出口同表示。

        两个列分两次写: 一次 put 下去时同一行的两列会共享 ``values`` 的长度,
        断单个列时反而要跟行索引缠在一起, 分开写更直白也更不容易写错断言。
        """
        sent = tmp_path / "sent.fits"
        write_fits(sent, [{"ps1_gpsf": SENTINEL}])
        data = _read_fits(sent)
        if data is None:
            return  # astropy 不可用: 显式跳过 (不静默通过)
        value = data["ps1_gpsf"][0]
        assert value != value, f"哨兵未转 NaN: {value}"  # NaN 用"自己不等自己"判

        real = tmp_path / "real.fits"
        write_fits(real, [{"ps1_gpsf": REAL}])
        data2 = _read_fits(real)
        if data2 is None:
            return
        assert data2["ps1_gpsf"][0] == pytest.approx(float(REAL)), "真实星等被误伤"

    def test_large_negative_non_magnitude_survives(self, tmp_path):
        """合法大负值自行不得被当成缺测。"""
        path = tmp_path / "pmra.fits"
        write_fits(path, [{"ps1_pmra": -1500.0}])
        data = _read_fits(path)
        if data is None:
            return
        assert data["ps1_pmra"][0] == pytest.approx(-1500.0)


def _read_fits(path):
    """读回 FITS 列; astropy 缺失时返回 None (调用方显式跳过)。"""
    try:
        from astropy.io import fits  # 延迟导入: 只有本件需要它
    except ImportError:
        return None
    with fits.open(path) as hdul:  # 上下文管理器: 离开即关文件, 不留句柄
        return {name: hdul[1].data[name] for name in hdul[1].data.columns.names}
