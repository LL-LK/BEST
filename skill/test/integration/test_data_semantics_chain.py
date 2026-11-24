"""Phase 3 数据语义钉桩集成测试 (Q-02/03/04/05/06/23, M11/M12/M13)。

protocol 层接线后的数据语义不变量: 带表头 CSV 的表头行不得变成幻影源
(ra=0.0/source_id='')、波段按列名而非列序映射 (gpsf->g, rpsf->r)、
gflags/ruwe 与测光列同首字母但不是星等 (须留在 raw_data 可审计)、生产
解析路径透传 catalog 剥前缀、无表头 legacy CSV 按星表列投影解析、分页必须
取完所有页、max_rows 必须截断、total_count 等于真实解析行数, 以及 CSV
注入中和不误伤负赤纬 (公式向量仍须被引号中和)。全部离线: HTTP 层由 mock
注入, 不访问 nadc.china-vo.org。

本文件由原 test_integration.py 按链路拆出 (TestDataSemantics 连同其 CSV
基准数据与 mock 助手)。拆分只是搬家, 测试名与断言一条未改。
"""
from __future__ import annotations

# 标准库: pathlib 做临时落盘路径锚定 (负赤纬/公式向量 CSV 往返测试)
from pathlib import Path

# 标准库: unittest.mock — Mock 响应替身 + patch 桩; 本文件全部 HTTP 交互
# 在此层被替身接管 (status_code/text 手工设定), 因此无真实网络。
from unittest.mock import Mock, patch

# 本地: 两阶段 REST 客户端 — 本文件主要被测对象 (权威实现在 src.client);
# legacy-import-guard: 导入失败即整文件跳过, 不让环境问题伪装成用例失败。
try:
    # src.client: 两阶段异步 HTTP 客户端 (被测入口)
    from src.client import BestClient
except Exception as _legacy_err:  # legacy-import-guard
    # pytest: 导入失败时主动 skip, 不让环境问题伪装成用例失败
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)            # 模块级跳过: 导入树问题不该算用例失败

# 本地: 下载器 (P1 落盘权威路径) — export_results 带行字典落盘语义 (原 pybest
# _save_result); 单独 try 守护, 其缺失不影响其余用例执行。
try:
    # 本地: 被测链路入口 (CSV 解析→模型→源对象的语义守门)
    from src.downloader import BestDownloader
except Exception as _legacy_err2:  # legacy-import-guard
    # pytest: 导入失败时主动 skip, 不让环境问题伪装成用例失败
    import pytest as _pytest2
    _pytest2.skip(f"legacy import unavailable: {_legacy_err2!r}", allow_module_level=True)       # 第二道守卫单独跳过: 它的缺失不该连带其余用例


# ---------------------------------------------------------------------------
# Phase 3 数据语义钉桩 (Q-02/03/04/05/23): 每条修复自带「改坏就红」的定向防线
# ---------------------------------------------------------------------------

# 实测形态的 ps1 投影: PSF 星等列 + 一个 flag 列 + 一个 RUWE
# 列 — 后两者与测光列共用波段首字母, 但本身不是星等 (Q-03 边界基准数据)。
CSV_WITH_HEADER = (                                                                                 # 带表头的 ps1 投影
    "ps1_source_id,ps1_ra,ps1_dec,ps1_gpsf,ps1_rpsf,ps1_gpsf_err,ps1_gflags,ps1_ruwe\n"   # 表头含 flag 与 RUWE: 两者与测光列共用波段首字母
    "BEST001,180.0,30.0,18.2,18.5,0.03,16416,1.04\n"                                                # 第一条源
    "BEST002,181.0,31.0,19.1,18.9,0.04,16416,0.98\n"                                                # 第二条源
)
CSV_HEADERLESS = "180.0,30.0,15.23,16.10,45.0,0.98\n181.0,31.0,14.80,15.50,32.0,0.95\n"             # 无表头 CSV: 只能按星表列投影解析


def _mock_csv_response(csv_text: str):
    """把一段文本包成 HTTP 200 的 Mock 响应, 供 phase-2 GET 桩复用。

    无表头/带表头/多页/计数 JSON 等数据形态都经此注入, 让每个数据语义
    用例只关心"回包长什么样", 不必重复搭 Mock。
    """
    # 替身工厂: 把一段 CSV 文本包成 HTTP 200 的 Mock 响应, 供 phase-2 GET
    # 桩复用 (无表头/带表头/多页等数据形态都经此注入)。
    resp = Mock()                                              # 离线根基: phase-2 取数的 HTTP 出口在此被替身接管
    resp.status_code = 200                                    # 客户端内联校验 status_code, 桩必须显式给 200
    resp.text = csv_text                                      # 正文原样注入: 计数/CSV/多页三种形态共用这一个口
    return resp


class TestDataSemantics:
    """Phase 3: protocol 层接线后的数据语义不变量。"""

    def test_header_row_never_becomes_phantom_source(self):
        """Q-02: 带表头 CSV 的表头行不得进入结果 (幻影源 ra=0.0/source_id='')。"""
        client = BestClient(rate_limit=0)                     # Q-02 链路: 真客户端 + 桩回包, 走的是生产解析路径
        # 替身: phase-2 GET 固定回带表头 CSV (HTTP 200) — 表头行是 Q-02 的判定对象
        with patch.object(client.session, "get", return_value=_mock_csv_response(CSV_WITH_HEADER)):  # 打桩在数据面
            result = client._fetch_sqlid_data(                                                      # 走真实分页入口
                "s9999", output_format="csv", max_rows=100,                                         # 上限
                catalog_path="ps1/q",                                                               # 星表路径: 没有它就无从按投影解析
            )
        assert len(result.sources) == 2, [s.source_id for s in result.sources]  # 挡住"表头行被当成第 3 条源"
        assert all(not (s.ra == 0.0 and s.source_id == "") for s in result.sources)  # 守住"零值+空 id"这组幻影特征
        assert result.sources[0].source_id == "BEST001"      # 挡住"跳过表头后行序整体错位一格"

    def test_bands_map_by_column_name_not_position(self):
        """Q-03: 波段按列名映射 (gpsf->g, rpsf->r), 不按列序猜测。"""  # Q-03 链路: 波段归属只能来自列名, 列序换了结果必须不变
        client = BestClient(rate_limit=0)                                                           # 限流归 0
        # 替身: phase-2 GET 固定回带表头 CSV (HTTP 200) — 列名是波段映射的唯一依据
        with patch.object(client.session, "get", return_value=_mock_csv_response(CSV_WITH_HEADER)):  # 打桩在数据面
            result = client._fetch_sqlid_data(                                                      # 走真实分页入口
                "s9999", output_format="csv", max_rows=100,                                         # 上限
                catalog_path="ps1/q",                                                               # 星表路径
            )
        mags = result.sources[0].magnitudes                                                         # 取第一个源的星等字典
        assert mags.get("g") == 18.2, mags                                                       # 必须按列名映射到 g: 按列序映射会把两列搞反
        assert mags.get("r") == 18.5, mags                                                          # 同样按列名映射到 r

    def test_flag_and_ruwe_columns_are_not_photometry(self):
        """Q-03 边界: ps1_gflags / ps1_ruwe 与测光列同首字母, 但不是星等。"""
        client = BestClient(rate_limit=0)                                                           # 限流归 0
        # 替身: phase-2 GET 固定回带表头 CSV (HTTP 200) — gflags/ruwe 与测光列同首字母
        with patch.object(client.session, "get", return_value=_mock_csv_response(CSV_WITH_HEADER)):  # 打桩在数据面
            result = client._fetch_sqlid_data(                                                      # 走真实分页入口
                "s9999", output_format="csv", max_rows=100,                                         # 上限
                catalog_path="ps1/q",                                                               # 星表路径
            )
        source = result.sources[0]  # 断言整份 magnitudes: 少一个键与多一个错键同样会被这条抓住
        assert source.magnitudes == {"g": 18.2, "r": 18.5}                                  # 星等字典必须恰好两项: 混进 flag 列就是波段误归属
        assert source.magnitude_errors == {"g": 0.03}  # 误差侧单列断言: 星等收了而误差没收, 光变拟合会缺一半信息
        # 这些值不是测光, 但必须留在 raw_data 里可审计
        assert source.raw_data["ps1_gflags"] == "16416"                                      # flag 列必须留在原始数据里: 可审计是它的唯一价值
        assert source.raw_data["ps1_ruwe"] == "1.04"                                                # RUWE 列同理

    def test_from_row_strips_catalog_prefix_in_production_path(self):
        """Q-04: 生产解析路径必须透传 catalog (前缀剥离后 source_id 非空)。"""
        client = BestClient(rate_limit=0)                                                           # 限流归 0
        # 替身: phase-2 GET 固定回带表头 CSV (HTTP 200) — 前缀剥离后 source_id 才可判
        with patch.object(client.session, "get", return_value=_mock_csv_response(CSV_WITH_HEADER)):  # 打桩在数据面
            result = client._fetch_sqlid_data(                                                      # 走真实分页入口
                "s9999", output_format="csv", max_rows=100,                                         # 上限
                catalog_path="ps1/q",                                                               # 星表路径
            )
        assert result.sources[0].source_id == "BEST001"  # 前缀没剥时 source_id 会带 ps1_ 前缀, 这条直接红
        assert result.sources[0].catalog == "ps1"  # catalog 落的是星表名而不是列前缀, 供下游按表分流

    def test_headerless_csv_uses_catalog_column_projection(self):
        """Q-05: 无表头 legacy CSV 按星表列投影解析 (ra/dec 落位正确)。"""
        client = BestClient(rate_limit=0)                                                           # 限流归 0
        # 替身: phase-2 GET 固定回无表头 CSV (HTTP 200)
        with patch.object(client.session, "get", return_value=_mock_csv_response(CSV_HEADERLESS)):  # 打桩无表头数据页
            result = client._fetch_sqlid_data(                                                      # 走真实分页入口
                "s9999", output_format="csv", max_rows=100,                                         # 上限
                catalog_path="ps1/q",                                                               # 星表路径: 按投影解析的依据
            )
        assert len(result.sources) == 2  # 无表头两行都要解析出来, 少一行说明列投影整体错位
        assert result.sources[0].ra == 180.0  # ra 落位正确是投影的第一顺位判据, 错列时数值必不对
        assert result.sources[0].dec == 30.0  # dec 同断: 只修 ra 不修 dec 的半修状态最容易被放过

    def test_pagination_fetches_all_pages(self):
        """M11 防线: 分页必须取完所有页 (只取第一页必须变红)。

        P0-2 起每次查询先发一次 getcount (服务端总数), 故 mock 序列首项是
        计数响应; ``total_count`` 从此以服务端口径为准。
        """
        client = BestClient(rate_limit=0)                                                           # 限流归 0
        page1 = "ps1_source_id,ps1_ra,ps1_dec\n" + "".join(                                         # 第一页三行: 服务端说共五行
            f"BEST{i:03d},{180.0 + i * 0.01},{30.0}\n" for i in range(3)                            # 逐行生成
        )
        page2 = "ps1_source_id,ps1_ra,ps1_dec\n" + "".join(                                         # 第二页两行
            f"BEST{i:03d},{181.0 + i * 0.01},{31.0}\n" for i in range(3, 5)                         # 逐行生成
        )
        # 替身序列 (side_effect 列表): 依次模拟协议阶段 — 首项 getcount
        # 计数响应 ({"total": 5}), 之后两项是两个 CSV 数据页 (page_size=3
        # 时的第 1、2 页); 全部 HTTP 200。
        responses = [                                                                               # 按请求次序排好的三个回包
            _mock_csv_response('{"total": 5}'),                                                     # 计数端点先回
            _mock_csv_response(page1),                                                              # 第一数据页
            _mock_csv_response(page2),                                                              # 第二数据页
        ]
        with patch.object(client.session, "get", side_effect=responses):                            # 按次序喂桩: 一次替身要扮演三个阶段
            result = client._fetch_sqlid_data(                                                      # 走真实分页入口
                "s9999", output_format="csv", max_rows=100,                                         # 上限
                page_size=3, catalog_path="ps1/q",                                                  # 页长给三: 逼它翻第二页
            )
        assert len(result.sources) == 5, [s.source_id for s in result.sources]  # 两页拼完才是 5 行: 只取第一页的回归会让这条与末行断言同时红
        assert result.sources[-1].source_id == "BEST004"  # 末行落在第二页 (BEST004), 断它才抓得住\漏取第二页\而非只断总数
        assert result.total_count == 5  # total_count 取服务端口径 (getcount 报 5), 不是本地解析行数
        assert result.truncated is False  # 未触上限故不得置截断位, 否则下游会误以为还有续页可拉

    def test_max_rows_truncates_result(self):
        """M12 防线: max_rows 必须截断结果 (total_fetched 不推进必须变红)。"""
        client = BestClient(rate_limit=0)                                                           # 限流归 0
        csv_text = "ps1_source_id,ps1_ra,ps1_dec\n" + "".join(                                      # 五行数据
            f"BEST{i:03d},{180.0 + i * 0.01},{30.0}\n" for i in range(5)                            # 逐行生成
        )
        # 替身: 单页回 5 行 CSV (HTTP 200), max_rows=2 — 验证客户端上限截断
        with patch.object(client.session, "get", return_value=_mock_csv_response(csv_text)):        # 打桩在数据面
            result = client._fetch_sqlid_data(                                                      # 走真实分页入口
                "s9999", output_format="csv", max_rows=2,                                           # 上限刻意给二: 截断必须生效
                page_size=10, catalog_path="ps1/q",                                                 # 页长给十: 一页装得下, 排除翻页干扰
            )
        assert len(result.sources) == 2  # 客户端上限优先于服务端页大小: 5 行进来只交 2 行
        assert result.total_count == 2  # 计数随交付量收敛, 不能仍报服务端那 5 行

    def test_total_count_equals_real_parsed_rows(self):
        """Q-23: total_count 等于真实解析行数 (无幻影虚增; M13 突变必须变红)。"""
        client = BestClient(rate_limit=0)                                                           # 限流归 0
        # 替身: phase-2 GET 固定回带表头 CSV (HTTP 200) — 幻影行会让 Q-23 计数虚增
        with patch.object(client.session, "get", return_value=_mock_csv_response(CSV_WITH_HEADER)):  # 打桩在数据面
            result = client._fetch_sqlid_data(                                                      # 走真实分页入口
                "s9999", output_format="csv", max_rows=100,                                         # 上限
                catalog_path="ps1/q",                                                               # 星表路径
            )
        assert result.total_count == 2  # 幻影行会让这条虚增到 3, 正是 M13 突变要抓的形态
        assert result.returned_count == 2  # 与 total_count 同为 2 才说明既没多算也没少算

    def test_negative_dec_survives_csv_roundtrip(self):
        """Q-06: 负赤纬经所有 emitter 落盘仍为 -5.0 (旧内联消毒加引号致数据损坏)。"""
        # 标准库: tempfile — 本地 IO: 临时目录内落盘后读回 (负赤纬往返, 不污染仓库)
        import tempfile
        # 本地 IO: 临时目录内落盘后读回 — 验证 -5.0 原样往返, 不被消毒逻辑
        # 包成 "'-5.0" (旧缺陷把负号当公式向量中和, 数据静默损坏)。
        with tempfile.TemporaryDirectory() as td:                                                   # 临时目录: 落盘产物不许留在工作区
            out = Path(td) / "neg.csv"                                                              # 目标文件落在临时区
            dl = BestDownloader(BestClient(rate_limit=0), td)                                       # 只做落盘的下载器: 客户端限流归零
            dl.export_results(                                                                      # 走模型外的直写入口
                [{"ps1_source_id": "X", "ps1_ra": "10.0", "ps1_dec": "-5.0"}],                      # 负赤纬那行
                "neg.csv",                                                                          # 文件名
            )
            text = out.read_text(encoding="utf-8")                                                  # 回读落盘字节
        assert "-5.0" in text                                                                       # 负赤纬必须原样落盘
        assert "'-5.0" not in text                                                                 # 不得被引号包住: 包了数值列就退化成文本列

    def test_formula_vector_is_quoted(self):
        """Q-06 另一半: 真公式向量仍须被引号中和。"""
        # 标准库: tempfile — 本地 IO: 临时目录内落盘后读回 (公式向量中和, 不污染仓库)
        import tempfile
        # 本地 IO: 临时目录内落盘后读回 — 验证 =cmd|... 公式向量被中和为
        # "'=cmd" (CSV 注入防线), 与上一条负赤纬不误伤互为边界。
        with tempfile.TemporaryDirectory() as td:                                                   # 临时目录
            out = Path(td) / "f.csv"                                                                # 目标文件落在临时区
            dl = BestDownloader(BestClient(rate_limit=0), td)                                       # 只做落盘的下载器
            dl.export_results(                                                                      # 走模型外的直写入口
                [{"ps1_source_id": "=cmd|'/c calc'!A1", "ps1_ra": "10.0"}],                         # 公式向量那行
                "f.csv",                                                                            # 文件名
            )
            text = out.read_text(encoding="utf-8")                                                  # 回读落盘字节
        assert "'=cmd" in text                                                               # 公式向量必须被引号中和, 否则 Excel 打开即执行
