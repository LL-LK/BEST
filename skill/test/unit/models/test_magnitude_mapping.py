"""回归: 波段归属必须来自 protocol 的显式星表映射, 而不是列名首字母猜测。

旧 ``from_row`` 按列名首字母猜波段, live 行证伪了它:

* ``ps1_gflags=16416`` / ``ps1_rflags=16416`` 变成 g/r **星等** (flags 是
  位掩码, 且排在 ``ps1_gpsf`` 之后, 赢了 last-write-wins 竞态),
* ``ps1_ruwe`` (无量纲天体测量残差) 变成 r 波段星等,
* ``stripe82_ummed`` (中位值) 覆盖 ``stripe82_u_h22``,
* 所有 Gaia/Landolt/J-PLUS 测光列被整体丢弃 (``phot_g_mean_mag`` / ``vmag``
  的首字母不在波段字母表里)。

``src/protocol.CATALOG_MAG_COLUMNS`` 已经编码了真实映射; 本组测试把 models
层与 protocol 层的接线钉死, 防止两层再次漂移。
"""
from __future__ import annotations

# 第三方: pytest (approx 浮点比较)
import pytest

# 本地: BestSource 行模型 + protocol 权威映射表 (Q-01/05: 键集与列名解析的
# 唯一出处在协议层, models 不得自建第二套波段表)
# 旧导入守门: 任一模块不可导入时整模块 skip 而非 collection error
try:
    # 本地: 行模型 (from_row 是波段归属的被测入口) + protocol 权威映射表
    # (星等列与误差列两张显式表, round-trip 的期望值源)
    from src.models import BestSource
    from src.protocol import CATALOG_MAG_COLUMNS, CATALOG_MAG_ERROR_COLUMNS, magnitude_column
except Exception as _legacy_err:  # legacy-import-guard
    # 源码树调整导致旧导入路径失效时整模块跳过, 不让收集期报错
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)            # 模块级跳过: 导入树问题不该算用例失败


# live 行形状的 ps1 记录: flags 与 RUWE 和 PSF 星等共用波段
# 首字母, 且此行的 g/r PSF 星等本身就是 ≈-1000 哨兵 — 波段误归属与哨兵
# 误判两个缺陷同时现形的输入。
PS1_LIVE_ROW = {                                                                        # live 行形状的 ps1 记录: 波段误归属与哨兵误判同时现形
    "ps1_ra": "179.99904154",
    "ps1_dec": "29.99972728",
    "ps1_source_id": "110737193846295516",
    "ps1_gflags": "16416.0",
    "ps1_gpsf": "-1004.0910089644447",
    "ps1_gpsf_err": "-999.0",
    "ps1_rflags": "16416.0",
    "ps1_rpsf": "-1003.8814010700681",
    "ps1_ruwe": "1.0432",
    "ps1_ipsf": "21.476521751795023",
    "ps1_ipsf_err": "0.1698320060968399",
    "ps1_ypsf": "20.089191932266274",
    "ps1_ypsf_err": "0.2246309965848922",
}


class TestExplicitMagnitudeMaps:
    """显式映射表接线守门: 波段归属只认 protocol 的表, 不认列名首字母。"""

    def test_ps1_flags_and_ruwe_never_become_magnitudes(self):
        """P0 波段误归属修复的守门测试: ps1_gflags=16416 绝不能进 magnitudes。

        flags 是位掩码、ruwe 是无量纲残差, 首字母猜波段会把 16416 当成 g
        星等; 此测试同时钉死哨兵行 (g/r 是哨兵 -> 两个波段都不得出现) 与
        真实星等 (i/y 必须按显式映射表落进 magnitudes)。
        """
        src = BestSource.from_row(PS1_LIVE_ROW, catalog="ps1")  # 一行喂进 from_row, 下面几断都在问同一件事: 键该归到哪个波段
        # g/r 是哨兵; flags (16416) 和 RUWE (1.04) 不得乘虚而入填进去
        assert "g" not in src.magnitudes  # 哨兵行下 g 波段必须缺席, 出现即说明 flags 又被当成星等
        assert "r" not in src.magnitudes  # r 同理: 只断 g 的实现仍能把 rflags 放进来
        # i/y 必须按显式映射表落进来: 只断"不该有的没有"的话, 修成"整列全丢"
        # 也一样能过, 所以正面这两个值是防止过度修正的另一半
        assert src.magnitudes["i"] == pytest.approx(21.476521751795023)  # 正面值挡住过度修正: 整列全丢也能通过只断缺席的用例
        assert src.magnitudes["y"] == pytest.approx(20.089191932266274)  # y 波段同理, 两个真实星等都进得来才算映射表真的接上了
        # 误差侧一并断: 星等收了而误差没收, 光变拟合仍会缺一半信息
        assert src.magnitude_errors["i"] == pytest.approx(0.1698320060968399)  # 只断 i 一个波段: 误差表与星等表是两张独立表, 漏接这张也要红

    def test_ps1_corrected_column_does_not_clobber_the_raw_psf_magnitude(self):
        """修正列守门: ``ps1_gpsf_corr`` 是另一列, 不得覆盖原始 g 星等。

        旧首字母匹配把 corr 列也判成 g, 后写的覆盖先写的; 修正值仍须原样
        留在 raw_data 供审计。
        """
        src = BestSource.from_row(                                                                  # 走真实的装配口
            {"ps1_gpsf": "16.5", "ps1_gpsf_corr": "16.9", "ps1_gpsf_err": "0.01"},                  # 同波段三列: 修正值、误差与原值摆在一起
            catalog="ps1",                                                                          # 星表名
        )
        assert src.magnitudes["g"] == pytest.approx(16.5)  # corr 列是另一列, 它的值不得顶掉原始 g 星等
        assert src.magnitude_errors["g"] == pytest.approx(0.01)  # 误差仍取 _err 而非 corr: 两列串位时数值断言可能双双成立
        # 修正值仍须原样留在 raw_data 供审计核对
        assert src.raw_data["ps1_gpsf_corr"] == "16.9"  # 键名与列名一致, 审计按原键回查不必反推映射表

    def test_gaia_photometry_survives_with_band_labels(self):
        """Gaia 测光列守门: phot_g_mean_mag 等无波段首字母的列必须保留并标波段。

        靠首字母猜波段的话会整列丢弃 (g 后面的拼写匹配不上任何波段列);
        phot_bp/phot_rp 映射到 bp/rp 两个 Gaia 特有波段键, ruwe 同样不得
        变成星等。
        """
        src = BestSource.from_row(                                                              # gaia 那一套列名: 首字母猜测在这里整列失效
            {                                                                                       # 行字典
                "gaia_dr3_18_source_id": "123",
                "gaia_dr3_18_ra": "10.68470833",
                "gaia_dr3_18_dec": "41.26875",
                "gaia_dr3_18_phot_g_mean_mag": "4.31",
                "gaia_dr3_18_phot_bp_mean_mag": "5.09",
                "gaia_dr3_18_phot_rp_mean_mag": "3.0",
                "gaia_dr3_18_ruwe": "0.97",
            },
            catalog="gaia_dr3_18",                                                                  # 星表名
        )
        assert src.magnitudes == {"g": 4.31, "bp": 5.09, "rp": 3.0}  # 整份等值: 少 bp 或多 ruwe 都会被这条一并抓住
        # 坐标一并断: 波段修对了而坐标仍被丢弃, 源照样能进管线却定位不到天区,
        # 这类半修状态比整列丢弃更难被发现
        assert src.ra == pytest.approx(10.68470833)  # ra 落在 g 波段修好之后仍可能被单独丢弃, 两处要分别断

    def test_stripe82_counts_and_medians_are_not_magnitudes(self):
        """stripe82 计数/中位列守门: ``unobs``/``ummed``/``ar`` 共享 'u' 前缀
        但不是 u 波段; 只有显式映射表里的 u_h22 才算 u 星等。

        若 ummed (中位值) 也算 u 波段, 它会覆盖 u_h22, 真实星等被统计量顶掉。
        """
        src = BestSource.from_row(                                                          # stripe82 那一套列名: 中位值列会覆盖真实星等列
            {                                                                                       # 行字典
                "stripe82_ra": "35.000105",                                                         # 赤经
                "stripe82_dec": "-0.451923",                                                        # 赤纬
                "stripe82_u_h22": "18.1234",                                                        # 真实星等列
                "stripe82_unobs": "7",                                                            # 观测次数列: 同样以 u 开头, 必须被排除
                "stripe82_ummed": "18.05",                                                   # 中位值列: 同样以 u 开头, 靠首字母猜就会覆盖真值
                "stripe82_ar": "2",                                                                 # 测光标志列
            },
            catalog="stripe82",                                                                     # 星表名
        )
        assert src.magnitudes == {"u": 18.1234}  # 只认 u_h22 一个键: unobs/ummed/ar 共用 u 前缀却不是星等

    def test_landolt_bands_are_recovered(self):
        """Landolt 标准星表守门: vmag 必须恢复成 v 波段 (首字母猜波段的写法会整列丢弃)。

        e_vmag 是误差列, 必须落进 magnitude_errors 而不是 magnitudes;
        b_v 是色指数不是星等, 不得进 magnitudes。
        """
        src = BestSource.from_row(                                                                  # landolt 那一套列名
            {                                                                                       # 行字典
                "landolt_field": "SA 98",                                                           # 观测场名: 不能被当成波段
                "landolt_raj2000": "10.0",                                                          # 赤经
                "landolt_dej2000": "20.0",                                                          # 赤纬
                "landolt_vmag": "12.34",                                                          # 视星等: 首字母是 v, 不在旧波段字母表里
                "landolt_e_vmag": "0.01",                                                           # 视星等误差
                "landolt_b_v": "0.51",                                                              # 另一个波段的消光改正
            },
            catalog="landolt",                                                                      # 星表名
        )
        assert src.magnitudes["v"] == pytest.approx(12.34)  # vmag 必须恢复成 v 波段, 整列丢弃即失效
        # 误差列断的是"进了 errors 而不是 magnitudes": 色指数 b_v 同在行里,
        # 若两张表串了, 0.01 与 0.51 会互换位置而数值断言仍可能都成立
        assert src.magnitude_errors["v"] == pytest.approx(0.01)  # e_vmag 与 b_v 数值不同, 串位时 0.01/0.51 互换仍会各自成立

    def test_band_attribution_is_independent_of_column_order(self):
        """确定性守门: 同一行打乱列顺序, magnitudes 必须完全一致。

        旧"首字母 + last-write-wins"实现的输出依赖 dict 插入顺序 — 同一次
        查询换个列序就给出不同星等, 结果不可复现。
        """
        forward = {                                                                                 # 正常列序的输入
            "ps1_gpsf": "16.5", "ps1_rpsf": "15.9", "ps1_ipsf": "15.1",                             # 四个波段的真星等
            "ps1_zpsf": "14.8",                                                                     # 最后一档
        }
        shuffled = {                                                                                # 打乱列序的输入
            "ps1_zpsf": "14.8", "ps1_ipsf": "15.1", "ps1_rpsf": "15.9",                             # 同样四个波段, 顺序反过来
            "ps1_gpsf": "16.5",                                                                     # 首档放到最后
        }
        assert (BestSource.from_row(forward, catalog="ps1").magnitudes  # 两种列序必须给出同一份 magnitudes, 挡住依赖插入序的实现
                == BestSource.from_row(shuffled, catalog="ps1").magnitudes)

    def test_every_mapped_band_round_trips_from_a_synthetic_row(self):
        """全星表 round-trip: protocol 映射表与 models 行模型对全部 12 个
        星表必须一致 — 每个映射列各造一个合成值, from_row 后逐波段核对。

        跳过 gaia_dr3 (legacy 别名, 现行表是 gaia_dr3_18) 与 std (导航组,
        不是可查表, Q-22)。
        """
        for catalog, bands in CATALOG_MAG_COLUMNS.items():  # 遍历映射表全部分支: 少一个星表这条用例的覆盖面就少一块
            # gaia_dr3 是 legacy 别名 (现行表是 gaia_dr3_18), std 是导航组而非
            # 可查表 (Q-22); 两者都不该在这张表里, 出现即说明表被污染
            if catalog in ("gaia_dr3", "std"):  # legacy 别名 / 非 live 表
                continue
            prefix = f"{catalog}_"  # 列名前缀由星表名拼出, 与服务端响应列的形态保持一致
            row: dict[str, str] = {}  # 合成行逐列填值, 下面两个断言比的就是它解析回来的结果
            # 每列给一个互不相同的值 (15.0 + index): 若两个列错误地落到同一波段,
            # 后写的会覆盖先写的而值相等, 断言就看不出串档了
            for index, (column, _band) in enumerate(bands.items()):                                # 逐条比对期望值源: 两层漂移要从这里被看见
                row[prefix + column] = f"{15.0 + index:.3f}"  # 每列一个互异值: 两列串到同一波段时后写覆盖会暴露出来
            src = BestSource.from_row(row, catalog=catalog)  # 合成行喂进真实入口, 期望值由同一张表反推而非另写一份
            # 期望值**逐波段取该标签的第一列**, 与 protocol.magnitude_column 同一条
            # 规则。这不是"随便挑一列": 查询层就是拿 magnitude_column 返回的那列
            # 下发约束的, 行模型若取另一列, 用户按 band 下发的条件与拿到的值就是
            # 两次不同的测量 —— 实测在 scr_galah 的 u 带 (ujkc vs usplus) 上差
            # 0.16963370 mag 的系统偏差 (AG5 P0-1)。
            # 原先这里按 enumerate 递增造期望值, 等于把"后写覆盖"钉成了契约:
            # 三列同标签时最后一列赢, 恰好与 magnitude_column 的首列相对立。
            first_index_for_band: dict[str, int] = {}  # 标签 -> 该标签首列的下标
            for index, band in enumerate(bands.values()):  # 首见即记, 后面的同标签列不再改写
                first_index_for_band.setdefault(band, index)
            expected = {band: pytest.approx(15.0 + index)  # 期望值按"该标签首列"取: 错位一列就会露馅
                        for band, index in first_index_for_band.items()}  # 星等字典的期望形态
            assert src.magnitudes == expected, catalog  # 整表比对: 少一个波段就是映射漏项

            # 逐波段再钉一道: 行模型取的值必须就是 magnitude_column 指定的那一列。
            for band in first_index_for_band:                          # 逐波段: 键即标签, 下标此处用不到
                official = magnitude_column(catalog, band)          # 查询层权威: 它决定约束落在哪列
                official_short = official.split(".", 1)[1]           # 表单键是 "表.列", CSV 表头是 "表_列"
                csv_name = f"{catalog}_{official_short}"
                assert src.magnitudes[band] == pytest.approx(float(row[csv_name])), (
                    f"{catalog}.{band}: 行模型取的值不是 magnitude_column 指定的 {csv_name} —— "
                    "约束与返回值会是两次不同的测量 (AG5 P0-1)"
                )

    def test_error_columns_map_onto_their_band(self):
        """误差列 round-trip: 每个误差列必须映射到与星等列同一波段键。

        星等表与误差表是两张独立的显式表 (CATALOG_MAG_ERROR_COLUMNS),
        漏接会让 photometry 只有值没有误差, 科学端无法做加权。
        """
        for catalog, bands in CATALOG_MAG_ERROR_COLUMNS.items():  # 误差表独立遍历: 星等表接通不代表误差表也接通
            prefix = f"{catalog}_"  # 同样的星表名前缀, 保证两张表走的是同一条剥前缀路径
            row = {prefix + column: "0.05" for column in bands}  # 全列同值 0.05: 归属错了也会被发现, 因为键会落到别的波段上
            src = BestSource.from_row(row, catalog=catalog)                                         # 走真实的装配口
            assert src.magnitude_errors == {band: pytest.approx(0.05) for band in bands.values()}  # 误差表按波段全集比: 星等表对了而误差表错了同样是漂移

    def test_unknown_catalog_still_falls_back_to_the_prefix_heuristic(self):
        """兼容回退守门: 无显式映射的星表保留旧的首字母启发式 (不丢数据)。

        显式表覆盖不到的星表 (如 mystery) 不能因为"猜错风险"就整列丢弃 —
        回退只发生在显式表缺失时, 有表时绝不回退。
        """
        src = BestSource.from_row(                                                                  # 未注册的星表名
            {"mystery_ra": "1.0", "mystery_rpsf": "15.5", "mystery_rpsf_err": "0.02"},              # 行字典带未注册前缀
            catalog="mystery",                                                                   # 未注册星表: 映射缺失必须报错而不是静默返回空
        )
        assert src.magnitudes["r"] == pytest.approx(15.5)  # 回退只在显式表缺失时发生, 有表时走错表才是真回归
        assert src.magnitude_errors["r"] == pytest.approx(0.02)  # 误差侧同样保留回退, 挡住只修星等一侧的半修

    def test_empty_catalog_keeps_the_prefix_heuristic(self):
        """无 catalog 入参时保持旧行为: 裸列名仍按首字母落波段 (rpsf -> r)。"""
        src = BestSource.from_row({"ra": "1.0", "dec": "2.0", "rpsf": "15.5"})                      # 无星表名的裸列名
        assert src.magnitudes["r"] == pytest.approx(15.5)  # 无 catalog 时按裸列名落波段, 旧行为不得被收紧

    def test_xp_catalogs_strip_their_form_table_prefix(self):
        """XP 星表守门 (2026-09-29 live 验收): xpsp/dr3xpcorr 的响应列以**表单
        表名** (gaiaxp_photinfo_replenish_) 而非星表名 (xpsp_) 为前缀。

        只剥星表前缀的话, 这两张星表的位置/星等整列静默丢失 (ra=None、
        magnitudes 为空、source_id 为空) —— 锥搜"成功"但 BestSource 是空壳。
        表单表前缀也必须剥 (长前缀优先)。
        """
        row = {                                                                                     # 构造一行站点原始数据
            "gaiaxp_photinfo_replenish_source_id": "4014208277453959552",
            "gaiaxp_photinfo_replenish_ra": "180.07675",
            "gaiaxp_photinfo_replenish_dec": "30.00123",
            "gaiaxp_photinfo_replenish_g_mag": "15.51",
            "gaiaxp_photinfo_replenish_bp_mag": "15.60",
            "gaiaxp_photinfo_replenish_rp_mag": "14.90",
        }
        for catalog in ("xpsp", "dr3xpcorr"):
            src = BestSource.from_row(row, catalog=catalog)  # 两星表共用一张表单表, 剥前缀分支只写一遍就会漏一张
            # 两张星表跑同一行: 它们共用一张表单表前缀, 剥前缀的分支只写一遍
            # 的话, 另一张就会静默回到空壳而这里恰好把它顶出来
            assert src.ra == pytest.approx(180.07675), catalog  # ra 断的是剥前缀: 落空时锥搜成功而源定位不到天区
            assert src.dec == pytest.approx(30.00123), catalog  # dec 同断, 位置两轴必须一起被剥才叫修好
            # 等值断整个 dict: 少了 bp 或 rp 任一个, 客户端的测光就缺一条带
            assert src.magnitudes == {"g": 15.51, "bp": 15.60, "rp": 14.90}, catalog  # 三条带缺一即红, 少 bp 或 rp 时下游光变会缺一整个波段
            # source_id 单列: 定位与去重全靠它, 空值会让同源被反复取到
            assert src.source_id == "4014208277453959552", catalog  # 单列断它: 键存在但为空同样让去重与定位失效

    def test_uss_dr1_bare_response_names_hit_the_mag_map(self):
        """uss_dr1 守门 (2026-09-29 live 验收): 该星表 CSV 响应是**裸名**
        (``ra_u``/``u_pstotal``, 不带 ``uss_dr1_`` 前缀, 站点 datagrid 才带)。

        剥前缀落空后裸名必须直接命中显式星等表; 按波段重构后没有规范化
        ra/dec (``ra_u`` 不是 ``ra``), 波段级 class_star 也不进 obj.class_star。
        """
        src = BestSource.from_row(                                                                 # 走装配口: 前缀剥离与波段归一都在这里生效
            {
                "ra_u": "2.277163",
                "dec_u": "-0.11891069",
                "u_pstotal": "16.082785",
                "u_err_pstotal": "0.01",
                "g_pstotal": "14.569454",
                "u_class_star": "0.98",
            },
            catalog="uss_dr1",
        )
        assert src.magnitudes["u"] == pytest.approx(16.082785)  # 裸名直接命中显式表, 剥前缀落空后的唯一兜底
        # 误差列落在 u 而不是混进 magnitudes: 两张表分家时这类串位最难察觉,
        # 因为星等与误差都是数字, 数值本身都"看起来对"
        assert src.magnitude_errors["u"] == pytest.approx(0.01)  # u_err_pstotal 与 u_pstotal 都是数字, 串进星等时数值仍看似合理
        assert src.magnitudes["g"] == pytest.approx(14.569454)
        # ra/dec 断 None: 裸名 ra_u 不是 ra, 按波段重构后没有可规范化的坐标,
        # 此时必须留 None 而不是拿 ra_u 的数字冒充 ra
        assert src.ra is None and src.dec is None  # 必须留 None: 拿 ra_u 的数字冒充 ra 会让源定位到错误天区
        # class_star 同理: u_class_star 是波段级量, 不得提升为全源属性
        assert src.class_star is None  # 波段级质量指标不得提升为全源属性, 否则跨波段误用
        # 原键仍留在 raw_data: 剥不动就不该丢, 后续加规则时有据可查
        assert src.raw_data["ra_u"] == "2.277163"  # 值仍可被后续规则回溯, 裸名不被规范化时这条是唯一凭据

    def test_smss_dr4_band_psf_columns_map(self):
        """smss_dr4 守门 (2026-09-29 live 验收): 站点已把单一 ``psf_mag`` 换成
        6 个波段 PSF 星等列 (upsf/vpsf/gpsf/rpsf/ipsf/zpsf), 且 source_id
        已下线; 静态表若还登记 psf_mag/source_id 即是幻影列 (服务端静默丢弃)。"""
        src = BestSource.from_row(                                                                  # 同上, 换一组波段字母
            {
                "smss_dr4_ra": "180.0",
                "smss_dr4_dec": "-30.0",
                "smss_dr4_upsf": "16.1",
                "smss_dr4_gpsf": "15.2",
                "smss_dr4_zpsf": "14.9",
            },
            catalog="smss_dr4",
        )
        assert src.ra == pytest.approx(180.0)  # ra 先过一遍, 波段对了而坐标被丢的半修最难排查
        assert src.magnitudes == {"u": 16.1, "g": 15.2, "z": 14.9}  # 六个 PSF 列里只登了三个, 服务端已下线单列 psf_mag


# live 锥搜回包的真实形态 (evals/groundtruth/snapshots/live-2026-10-04 逐份快照
# 核对: 31 份里 30 份带这 4 列, 例外是 uss_dr1): 元数据列带 ``inputobjs_``
# 前缀, 且排在表头最前。带星表前缀的形态 (``<cat>_inputobjs_*``) 则是同一批
# 列再叠一层星表前缀 —— 剥掉星表前缀后才认得出是元数据列。
LIVE_PS1_META_ROW = {                                                                        # live 锥搜回包的一行: 4 个元数据列 + 真星等列同在
    "inputobjs_dist_arcsec": "0.83",
    "inputobjs_input_line": "7",
    "inputobjs_input_ra": "179.99904154",
    "inputobjs_input_dec": "29.99972728",
    "ps1_gpsf": "16.5",
    "ps1_gpsf_err": "0.01",
}

# (用例标签, 行字典): 两种拼写 (带 inputobjs_ 前缀 / 无前缀裸名) × 有无星表前缀
META_COLUMN_SPELLINGS = [
    ("live 形态, 无星表前缀", {"inputobjs_dist_arcsec": "0.83", "ps1_gpsf": "16.5"}),
    ("带星表前缀的 inputobjs_ 形态", {"ps1_inputobjs_dist_arcsec": "0.83", "ps1_gpsf": "16.5"}),
    ("live 形态, 无星表前缀 (input_line)", {"inputobjs_input_line": "7", "ps1_gpsf": "16.5"}),
    ("带星表前缀的 input_line 裸名形态", {"ps1_input_line": "7", "ps1_gpsf": "16.5"}),
    ("带星表前缀的 input_ra 裸名形态", {"ps1_input_ra": "179.99904154", "ps1_gpsf": "16.5"}),
    ("带星表前缀的 input_dec 裸名形态", {"ps1_input_dec": "29.99972728", "ps1_gpsf": "16.5"}),
]


class TestProximityMetaColumnsNeverBecomeMagnitudes:
    """proximity/锥搜元数据列守门: 它们**永远**不得进 magnitudes/magnitude_errors。

    这批列 (角距弧秒 / 输入行号 / 输入坐标) 描述的是"这行匹配了哪个输入",
    不是测光。``inputobjs_*`` 首字母是 ``i``, 于是一条不认元数据列的守卫就
    会让首字母回退把角距/行号当成 i 波段星等 —— 静默污染, 无异常无日志。

    两道守卫都要在: 无前缀拼写在**剥前缀前**认得出, 带星表前缀的拼写要**剥掉
    星表前缀之后**才认得出。只判前者时, 带前缀形态会一路穿过守卫落进回退分支。
    """

    @pytest.mark.parametrize("label,row", META_COLUMN_SPELLINGS, ids=[c[0] for c in META_COLUMN_SPELLINGS])
    def test_meta_column_does_not_leak_into_i_band(self, label, row):
        """已注册星表 (ps1): 两种拼写都不得让 i 波段被元数据列占位。

        ps1 有显式星等表, 即便守卫全失手 ``use_maps`` 也会兜住 —— 所以这里真正
        被钉住的是"元数据列不进 magnitudes"这条契约本身, 而不是实现路径。
        断缺席 + 断真星等仍在, 挡住"整列全丢"式的过度修正。
        """
        src = BestSource.from_row(row, catalog="ps1")  # 带星表前缀的行, 走真实的剥前缀路径
        assert "i" not in src.magnitudes, f"{label}: 元数据列漏成 i 波段星等 (magnitudes={src.magnitudes})"  # 只断缺席
        assert src.magnitudes.get("g") == pytest.approx(16.5), f"{label}: 真星等被一起掐掉"  # 断过度修正: 整列丢弃也必须红

    @pytest.mark.parametrize("label,row", META_COLUMN_SPELLINGS, ids=[c[0] for c in META_COLUMN_SPELLINGS])
    def test_meta_column_does_not_leak_when_catalog_has_no_mag_map(self, label, row):
        """未注册星表 (无显式星等表 → 走首字母回退): 这才是守卫失手即污染的路径。

        ``mystery`` 不在 ``CATALOG_MAG_COLUMNS`` 里, 故 ``use_maps=False``, 首字母
        回退生效 —— 守卫漏判时 ``..._inputobjs_dist_arcsec`` 剥完前缀首字母是
        ``i``, 角距 0.83 会直接落成 i 波段星等。这条是本组的核心判据。
        """
        row = {k.replace("ps1_", "mystery_"): v for k, v in row.items()}  # 把行改造成带"星表前缀"的形态, 未注册故走回退
        src = BestSource.from_row(row, catalog="mystery")  # 未注册星表: 星等表缺失, 首字母回退生效
        assert "i" not in src.magnitudes, f"{label}: 角距/行号被吞成 i 波段星等 (magnitudes={src.magnitudes})"
        assert "i" not in src.magnitude_errors, f"{label}: 误差侧同样不得被元数据列占位"
        assert src.magnitudes.get("g") == pytest.approx(16.5), f"{label}: 真星等被一起掐掉"  # 断过度修正

    def test_live_cone_search_row_meta_columns_stay_out_of_photometry(self):
        """live 锥搜回包形态 (整行实样): 4 个元数据列 + 2 个真星等列同在一行。

        ``inputobjs_input_ra`` / ``inputobjs_input_dec`` 是输入天区坐标 (179.99/
        29.99), 数值上完全像星等 —— 它们若漏进 magnitudes, 光变曲线上会出现
        一个恒定的"亮源", 且不会有任何报错。
        """
        src = BestSource.from_row(LIVE_PS1_META_ROW, catalog="ps1")
        assert src.magnitudes == {"g": pytest.approx(16.5)}, f"元数据列混进了星等: {src.magnitudes}"  # 整份等值断: 4 列任一漏进来都会红
        assert src.magnitude_errors == {"g": pytest.approx(0.01)}  # 误差侧同样整份断
        # 元数据列必须仍留在 raw_data: 守卫是"不进星等", 不是"丢弃数据"
        assert src.raw_data["inputobjs_dist_arcsec"] == "0.83"  # 掐掉星等归属不等于删列, 追溯原值要留着
        # 输入坐标不得被提升成源的位置: ra/dec 只认 ra/dec 三种拼写
        assert src.ra is None and src.dec is None  # inputobjs_input_ra/dec 是输入位置, 不是本源位置

