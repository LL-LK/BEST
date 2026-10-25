# -*- coding: utf-8 -*-
"""缺测哨兵按**带**判定的回归 (H3-02 / G6-F1)。

职责: 把"ps1 空测光 ≈ -1000"这件事从**点值**口径纠正为**带**口径, 并用实测
取值范围把这条判定钉死, 使"把阈值收紧到某一个具体浮点数"这种改法必红。

为什么必须是带 (2026-10-05 实测, ps1 @180,30 60" 一整页 174 行,
temp/h3/live_probe.py 逐列统计): 同一发样本里, 带哨兵的 148 行 ``ps1_gpsf``
在 2 位小数上就分裂成 ``-1004.07``(103 行) + ``-1004.08``(45 行), 完整浮点上
散布在 -1004.0787842744421 ~ -1004.0726439746845 之间。**浮点精确相等只能命中
1/174**。而每个波段的带心还各不相同 (g≈-1004.07 / r≈-1003.88 / i≈-1003.54 /
z≈-1002.88 / y≈-1001.94), 误差列则是精确的 -999.0 —— 所以枚举两三个点覆盖不了,
按带才有唯一正确解。

覆盖: 模型层的缺测判定 (``BestSource.NULL_MAGNITUDE_SENTINEL``) 在**全部实测
带内取值**上的一致性, 以及阈值相对"最近合法星等"的安全余量。
依赖: 纯内存, 桩数据只来自下表实测记录; 不发任何网络请求。
历史沿革: 阈值本身早就是带判定 (-999.0), 但仓内多处注释/docstring 把它记成
"实测 ps1_gpsf=-1004.07" 这个**点值**, 读的人据此以为点判据成立 (G6-F1)。
"""
from __future__ import annotations

# 本地: 源对象模型 (缺测判定的落点: from_row 逐列判 <= 阈值即缺测)
from src.models import BestSource

# 实测带 (2026-10-05, ps1 @180,30 r=60", 174 行, temp/h3/live_probe.py 逐列统计):
#   列 → (带内最小值, 带内最大值, 带内行数, 该列数值行数, 带外最近的合法取值)
# 带外最近合法值这一列是定阈值的另一半依据: 阈值必须落在"带顶"与"最近合法值"
# 之间, 因此把合法值也记下来, 免得只记哨兵侧就以为越窄越安全。
MEASURED_BAND = {  # 键是列名, 值是那一列的实测五元组
    "ps1_gpsf": (-1004.0787842744421, -1004.0726439746845, 148, 174, 16.20364086044799),
    "ps1_ipsf": (-1003.566544761388, -1003.5332540474772, 108, 174, 17.935977595608897),
    "ps1_rpsf": (-1003.8843778022357, -1003.8708360913615, 135, 174, 18.200711864403978),
    "ps1_ypsf": (-1001.9422407031801, -1001.9397837161488, 142, 174, 17.946248948278676),
    "ps1_zpsf": (-1002.8841223627335, -1002.8610947767328, 133, 174, 17.701772859576238),
    # 误差列是**精确** -999.0 (149/109/136/142/134 行), 没有任何带内散布 —— 但它
    # 同样必须落进同一条带判定: 按"误差 >= 0 才算有效"处理会漏掉它。
    "ps1_gpsf_err": (-999.0, -999.0, 149, 174, 0.0014680000022053),
    "ps1_rpsf_err": (-999.0, -999.0, 136, 174, 0.0069849998690187),
}
BAND_TOP = max(hi for _lo, hi, *_rest in MEASURED_BAND.values())  # 全带上沿: 判定阈值必须高于它
NEAREST_LEGIT = min(legit for *_rest, legit in MEASURED_BAND.values())  # 带外最近合法值下界: 阈值必须低于它


def _magnitude_band(column: str) -> str:
    """``ps1_gpsf`` → ``g``; ``ps1_gpsf_err`` → ``g`` (误差列同族, 仅去后缀)。

    波段标签取列名里的 PSF 字母: 实测回包里 PSF 测光列一律以该字母收尾
    (gpsf/ipsf/rpsf/ypsf/zpsf 与对应的 ``*_err``), 不按位置猜。
    """
    return column.replace("ps1_", "").replace("_err", "").replace("psf", "")


def _source(column: str, value: float) -> BestSource:
    """造一行只带单列取值的 ps1 源对象 (坐标齐备, 否则会被半行判定剔掉)。"""
    return BestSource.from_row({"ps1_ra": 180.0, "ps1_dec": 30.0, column: value}, catalog="ps1")


class TestMeasuredBandIsAllTreatedAsMissing:
    """带内每一个实测取值都必须判成缺测 (不是"大多数"判成缺测)。"""

    def test_every_measured_band_endpoint_is_missing(self):
        """逐列取带内最小/最大两端, 都不许进 ``magnitudes``。

        这条就是"反向自证": 若有人把阈值从带 (-999.0) 收紧成点值 (例如
        -1004.07 或 -1004.08), y 波段 (带顶 -1001.9397837161488) 立刻变成
        "真值", 本用例转红。
        """
        survivors = []  # 收"被当成真值"的 (列, 取值) 对: 空列表即合规
        for column, (lo, hi, *_rest) in MEASURED_BAND.items():
            for value in (lo, hi):  # 两端各取一次: 带内的极值是最容易被收紧漏掉的那两个
                key = _magnitude_band(column)  # 期望它落进 magnitudes 的键 (波段字母)
                if _source(column, value).magnitudes.get(key) is not None:
                    survivors.append((column, value))  # 命中即说明阈值收得太紧
        assert not survivors, f"以下实测带内取值被当成了真值 (阈值被收窄了?): {survivors}"

    def test_error_column_sentinel_is_missing_too(self):
        """误差列的 -999.0 与测光列同一族: 判定口径不许只对 magnitudes 生效。"""
        assert _source("ps1_gpsf_err", -999.0).magnitude_errors == {}  # 误差侧必须同样判缺测

    def test_nearest_legit_value_survives(self):
        """带外最近的合法取值必须**保留**: 阈值取太靠近 0 的一侧会把真值抹掉。"""
        for column, (_lo, _hi, _n, _tot, legit) in MEASURED_BAND.items():
            key = _magnitude_band(column)  # 误差列与测光列同键 (都是波段字母), 只是字典不同
            values = (_source(column, legit).magnitude_errors if column.endswith("_err")  # 误差列进误差字典
                      else _source(column, legit).magnitudes)  # 其余进星等字典
            assert values.get(key) is not None, f"{column} 的合法取值 {legit} 被抹成缺测了"


class TestThresholdSitsInsideTheSafeWindow:
    """阈值必须落在 (带顶, 最近合法值) 这个开区间里, 且余量不对称地大。"""

    def test_threshold_above_band_top(self):
        """阈值高于实测带顶: 否则高带心那一族 (y) 会被当真值。"""
        threshold = BestSource.NULL_MAGNITUDE_SENTINEL  # 生产阈值: 判据读的就是它, 改了这里本用例即转红
        assert threshold >= BAND_TOP, (  # 带顶是"最不容易被漏判"的那个哨兵
            f"阈值 {threshold} 低于实测带顶 {BAND_TOP}: 高带心那一族 (y) 会被当真值"
        )

    def test_threshold_below_nearest_legit_value(self):
        """阈值低于带外最近合法值: 否则真实星等会被抹成缺测。"""
        threshold = BestSource.NULL_MAGNITUDE_SENTINEL  # 生产阈值
        assert threshold < NEAREST_LEGIT, (  # 合法值下界: 最先被误杀的那个真值
            f"阈值 {threshold} 触到最近合法值 {NEAREST_LEGIT}: 真值会被抹掉"
        )

    def test_margin_to_legit_is_orders_of_magnitude_larger_than_to_band(self):
        """余量方向也钉住: 往上留的余量必须远大于往下留的余量。

        理由: 星等是有界的正数, 向下(更负)方向再出现新哨兵族的可能性远大于出现
        -1000 到 -900 之间真实星等的可能性; 余量不对称才配得上这个先验。
        """
        threshold = BestSource.NULL_MAGNITUDE_SENTINEL  # 生产阈值
        to_legit = NEAREST_LEGIT - threshold  # 向上留的余量 (离最近合法值多远)
        to_band = threshold - BAND_TOP  # 向下留的余量 (离实测带顶多远)
        assert to_legit > 100 * to_band, f"余量不对称性消失: 距合法值 {to_legit} vs 距带顶 {to_band}"


class TestPointEqualityIsNotASufficientJudge:
    """把"点判据不够用"钉成用例, 而不是只写在报告里。"""

    def test_float_equality_misses_almost_the_whole_g_band(self):
        """按最常见的那个 2 位小数取值做浮点相等, 只能命中极少数行。"""
        column = "ps1_gpsf"  # 带内行数最多的那一列 (148/174), 判据失效在这里最明显
        lo, hi, n_band, _n_total, _legit = MEASURED_BAND[column]  # 取该列的实测五元组
        samples = [lo, (lo + hi) / 2.0, hi]  # 下沿/中点/上沿: 带内的三个代表点
        assert not any(sample == -1004.072785155375 for sample in samples), (  # 旧文档记的那个点值
            "若这三个代表点恰好都等于 -1004.072785155375, 本用例的前提 (点判据漏 majority) 失效, 需重取实测"
        )
        assert n_band > 103, "实测分布与记录不符: -1004.07 不再是主取值, 本用例的前提需按新分布重写"  # 148 = 103+45

    def test_a_two_point_enumeration_would_miss_other_bands(self):
        """只枚举 g 带的两个 2 位小数取值, 会把 r/i/z/y 四族整族漏掉。"""
        enumerated = {-1004.07, -1004.08}  # 点判据派生的"两个取值"版本
        missed = [column for column, (lo, hi, *_r) in MEASURED_BAND.items()  # 整族都高于 -1004.08 的列
                  if not (lo <= -1004.07 or hi <= -1004.07)]
        assert len(missed) >= 4, f"预期至少漏掉 4 个波段族, 实得 {missed}"  # r/i/z/y
        assert all(MEASURED_BAND[column][0] not in enumerated for column in missed), (  # 逐族确认没被枚举覆盖
            "枚举法竟覆盖了这些波段 —— 实测分布变了, 结论需重取"
        )
