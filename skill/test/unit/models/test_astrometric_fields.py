"""回归: BestSource.from_row 必须按真实列名填充六个天体测量/质量字段 (budget §6.1 G1)。

缺陷形态 (修复前): ``ra_err``/``dec_err``/``parallax``/``parallax_err``/
``fwhm``/``quality_flag`` 六个字段从不被 from_row 填充 — CSV 行里明明有
``ps1_parallax`` 等真实列, 解析后字段仍停留在默认值 (None / "good"), 真实值
只在 ``raw_data`` 里; 下游直接读 ``obj.parallax`` 会静默拿到 None。

本组测试的列名全部锚定 ``src/protocol_catalog_tables.py`` 的 CATALOG_COLUMNS
响应列清单 (线上真实发布的拼写): stripe82 的 ``rarms``/``decrms`` (坐标 RMS),
ps1 的 ``parallax``/``parallax_err``, gaia_dr3_18 的 ``parallax_error``
(误差列拼写与 ps1 不同)。fwhm/quality_flag 当前无任何星表发布, 字段保留
缺省值 — 上游将来发布或本包导出列回读时按同名字直接流入。
"""
from __future__ import annotations

# 第三方: pytest (approx 浮点比较)
import pytest  # approx: 视差/坐标是文本转 float, 直等会因尾数差误报

# 旧导入守门: src.models 不可导入时整模块 skip 而非 collection error
try:
    # 本地: 源数据模型 (六字段填充的被测入口) + 协议层真实列清单 (期望值源)
    from src.models import BestSource
    from src.protocol_catalog_tables import CATALOG_COLUMNS
except Exception as _legacy_err:  # legacy-import-guard
    # 源码树调整导致旧导入路径失效时整模块跳过, 不让收集期报错
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)            # 模块级跳过: 导入树问题不该算用例失败


class TestParallaxFields:
    """parallax / parallax_err: ps1 与 gaia_dr3_18 的真实列名都必须落入字段。"""

    def test_ps1_parallax_columns_fill_the_fields(self):
        """ps1 行 (live 实证列名) 的视差与视差误差必须进字段。

        修复前 ``ps1_parallax``/``ps1_parallax_err`` 只进 raw_data,
        ``obj.parallax`` 恒为 None — 下游读字段即静默丢失。
        """
        src = BestSource.from_row(                                                                  # 走真实的装配口
            {                                                                                       # 行字典: 列名必须与线上发布拼写一致
                "ps1_source_id": "110737193846295516",                                              # 大整数标识: 证明它没被当成数值列
                "ps1_ra": "179.99904154",                                                           # 赤经
                "ps1_dec": "29.99972728",                                                           # 赤纬
                "ps1_parallax": "2.534",  # mas 量级: 确认走的是视差列而非星等列
                "ps1_parallax_err": "0.021",  # 约为视差的 0.8%, 比例失真说明取错列
            },
            catalog="ps1",                                                                          # 星表名决定用哪张列映射表
        )
        assert src.parallax == pytest.approx(2.534)  # 挡"只进 raw_data 字段留 None"
        assert src.parallax_err == pytest.approx(0.021)                                            # 视差误差也要落字段: 只填视差等于半个修复
        # 视差列不是测光列: 不得借道显式映射/启发式混进 magnitudes
        assert src.magnitudes == {}  # 挡"视差被当成某个波段的星等"

    def test_gaia_parallax_error_spelling_fills_the_field(self):
        """gaia_dr3_18 的误差列拼写是 ``parallax_error`` (非 ``_err``)。"""
        src = BestSource.from_row(                                                             # gaia 那一套列名: 误差列拼法与 ps1 不同
            {                                                                                       # 行字典
                "gaia_dr3_18_source_id": "123",                                                     # 标识列
                "gaia_dr3_18_ra": "10.68470833",                                                    # 赤经
                "gaia_dr3_18_dec": "41.26875",                                                      # 赤纬
                "gaia_dr3_18_parallax": "7.32",                                                     # 视差列
                "gaia_dr3_18_parallax_error": "0.03",  # _error 后缀: 与 ps1 的 _err 不同拼写
            },
            catalog="gaia_dr3_18",                                                               # 星表名用真实表名而不是别名: 别名在这里不成立
        )
        # 这条是"每个星表各写各的列名"的守门人: gaia 用 _error 而 ps1 用 _err,
        # 映射表若只按 ps1 的拼写推, gaia 行的误差会静默留空而字段看着是合法的
        assert src.parallax == pytest.approx(7.32)                                                  # 视差必须落字段
        assert src.parallax_err == pytest.approx(0.03)  # 挡"映射表只认 ps1 拼写"

    def test_parallax_over_error_is_not_an_error(self):
        """``parallax_over_error`` 是信噪比比例列, 不得当成 parallax_err。"""
        src = BestSource.from_row(                                                                  # 只有视差与另一条误差列
            {"gaia_dr3_18_parallax": "7.32", "gaia_dr3_18_parallax_over_error": "244.0"},   # 另一条误差列: 拼法与前一条不同, 少认一条就是静默丢失
            catalog="gaia_dr3_18",                                                                  # 星表名
        )
        # 244.0 是视差信噪比, 量级比视差本身大两个数量级; 若被前缀匹配误收成
        # parallax_err, 下游算出的不确定度会离谱却不报错, 属静默数据损坏
        assert src.parallax == pytest.approx(7.32)                                                  # 视差必须落字段
        assert src.parallax_err is None  # 挡"前缀匹配把 over_error 误收成误差"

    def test_sentinel_exemption_is_narrowed_to_proven_columns(self):
        """P2-3 豁免收窄 (AH3-04, 2026-10-06): 豁免按**列**, 不按整类天体测量。

        原实现写的是「天体测量列整类白免」, 其**自身注释给出的理由**只有一条:
        高自行星 pmra 可达 ±1e4 mas/yr。而 pmra/pmdec/radial_velocity 本就在
        ``_SENTINEL_EXEMPT_COLUMNS`` 窄名单里 —— 整类豁免比理由所需宽得多,
        顺带把**视差的缺测哨兵**放行了。

        收窄的实测依据 (temp/_astro_range.py 扫仓内全部快照 34,379 行逐列核量程):
        ``gaiaxp_photinfo_replenish_parallax`` 有 **108 个 <= -999 的取值, 且逐字
        相同都是 '-999.0'** (temp/_parallax_sentinel_shape.py) —— 固定值 + 真实
        视差量级只到 ±15 mas, 两者合起来只能读成哨兵。原注释引用的证据是
        「ps1 与 gaia_dr3_18 各 200 行里没有这类取值」, 样本窄了一档, 结论
        在全语料上不成立。
        """
        # (a) 真正到得了哨兵带的列仍受保护 —— 这是原用例**真正要守**的东西
        src = BestSource.from_row(
            {"gaia_dr3_18_pmra": "-1500.0", "gaia_dr3_18_pmdec": "-1200.0"}, catalog="gaia_dr3_18"
        )
        assert src.raw_data.get("gaia_dr3_18_pmra") == "-1500.0"  # 合法高自行: 豁免保住原值

        # (b) 视差的缺测哨兵不再被整类豁免放行
        sentinel = BestSource.from_row(
            {"gaiaxp_photinfo_replenish_parallax": "-999.0"}, catalog="xpsp"
        )
        assert sentinel.parallax is None, "视差哨兵仍被整类豁免放行 (AH3-04 回归)"

        # (c) 真实视差不受影响, 含合法的负视差
        real = BestSource.from_row(
            {"gaiaxp_photinfo_replenish_parallax": "-1.2"}, catalog="xpsp"
        )
        assert real.parallax == pytest.approx(-1.2), "合法负视差被哨兵判据误伤"

    def test_photometry_sentinel_still_applies(self):
        """P2-3 边界守门: 豁免只给**已证明量程到得了哨兵带**的列, 测光列必须仍然生效。

        没有任何天文星等到 -999, 因此 gpsf=-999 继续按"无测光"处理;
        收窄豁免的同时不能把测光侧的哨兵一起废掉 (修成"哨兵全废"会静默放行
        幻影星等), 故这条反向对照必须留着。
        """
        src = BestSource.from_row(                                                                  # 一行里星等与视差都是哨兵
            {"ps1_gpsf": "-999.0", "ps1_gpsf_err": "-999.0",                                        # 星等侧两个哨兵列
             "ps1_parallax": "-999.0"}, catalog="ps1"                                               # 视差侧哨兵
        )
        # 三个 -999 全部判缺测: 测光侧与视差侧同一判据 (AH3-04 收窄后)。
        # 只断测光侧的话, "把哨兵判据整体废掉"这种过度修复照样能混过测试。
        assert src.magnitudes.get("g") is None  # 测光侧仍按"无测光"处理
        assert src.magnitude_errors.get("g") is None  # 误差侧同样清成 None
        assert src.parallax is None  # 视差侧同判: -999 是该列的缺测哨兵 (全语料 108 处逐字相同)


class TestMissingCoordinatesAreNone:
    """P1-4: ra/dec 缺失即 None, 不得填 0.0 冒充天球原点。"""

    def test_empty_ra_dec_yield_none_not_origin(self):
        """空/``null`` 的 RA/Dec 必须落 None。

        复过的现: ``obj.ra = nv or 0.0`` 会把缺失坐标填成 (0,0) —
        那是一个真实天球位置, 畸形行随后被 deduplicate 当成同一位置互相
        去重 (src/crossmatch.py 的注释早已把该做法点名为反模式)。
        """
        src = BestSource.from_row(                                                                  # 坐标缺测而星等完好的行
            {"ps1_ra": "", "ps1_dec": "null", "ps1_gpsf": "15.0"}, catalog="ps1"               # 赤经空串、赤纬字面 null: 两种缺测形态一起给
        )
        assert src.ra is None  # 挡"or 0.0": (0,0) 是真实天球位置, 会被去重误伤
        assert src.dec is None  # "null" 字符串同样按缺失处理, 不按 0.0
        # 其它字段不受影响 (星等照常填充)
        assert src.magnitudes.get("g") == pytest.approx(15.0)                                      # 星等必须照常落: 坐标缺测不该连带丢掉测光

    def test_present_coordinates_still_fill(self):
        """正常坐标必须照常落入字段 (修缺失语义不得顺径改正常路径)。"""
        src = BestSource.from_row(                                                                  # 坐标完好的行
            {"ps1_ra": "179.99904154", "ps1_dec": "29.99972728"}, catalog="ps1"                     # 坐标齐全
        )
        assert src.ra == pytest.approx(179.99904154)  # 挡"把全部坐标一律判缺失"的过度修复
        assert src.dec == pytest.approx(29.99972728)                                                # 赤纬必须落字段


class TestPositionErrorFields:
    """ra_err / dec_err: stripe82 的 rarms/decrms (坐标 RMS) 必须落入字段。"""
    def test_stripe82_rms_columns_fill_ra_dec_errors(self):
        """stripe82 响应列清单里的 ``rarms``/``decrms`` 即坐标误差。

        修复前这两列对带显式映射表的 stripe82 完全被忽略; 同时守它们不得
        借首字母启发式混进 magnitudes (``rarms`` 以 r 开头, 旧回退路径会
        把它当成 r 波段星等)。
        """
        src = BestSource.from_row(                                                                  # stripe82 那一套列名
            {                                                                                       # 行字典
                "stripe82_calibstars_id": "CALIBSTARS_0844369",                                  # 裸 ID 列名是 stripe82 的真实拼写
                "stripe82_ra": "35.000105",                                                         # 赤经
                "stripe82_dec": "-0.451923",                                                        # 赤纬
                "stripe82_rarms": "0.00028",  # 2.8e-4 deg: 坐标 RMS, 不是星等
                "stripe82_decrms": "0.00024",  # 两列取不同值: 交换赋值也该被抓住
                "stripe82_u_h22": "18.1234",  # 唯一真测光列, 用作 magnitudes 的等值基准
            },
            catalog="stripe82",                                                                     # 星表名
        )
        assert src.ra_err == pytest.approx(0.00028)  # 挡"显式映射表漏了 stripe82 整条分支"
        assert src.dec_err == pytest.approx(0.00024)                                                # 坐标 RMS 要落进误差字段
        # rarms 以 r 开头, 旧的首字母回退路径会把它当成 r 波段星等塞进
        # magnitudes; 这条等值断言挡的正是那种"顺手多收一列"的启发式
        assert src.magnitudes == {"u": 18.1234}                                                    # 星等只落真实波段: 坐标列不得混进星等字典


class TestFwhmAndQualityFlag:
    """fwhm / quality_flag: 当前无星表发布, 同名列 (导出回读) 必须流入。"""

    def test_canonical_columns_fill_fwhm_and_quality_flag(self):
        """裸列名 fwhm/quality_flag (无 catalog 上下文) 必须填充字段。

        这两个字段当前没有任何星表发布 (QUALITY_COLUMNS 同为空), 但本包
        导出列 (downloader 写 quality_flag 列) 回读时应原样落入字段, 而不是
        停留在默认值。
        """
        src = BestSource.from_row(                                                                  # 无前缀列名的一行
            {"ra": "180.0", "dec": "30.0", "fwhm": "2.7", "quality_flag": "needs_review"}           # 两个当前无星表发布的字段: 保留缺省值
        )
        assert src.fwhm == pytest.approx(2.7)  # 挡"裸列名 fwhm 认不出"
        assert src.quality_flag == "needs_review"  # 挡"标签回落默认值 good"

    def test_absent_columns_keep_defaults(self):
        """行里没有这些列时字段保持缺省 (None / "good"), 不拿默认值冒充真实值。"""
        src = BestSource.from_row({"ps1_ra": "1.0", "ps1_dec": "2.0"}, catalog="ps1")               # 只有坐标的一行
        # 逐字段钉缺省: 若解析层改成"缺列即填 0.0", 调用方分不清"没测到"与
        # "测到是零", 而 quality_flag 填错更糟 — 它会被下游当成可信标签采信
        assert src.ra_err is None                                                            # 没发布就留 None: 伪造 0 会被下游当成真实测值
        assert src.dec_err is None                                                                  # 赤纬误差同理
        assert src.parallax is None  # 挡"缺列即填 0.0": 没测到 ≠ 测到是零
        assert src.parallax_err is None                                                             # 未见过的字段同理
        assert src.fwhm is None                                                                     # 未见过的字段同理
        assert src.quality_flag == "good"  # 缺省 good 而非空串: 空串是第三态

    def test_empty_quality_flag_column_keeps_default(self):
        """quality_flag 列是空串时不当有效值 (保留缺省 "good")。"""
        src = BestSource.from_row({"ra": "1.0", "quality_flag": "  "})  # 纯空白: 站点导出常见写法
        # 站点导出常把缺测写成纯空白; 若按 strip 后非空就采信, 标签会变成 ""
        # 这种下游无法处理的第三态, 不如老老实实留 "good"
        assert src.quality_flag == "good"  # 挡"空白标签被当成有效值原样透出"


class TestRoundTrip:
    """导出 (to_dict) -> 回读 (from_row) 必须保持六字段不丢。"""

    def test_round_trip_preserves_the_six_fields(self):
        """to_dict 的 raw_data 段带原列名, 回读必须重新填充六个字段。

        下载/导出链路写出这些列后再读回时, 字段级信息不得衰减成 None。
        """
        row = {                                                                                   # 回读用的行字典: 导出再解析是这条要验的闭环
            "ps1_source_id": "B1",
            "ps1_ra": "180.0",
            "ps1_dec": "30.0",
            "ps1_parallax": "2.5",
            "ps1_parallax_err": "0.1",
            "fwhm": "2.7",  # 裸列名: 与带前缀列并存的混合形态正是导出回读的实况
            "quality_flag": "good",
        }
        exported = BestSource.from_row(row, catalog="ps1").to_dict()  # 走真实导出路径
        reread = BestSource.from_row(exported, catalog="ps1")  # 再原样喂回去
        # 走完整往返而不是只测 from_row: 缺陷的真实触发面是"下载写出后再读回",
        # 只测单向往返会漏掉 to_dict 侧列名写错导致回读认不出的那半程
        assert reread.parallax == pytest.approx(2.5)  # 挡"导出丢列名致回读认不出"
        assert reread.parallax_err == pytest.approx(0.1)                                            # 回读后误差列要落
        assert reread.fwhm == pytest.approx(2.7)                                                    # 回读后未见过的字段照样落
        assert reread.quality_flag == "good"                                                        # 回读后质量标志落缺省值

    def test_mapped_columns_are_real_catalog_columns(self):
        """别名表里的星表侧列名必须是 CATALOG_COLUMNS 真实发布的拼写。

        防"按猜的列名建映射": rarms/decrms 归 stripe82, parallax_err 归 ps1,
        parallax_error 归 gaia_dr3_18 — 逐个在权威列清单里核实存在。
        """
        # 拿权威列清单当断言源, 而不是把期望值写死: 星表改列名时这里会第一个红,
        # 提醒同步改映射表, 而不是让映射表悄悄对不上真实响应
        assert "stripe82_rarms" in CATALOG_COLUMNS["stripe82"]  # 拿权威清单当源, 不写死期望
        assert "stripe82_decrms" in CATALOG_COLUMNS["stripe82"]                              # stripe82 的坐标 RMS 列必须真的在注册表里
        assert "ps1_parallax" in CATALOG_COLUMNS["ps1"]                                             # ps1 视差列必须在
        assert "ps1_parallax_err" in CATALOG_COLUMNS["ps1"]                                         # ps1 视差误差列必须在
        assert "gaia_dr3_18_parallax_error" in CATALOG_COLUMNS["gaia_dr3_18"]  # _error 拼写独立守
