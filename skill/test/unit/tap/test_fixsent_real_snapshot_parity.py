# -*- coding: utf-8 -*-
"""两引擎空值语义一致性 —— 真实语料载荷断言 (AH1-3)。

AH1 §2.2 / §9 的实测: ``live_xpsp_ra10.68_dec41.27_r300.0as/rows_full.csv`` 第
**648** 行的 ``gaiaxp_photinfo_replenish_pmra`` 站点给的是 ``-999.0``, 而

- TAP 引擎 (``client_query:198`` -> ``convert_table_rows``) 读成 ``nan``;
- 模型引擎 (``BestSource.from_row`` -> ``to_dict``) 读成 ``'-999.0'``。

同一份数据两条出口给出**相反的空值语义**, 全表共 **108 格** (AH1 自纠后的数字:
第一版报 216, 其中站点本来就写 ``nan`` 的那部分不算矛盾)。

本件按 AH1 §7.3 的要求写成**端到端**断言: 喂真实快照、断言具体数字、断言两条
引擎在同一格上不再矛盾。只测归一器不够 —— 两处调用点里任何一处漏接, 单测照样全绿。
"""
from __future__ import annotations

import csv  # 标准库: 读真实快照
import sys  # 标准库: 路径锚定
from pathlib import Path  # 标准库: 快照定位

import pytest  # 断言库

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本件在 test/unit/tap/ 下三级
if str(SKILL_ROOT) not in sys.path:  # 已注入就不重复: 重复注入会让 src.* 出现两份类对象
    sys.path.insert(0, str(SKILL_ROOT))  # 插首位: 本件的导入要优先于环境里可能存在的同名包

from src.models import BestSource  # noqa: E402  模型引擎
from src.tap.formats import convert_table_rows  # noqa: E402  TAP 引擎

SNAPSHOT = (  # AH1 §2.2 点名的语料: 载荷断言必须打在真实快照上, 合成行造不出这条判据
    SKILL_ROOT / "evals" / "groundtruth" / "snapshots" / "live-2026-10-04"  # 与 baseline 时的语料同源
    / "live_xpsp_ra10.68_dec41.27_r300.0as" / "rows_full.csv"  # AH1 原文引用的那个目录与文件名
)
CATALOG = "xpsp"  # 该快照的星表: 自行列挂在共享表单表 gaiaxp_photinfo_replenish 上
PROPER_MOTION_COLUMNS = (  # 真实存在的两个自行列 (带共享表名前缀, 不是 xpsp_ 前缀)
    "gaiaxp_photinfo_replenish_pmra",
    "gaiaxp_photinfo_replenish_pmdec",
)
EXPECTED_CELLS = 108  # AH1 自纠后的矛盾格数: 修复前这 108 格在两个引擎上语义相反


def _rows() -> list[dict]:
    """读真实快照; 快照缺失即报错而不是 skip (禁 fail-open)。"""
    assert SNAPSHOT.exists(), f"真实快照缺失, 判据无法落地: {SNAPSHOT}"
    with SNAPSHOT.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _is_null(value) -> bool:
    """一个格子在某个引擎里是否表示"无值"。"""
    if value is None:  # 引擎没给这一列: TAP 侧缺列即缺格
        return True
    if isinstance(value, float) and value != value:  # NaN: 自己不等自己
        return True
    text = str(value).strip().lower()  # 站点侧的字符串形态统一小写去空白再判
    return text in ("", "nan", "null")  # 空串与字面 nan/null 都算"无值"


class TestTwoEnginesAgreeOnNullSemantics:
    """TAP 与模型两条引擎对同一格必须给出同一个空值结论。"""

    def test_snapshot_shape_is_still_the_audited_one(self):
        """先把语料本身钉住: 素材换了, 下面的 108 就失去意义。"""
        rows = _rows()  # 每次现读: 快照可能被重抓, 缓存会让载荷断言钉在旧语料上
        assert len(rows) == 1000, f"xpsp 快照应是 1000 行, 实得 {len(rows)}"
        for column in PROPER_MOTION_COLUMNS:  # 逐个自行列核对存在性
            assert column in rows[0], f"快照缺自行列 {column}: {sorted(rows[0])[:8]}..."

    def test_row_648_proper_motion_survives_on_both_engines(self):
        """AH1 点名的第 648 行: 两引擎都必须保住 ``-999.0``, 不许一个给 nan。"""
        rows = _rows()  # 现读快照: 判据要打在真实语料上
        row = rows[648]  # AH1 §2.2 原文给的行号, 换行即换了一个缺陷
        for column in PROPER_MOTION_COLUMNS:  # 两个自行列逐个判
            raw = (row.get(column) or "").strip()  # 站点原值: 判据锚在它上面
            assert raw == "-999.0", f"第 648 行 {column} 站点原值应是 -999.0, 实得 {raw!r}"
            tap = convert_table_rows([{column: raw}])[0][column]  # TAP 引擎
            model = BestSource.from_row(row, CATALOG).raw_data.get(column)  # 模型引擎
            assert not _is_null(tap), f"TAP 引擎把合法的 {column}=-999.0 抹成了 {tap!r}"
            assert not _is_null(model), f"模型引擎把合法的 {column}=-999.0 抹成了 {model!r}"

    def test_no_contradicting_cells_left_in_the_whole_snapshot(self):
        """全表扫描: 两引擎空值语义不一致的格数必须为 0 (修前 108)。"""
        rows = _rows()  # 现读快照: 全表判据同样要打在真实语料上
        converted = convert_table_rows(rows)  # TAP 侧一次转完
        contradictions = 0  # 矛盾格计数
        audited = 0  # 参与判定的格数 (站点真给了 <= -999 的实数)
        for index, row in enumerate(rows):  # 逐行对照两引擎
            model = BestSource.from_row(row, CATALOG)  # 模型侧逐行归一
            for column in PROPER_MOTION_COLUMNS:  # 两个自行列逐个判
                raw = (row.get(column) or "").strip()  # 站点原值
                if not raw or raw.lower() in ("nan", "null"):
                    # 站点本来就写 nan: 两引擎都对它判缺测, 不构成矛盾 (AH1 的自纠点)
                    continue
                try:
                    number = float(raw)
                except ValueError:
                    continue
                if number != number or number > BestSource.NULL_MAGNITUDE_SENTINEL:
                    continue  # 非数值 / 不在哨兵带内: 不参与本判据
                audited += 1
                tap_null = _is_null(converted[index].get(column))
                model_null = _is_null(model.raw_data.get(column))
                if tap_null != model_null:
                    contradictions += 1
        # 载荷断言打在真实语料上: 参与判定的格数必须恰是审计记录的 108
        assert audited == EXPECTED_CELLS, (
            f"参与判定的自行格数应为 {EXPECTED_CELLS} (AH1 实测), 实得 {audited} —— 语料换了"
        )
        assert contradictions == 0, (
            f"仍有 {contradictions} 格两引擎空值语义相反 (修前 {EXPECTED_CELLS} 格全矛盾)"
        )
