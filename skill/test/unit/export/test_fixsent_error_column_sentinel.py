# -*- coding: utf-8 -*-
"""泛用导出不再泄漏误差列哨兵 —— 真实语料载荷断言 (AF4-P0-1)。

A7 在 HEAD `631e72c` 上的实测: ps1 落盘仍泄 **15,644** 格 ``-999.0``, 其中 ``*_err``
误差列占 **15,036** (本仓 4003 行那份快照实测 15,644 全部落在误差列)。根因是
``src/serialization.py`` 的哨兵判据只认 :func:`is_magnitude_column` —— 而误差列被
该函数**显式排除** (``gpsf_err`` 以 ``gpsf`` 结尾, 若不排除就会把 ``unit="mag"``
挂到 0.003 角秒的不确定度上), 于是误差列成了"没有任何判据认领"的那一半。

本件按审计的承重测试标准写:
  1. 喂**真实快照** (不是手写 dict);
  2. 断言**具体数字** (15644 -> 0), 不是断言"非空";
  3. 留**反例** —— 真值列与合法负值不得被顺带抹掉, 否则"把阈值放宽到 -1e9"也能过。
"""
from __future__ import annotations

import csv  # 标准库: 读真实快照与回读落盘正文
import io  # 标准库: 从字符串解析 CSV
import sys  # 标准库: 路径锚定
from pathlib import Path  # 标准库: 快照定位

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本件在 test/unit/export/ 下三级
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from src.models import BestSource  # noqa: E402  哨兵阈值真源
from src.serialization import delimited_text  # noqa: E402  被测出口

SNAPSHOT = (
    SKILL_ROOT / "evals" / "groundtruth" / "snapshots" / "live-2026-10-04"
    / "live_ps1_ra180.0_dec30.0_r300.0as_max4000" / "rows_full.csv"
)
EXPECTED_ROWS = 4003  # 该快照的行数 (含 3 个分页重复表头行, AF4-P1-1 另一条, 此处不裁)
LEAK_BEFORE_FIX = 15644  # 修前落盘后仍为 -999.0 的格数 (实跑值, 非转述)


def _rows() -> list[dict]:
    """读真实 ps1 快照; 快照缺失即报错而不是 skip (禁 fail-open)。"""
    assert SNAPSHOT.exists(), f"真实快照缺失, 判据无法落地: {SNAPSHOT}"
    with SNAPSHOT.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _cells_by_column(text: str) -> dict[str, list[str]]:
    """把落盘正文读回 {列名: [逐行取值]}。"""
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    table: dict[str, list[str]] = {name: [] for name in header}
    for row in reader:
        for name, cell in zip(header, row):
            table[name].append(cell.strip())
    return table


class TestErrorColumnsNoLongerLeakSentinel:
    """误差列的 -999.0 必须转 NaN, 与星等列同一判据。"""

    def test_snapshot_is_the_audited_one(self):
        """先把语料钉住: 素材换了, 15644 这个数就失去意义。"""
        rows = _rows()
        assert len(rows) == EXPECTED_ROWS, f"ps1 快照应是 {EXPECTED_ROWS} 行, 实得 {len(rows)}"
        assert "ps1_gpsf_err" in rows[0], "快照缺误差列 ps1_gpsf_err"

    def test_no_minus_999_survives_in_landed_text(self):
        """落盘正文里不得再出现 -999.0 (修前 15644 格, 全部来自 *_err 列)。"""
        text = delimited_text(_rows(), ",")
        leaked = sum(1 for line in text.splitlines()[1:] for cell in line.split(",")
                     if cell.strip() == "-999.0")
        assert leaked == 0, f"落盘仍泄 {leaked} 格 -999.0 (修前 {LEAK_BEFORE_FIX})"

    def test_error_columns_are_converted_while_values_are_not(self):
        """逐列断言: 误差列全转 NaN, 而真值列一个都不许被转。"""
        table = _cells_by_column(delimited_text(_rows(), ","))
        error_columns = [name for name in table if name.endswith("_err")]
        assert error_columns, "快照里应有误差列, 否则本判据空转"
        for name in error_columns:
            assert "-999.0" not in table[name], f"误差列 {name} 仍泄漏 -999.0"
        # 反例: 真值列必须原样存活 —— 挡"把阈值放宽到把所有负值都判缺测"的假修复
        for name in ("ps1_ra", "ps1_dec"):
            if name not in table:
                continue
            assert all(cell.lower() != "nan" for cell in table[name]), f"{name} 被误转成 NaN"

    def test_error_column_sentinel_cells_are_nan_not_dropped(self):
        """误差列的哨兵格要落成 NaN 而不是变成空串: 两者在下游统计里含义不同。"""
        table = _cells_by_column(delimited_text(_rows(), ","))
        nan_cells = sum(1 for name in table if name.endswith("_err")
                        for cell in table[name] if cell.lower() == "nan")
        assert nan_cells > 0, "误差列一个 NaN 都没有: 判据要么没生效, 要么把哨兵转成了空值"

    def test_real_magnitudes_and_coordinates_survive(self):
        """真值不受影响 (合成用例之外的真实语料反例)。"""
        rows = _rows()
        text = delimited_text(rows, ",")
        table = _cells_by_column(text)
        # ps1_ra 全列非空且都不是 NaN: 坐标列不是测光列, 判据不该碰它
        if "ps1_ra" in table:
            assert all(cell != "" and cell.lower() != "nan" for cell in table["ps1_ra"])
        # 星等列的真实取值必须逐字保住: 抽查前 50 行里 > 阈值的那些格
        if "ps1_gpsf" in table:
            kept = [c for c in table["ps1_gpsf"][:50]
                    if c.lower() != "nan" and c != "" and float(c) > BestSource.NULL_MAGNITUDE_SENTINEL]
            assert kept, "ps1_gpsf 的真实取值被整列抹掉了 —— 判据改宽了"
