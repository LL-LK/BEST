"""BestMultiBandPhotometry 光变装配单元测试。

覆盖光变对象的取源装配 (from_position/from_client)、波段集合、CSV/JSON 导出,
以及导出路径穿越防护 (_guard_output)。

职责: 守住光变装配与导出的回归 —— 多源匹配后波段的正确归集、CSV/JSON 两种导出
  格式的列序与取值、以及 _guard_output 对路径穿越的拦截。前两类错了会产出看似
  合理的错误光变曲线, 最后一类错了则是任意写文件的口子, 必须 fail-closed。
所属层次: test/unit 层, 对应被测模块 src/multiband_photometry.py 的
  BestMultiBandPhotometry 门面 (含 _guard_output 路径防护), 协作件是
  src/client.py 的 BestClient (cone_search 被打桩, 零真实网络) 与 src/models/
  的 BestQueryResult / BestSource (行与结果数据模型)。
对外接口: TestBestMultiBandPhotometryUnit 覆盖 from_position 与 from_client 两条
  取源入口、波段集合的组成, 以及 CSV/JSON 导出的内容与落盘路径; 路径穿越用例断言
  raises(ValueError), 是防护存在性的守门人。
依赖与数据流: 数据源是 Mock/PropertyMock 打的 cone_search 替身, 返回内联的固定
  行字典 (相当于离线快照), 因此无需任何夹具; 导出断言用 pytest 的 tmp_path 回读
  产物, 写操作全部落在 tmp_path 下, 不写仓库也不写用户目录; JSON 导出用 json
  模块回读做结构校验, CSV 则按列名取值以避开行序假设。
关键契约与不变量: 离线回放 —— 任何取源都必须经过被 patch 的 cone_search, 测试
  期间不得发出网络请求; 路径穿越必须抛 ValueError 而不是静默改写到别处, 宁可
  失败也不让导出落到调用方没指定的目录; 导出内容必须是装配后的光变点集, 不得
  把装配前的原始行当结果倒出去。
陷阱与边界: 断言写成"回读导出文件再比对"而不是直接比对内存对象, 因为导出器最
  常见的回归恰恰在列序与格式化那一层, 绕开落盘就测不到; 用 raises 而不是断言
  返回值, 是为了让"防护被摘掉改成写别处"立刻变成一次响亮的失败, 而不是安静地
  通过; 旧导入路径失效时整模块 skip (legacy-import-guard), 免得源码树调整被
  误判成导出行为回归。
"""
from __future__ import annotations

# 标准库: JSON 导出回读校验、产物路径断言, 以及 unittest.mock 打桩 cone_search
import csv  # CSV 导出按列名回读: 本组的断言要钉"哪一列是什么", 行序假设一律不用
import json
from pathlib import Path
from unittest.mock import Mock, PropertyMock, patch

# 测试框架: raises 断言拦截异常形态 (路径穿越必须抛 ValueError)
import pytest

try:
    # 本地: 光变曲线门面 (含 _guard_output 路径防护)
    from src.multiband_photometry import BestMultiBandPhotometry
except Exception as _legacy_err:  # legacy-import-guard
    # 旧源码树布局缺失时整包跳过, 不让历史导入失败伪装成本用例失败
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)         # 模块级跳过: 旧源码树布局不该被误读成导出回归
# 本地: HTTP 客户端 (cone_search 被打桩) 与源/结果数据模型
from src.client import BestClient
from src.models import BestQueryResult, BestSource


class TestBestMultiBandPhotometryUnit:
    """BestMultiBandPhotometry 取源、波段、导出与路径防护用例。"""

    def test_from_position_found(self):
        """按位置装配光变: 命中时 source_id/点数/星等都要落到对象上。

        回归锚点: from_position 是"给坐标找光变"的唯一入口, 星等字典漏装配会让
        下游相位折叠拿到空序列。
        """
        client = BestClient(rate_limit=0)  # 限流归零: cone_search 已打桩, 不该再等真实节流
        # 构造一条带 r/g 双波段星等与 SNR 的源, 验证装配完整性
        src = BestSource(source_id="BEST001", ra=180.0, dec=30.0,                                   # 带双波段星等的源: 装配完整性靠它验
                         magnitudes={"r": 15.23, "g": 16.10}, snr=45.0)                           # 两个波段加信噪比: 缺哪个字段都会在装配时丢

        # 替身 cone_search: 模拟网关锥区查询 HTTP 200 返回单源
        with patch.object(client, "cone_search") as mock_cs:                     # 只打桩这一个出口: 便于发现绕开查询直接取数的旁路实现
            mock_cs.return_value = BestQueryResult(success=True, sources=[src])  # success=True 才算命中: 失败态另有契约, 本用例只验装配
            lc = BestMultiBandPhotometry.from_position(client, 180.0, 30.0, band="r")               # 走公开装配入口
            assert lc.source_id == "BEST001"  # ID 必须透传: 取到的源与光变对象要指向同一个体
            assert lc.n_points == 1                                                               # 点数必须落上: 漏装配会让相位折叠拿到空序列
            assert lc.magnitudes.get("r") == 15.23                                           # 星等字典也要落: 只落 ID 不够, 下游要的是测光值

    def test_from_position_not_found(self):
        """锥区无源时返回空光变 (0 点) 而不是抛错或 None。

        回归锚点: 空结果是合法科学输出, 抛 KeyError 会阻断整批处理。
        """
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        # 替身 cone_search: HTTP 200 但 sources 为空
        with patch.object(client, "cone_search") as mock_cs:                                        # 打桩锥搜出口
            mock_cs.return_value = BestQueryResult(success=True, sources=[])  # 空源列表是合法科学输出: 装配层不得把它升级成异常
            lc = BestMultiBandPhotometry.from_position(client, 180.0, 30.0)                         # 走公开装配入口: 空结果也要走同一条路
            assert lc.n_points == 0  # 断 0 点而非断 None: None 会让下游迭代直接崩在半路

    def test_bands_property(self):
        """bands 属性是所有点出现过的波段排序去重集合, 与输入顺序无关。"""
        src = BestSource(magnitudes={"r": 15.0, "g": 16.0, "i": 14.5})                              # 三个波段的源: 聚合口径要覆盖多波段
        lc = BestMultiBandPhotometry(source_id="T1", points=[src])  # 直接构造绕过取数: 本用例只关心波段聚合, 不掺查询行为
        assert sorted(lc.bands) == ["g", "i", "r"]                  # 排序后比对: 字典迭代顺序不该泄漏成对外契约

    def test_to_csv(self, tmp_path):
        """CSV 导出必须落盘且包含 source_id 与星等数值 (供外部工具复核)。"""
        # 带星等误差/恒星分类的源, 验证导出列不丢字段
        src = BestSource(source_id="BEST001", ra=180.0, dec=30.0,                                   # 带误差与恒星分类的源: 导出列不能丢字段
                         magnitudes={"r": 15.23, "g": 16.10},                                       # 两个波段加误差
                         magnitude_errors={"r": 0.03}, snr=45.0, class_star=0.98)                   # 误差、信噪比与分类: 少一列导出就少一列
        lc = BestMultiBandPhotometry(source_id="BEST001", points=[src])                         # 直接构造绕过取数: 本用例只关心导出, 不掺查询
        # 导出到 tmp_path, 避免污染仓库工作区
        path = lc.to_csv(str(tmp_path / "lc.csv"))                                                  # 导出到临时区: 不污染仓库工作区
        assert Path(path).exists()                                                                  # 产物必须落盘
        content = Path(path).read_text(encoding="utf-8")  # 回读而非只看落盘: 文件存在不代表内容写对了
        assert "BEST001" in content                                                                 # ID 要在文件里: 血缘追踪靠它
        assert "15.23" in content                                                                  # 星等数值也要在: 数值被格式化成空同样算坏

    def test_to_json(self, tmp_path):
        """JSON 导出的 source_id 字段是血缘追踪的主键, 必须存在。"""
        src = BestSource(source_id="BEST001", ra=180.0, dec=30.0,                                   # 最小源: JSON 导出的主键验证
                         magnitudes={"r": 15.23})                                                   # 单波段星等
        lc = BestMultiBandPhotometry(source_id="BEST001", points=[src])                             # 直接构造绕过取数
        path = lc.to_json(str(tmp_path / "lc.json"))  # JSON 是独立出口: 与 CSV 各有一层序列化实现, 得分别验
        assert Path(path).exists()                                                           # JSON 是独立出口: 与 CSV 各有一层序列化实现
        # 回读 JSON: 证明导出的是合法 JSON 而非裸文本
        data = json.loads(Path(path).read_text(encoding="utf-8"))                              # 回读解析: 证明导出的是合法 JSON 而非裸文本
        assert data["source_id"] == "BEST001"                                                       # 主键必须存在: 血缘追踪靠它

    def test_from_client_resolves_pos_id(self):
        """from_client 对 POS_<ra>_<dec> 合成 ID 解析坐标并转 from_position。

        回归锚点: POS_ 形态是唯一可解析的 source_id (BEST 没有按 ID 检索的
        公开端点); band 参数必须原样透传到装配结果。
        """
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        src = BestSource(source_id="BEST001", ra=180.0, dec=30.0,                                   # 单波段源
                         magnitudes={"r": 15.23})                                                   # 带星等的源
        with patch.object(client, "cone_search") as mock_cs:                                        # 打桩锥搜出口
            mock_cs.return_value = BestQueryResult(success=True, sources=[src])                     # 回一个命中的结果
            lc = BestMultiBandPhotometry.from_client(client, "POS_180.0_30.0", band="r")  # POS_ 形态是唯一可解析的 ID: 没有按 ID 检索的公开端点
            assert lc.source_id == "BEST001"                                                        # 解析出的源 ID 必须透传
            assert lc.band == "r"  # band 原样透传: 静默改波段会让相位折叠用错滤光片
            assert lc.n_points == 1                                                                 # 点数也要落上

    def test_from_client_rejects_unrecognized_id(self):
        """P2-12 守门: 非 POS_ 形态的 source_id 必须显式 ValueError。

        复过的现: 静默返回 0 点容器会被导出落盘成仅表头文件还报
        "成功" — 调用方拿到一个看似完好的空文件, 正是 Q-29"未识别
        列须显式失败"要堵的漏。
        """
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        with pytest.raises(ValueError, match="unrecognized source_id"):  # match 钉住错误语义: 静默返回空容器正是这里要挡的旧缺陷
            BestMultiBandPhotometry.from_client(client, "SRC_123", band="g")                # 非 POS_ 形态: 静默返回空容器正是这里要挡的旧缺陷
        # POS_ 形态但坐标不可解析 (两段非数字), 同样显式失败 (不静默空容器)
        with pytest.raises(ValueError, match="unresolvable POS_"):                                  # 坐标不可解析同样显式失败
            BestMultiBandPhotometry.from_client(client, "POS_abc_def")                           # 两段非数字: 形态对而内容坏, 也要响亮地失败

    @pytest.mark.parametrize("bad_sid", [
        "POS_nan_2.0", "POS_190.1_nan", "POS_inf_2.0", "POS_190.1_-inf",
    ])
    def test_from_client_rejects_non_finite_coordinate(self, bad_sid):
        """POS_ 坐标含 nan/inf 必须显式 ValueError (与 :func:`float` 的差异守门)。

        回归锚点: ``float("nan")`` 与 ``float("inf")`` **不抛 ValueError**, 所以
        上面的 "unresolvable POS_" 那条接不住它们; POS_nan_2.0 会把 NaN 坐标
        一路递进 ``cone_search`` (``ConeSearchInput`` 不自校验, 其注释明写
        "由调用方保证"), 最终只换来一条来自站点的含混软错误 —— 恰好是本模块
        "显式失败 (Q-29)" 要防的结果。

        四条各占一角: nan/inf 各有正负两侧, 少判一个符号就漏一半。
        """
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        with pytest.raises(ValueError, match="non-finite coordinate"):
            BestMultiBandPhotometry.from_client(client, bad_sid, band="g")

    def test_guard_output_traversal(self, tmp_path):
        """_guard_output 必须拒绝 ../ 穿越路径, 否则用户可控路径可写到任意位置。"""
        # 本地: 导出路径防护函数 (本用例唯一需要延迟导入的私有辅助)
        from src.multiband_photometry import _guard_output
        with pytest.raises(ValueError):                                                         # 穿越路径必须抛错: 静默改写到别处就是任意写文件
            _guard_output("../unsafe.csv")


class TestCsvAttributionUnit:
    """CSV 归因三件套 (catalog + band + source_column) 必须落在每行 (G1-06, H4-1)。

    守的回归: 旧投影只有 8 列, 既无 ``catalog`` 也无物理列名, ``magnitude``
    列在多星表下混着不同测光系统的量 (``r`` 在 ps1 是 ``rpsf``、在 landolt 是
    ``rmag``、在 gaia_dr3_18 是 ``phot_rp_mean_mag``) —— 产物无法归因, 下游
    按 band 列直接混算就是把三个系统的星等当同一量。

    数据用**真实响应行的形态** (G1 LIVE-1 实测: ps1 的 ``ps1_source_id`` 线上
    发空串), 这样"首列整列空"的现场也被一并钉住。
    """

    def test_csv_carries_catalog_and_physical_column(self, tmp_path):
        """同一 band 标签在不同星表下必须落到各自的物理列名。"""
        # 本地: 行构造器 (走 from_row 才是真实解析口径, 直接构造会绕过列名映射)
        from src.models import BestSource
        ps1 = BestSource.from_row({                       # ps1 线上形态: source_id 发空串
            "ps1_source_id": "", "ps1_ra": "10.68", "ps1_dec": "41.27",
            "ps1_rpsf": "15.99", "ps1_ipsf": "12.71",
        }, catalog="ps1")
        landolt = BestSource.from_row({                   # landolt 的 r 波段是 rmag, 不是 rpsf
            "calibstars_id": "HD1", "ra_v": "180.0", "de_v": "30.0", "vmag": "12.1", "rmag": "12.4",
        }, catalog="landolt")
        lc = BestMultiBandPhotometry(source_id="POS_10.6850_41.2688", points=[ps1, landolt])  # 容器 id 非空: 站点空 id 的兜底源
        rows = list(csv.DictReader(Path(lc.to_csv(str(tmp_path / "a.csv"))).read_text(encoding="utf-8-sig").splitlines()))
        by_band = {(r["catalog"], r["band"]): r for r in rows}  # (星表, 波段) 是这批产物的归因主键
        assert by_band[("ps1", "r")]["source_column"] == "rpsf", "ps1 的 r 必须报出真实列名 rpsf"
        assert by_band[("landolt", "r")]["source_column"] == "rmag", "landolt 的 r 必须报出 rmag —— 与 ps1 同标签不同列才是本用例的要点"
        assert by_band[("ps1", "i")]["source_column"] == "ipsf"  # 同一张表内另一波段也各自归位

    def test_csv_source_id_never_collapses_to_an_all_empty_column(self, tmp_path):
        """站点发空 source_id 时必须回退到容器 id, 不得落一整列空 (血缘断在第一列)。"""
        # 本地: 行构造器 (本用例要的是 from_row 对空串 id 的真实解析结果)
        from src.models import BestSource
        src = BestSource.from_row({                       # ps1 线上实测: ps1_source_id 就是空串, 不是解析 bug
            "ps1_source_id": "", "ps1_ra": "10.68", "ps1_dec": "41.27", "ps1_rpsf": "15.99",
        }, catalog="ps1")
        assert src.source_id == "", "前提变了: 站点不再发空 id, 本用例就该撤"  # 钉住前提: 免得日后悄悄失效还绿着
        lc = BestMultiBandPhotometry(source_id="POS_10.6850_41.2688", points=[src])  # from_client 侧的真实合成 id
        text = Path(lc.to_csv(str(tmp_path / "b.csv"))).read_text(encoding="utf-8-sig")
        assert "POS_10.6850_41.2688" in text, "容器 id 没能兜住站点的空 source_id"
        ids = [r["source_id"] for r in csv.DictReader(text.splitlines())]
        assert all(i.strip() for i in ids), f"source_id 列整列为空: {ids!r}"  # 显式禁掉"一列全空"这个形态

    def test_unknown_catalog_leaves_source_column_blank_not_guessed(self, tmp_path):
        """无权威波段表的星表 (from_row 走首字母回退) 归因列如实留空, 不猜列名。"""
        # 本地: 行构造器 (未知星表必须真的走到 from_row 的启发式回退支路)
        from src.models import BestSource
        src = BestSource.from_row({"ra": "10.0", "dec": "20.0", "rpsf": "15.0"}, catalog="no_such_catalog")  # 查表落空 -> 启发式回退
        lc = BestMultiBandPhotometry(source_id="T1", points=[src])
        row = next(csv.DictReader(Path(lc.to_csv(str(tmp_path / "c.csv"))).read_text(encoding="utf-8-sig").splitlines()))
        assert row["band"] == "r" and row["source_column"] == "", "无权威条目时不得拼一个看起来能用的列名"  # 猜出来的列名比空值更坏: 它让产物看似可归因

    def test_magnitude_source_column_resolves_legacy_alias(self):
        """旧星表别名 (gaia_dr3) 必须与规范名解析到同一物理列。"""
        # 本地: 波段->物理列的反查函数 (归因列的单一来源, 值得单独钉别名归一)
        from src.multiband_photometry import _magnitude_source_column
        assert _magnitude_source_column("gaia_dr3", "rp") == _magnitude_source_column("gaia_dr3_18", "rp") == "phot_rp_mean_mag"


class TestFromClientKeepsSyntheticIdUnit:
    """from_client 不得把调用方给的 POS_ 合成 ID 丢成空串 (H4-1 实跑于 2026-10-05)。

    回归锚点: ``from_position`` 用**站点的** ``source_id`` 建容器, 而线上
    ``ps1`` 的 ``ps1_source_id`` 实测发空串 —— 调用方解析出来的
    ``POS_<ra>_<dec>`` 就这样被顶掉, 导出的 CSV 首列整列为空, 血缘断在
    第一列。G1 LIVE-2a 记下了"CSV 首列全空"这个现象, 但把它归因为"站点
    本身就发空串, 不是解析 bug" —— 站点发空串没错, 丢合成 ID 是本包的 bug。
    """

    def test_synthetic_id_survives_an_empty_site_id(self):
        """站点回空 source_id 时, 容器必须保住调用方给的 POS_ 合成 ID。"""
        client = BestClient(rate_limit=0)  # 限流置 0
        # 走 from_row 才是真实解析口径: 直接构造 BestSource 绕过了空串 id 的落库环节
        src = BestSource.from_row({"ps1_source_id": "", "ps1_ra": "10.68", "ps1_dec": "41.27", "ps1_rpsf": "15.99"}, catalog="ps1")
        assert src.source_id == "", "前提变了: 站点不再发空 id, 本用例就该撤"  # 钉住前提
        with patch.object(client, "cone_search") as mock_cs:  # 打桩锥搜出口: 零网络
            mock_cs.return_value = BestQueryResult(success=True, sources=[src])  # 命中但 id 为空
            lc = BestMultiBandPhotometry.from_client(client, "POS_10.6850_41.2688")
        assert lc.source_id == "POS_10.6850_41.2688", f"合成 ID 被站点的空 id 顶掉了: {lc.source_id!r}"

    def test_real_site_id_wins_over_the_synthetic_one(self):
        """站点真给了 id 时不得被合成 ID 覆盖 (两个都是真值, 站点值更具体)。"""
        client = BestClient(rate_limit=0)
        src = BestSource.from_row({"ps1_source_id": "PS1-77", "ps1_ra": "10.68", "ps1_dec": "41.27", "ps1_rpsf": "15.99"}, catalog="ps1")
        with patch.object(client, "cone_search") as mock_cs:  # 打桩锥搜出口: 零网络
            mock_cs.return_value = BestQueryResult(success=True, sources=[src])  # 命中且带真实 id
            lc = BestMultiBandPhotometry.from_client(client, "POS_10.6850_41.2688")
        assert lc.source_id == "PS1-77", "站点的真实标识被合成 ID 盖掉了"
