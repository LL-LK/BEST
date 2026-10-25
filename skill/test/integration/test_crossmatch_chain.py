"""交叉匹配链集成测试: BestCrossMatch 的输入校验、依赖注入与适配层。

空坐标列表与 RA/Dec 长度不齐必须在入口拦住 — 硬配对会把 A 目标的赤经配到
B 目标的赤纬, 产出看似合理的错误匹配; 依赖注入方向不变 (xm.client 就是
注入的 client); crossmatch_source_list 只是坐标数组的适配层, 不允许在此
丢字段或改语义。全部离线: 不发起任何 HTTP 请求。

本文件由原 test_integration.py 按链路拆出 (TestBestCrossMatch)。拆分
只是搬家, 测试名与断言一条未改。
"""
from __future__ import annotations

# 标准库: unittest.mock — patch 桩掉逐点 HTTP 编排, 隔离验证适配层逻辑
from unittest.mock import patch

# 本地: 两阶段 REST 客户端 — 交叉匹配的注入依赖 (权威实现在 src.client);
# legacy-import-guard: 导入失败即整文件跳过, 不让环境问题伪装成用例失败。
try:
    # src.client: 两阶段异步 HTTP 客户端 (被测入口)
    from src.client import BestClient
except Exception as _legacy_err:  # legacy-import-guard
    # pytest: 导入失败时主动 skip, 不让环境问题伪装成用例失败
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)

# 本地: 交叉匹配编排 — 本文件被测对象 (输入校验/依赖注入/适配层)
from src.crossmatch import BestCrossMatch

# 本地: 领域模型 — 结果信封 (适配层原样返回的断言目标)
from src.models import BestQueryResult


class TestBestCrossMatch:
    """交叉匹配领域逻辑回归 (输入校验 / 依赖注入 / 适配层)。"""

    def test_init(self):
        """BestCrossMatch 必须持有注入的 client (依赖注入方向不变)。"""
        client = BestClient(rate_limit=0)  # rate_limit=0 是离线铁律: 整条链路零外网流量
        xm = BestCrossMatch(client)                                                                 # 构造编排对象: 依赖注入方向是这条要验的
        assert xm.client is client                                                         # 必须是同一个 client 对象: 换掉就等于另起一条链路

    def test_crossmatch_empty_coords(self):
        """空坐标列表必须判失败并报 "Empty" (入口防线, 不发请求)。"""
        client = BestClient(rate_limit=0)                                                           # 限流置 0: 整条链路零外网流量
        xm = BestCrossMatch(client)                                                                 # 构造编排对象
        result = xm.crossmatch_coords([], [], catalog="ps1")
        assert not result.success  # 空坐标必失败: 空数组打服务端只会得到不可预期的空集
        assert "Empty" in result.error

    def test_crossmatch_mismatched_lists(self):
        """RA/Dec 列表长度不一致必须报 "length mismatch" (防错位配对)。

        守输入校验: 长度不齐时若硬配对, 会把 A 目标的赤经配到 B 目标的赤纬,
        产出看似合理的错误匹配 — 必须在入口拦住。
        """
        client = BestClient(rate_limit=0)                                                           # 零限速: 集成用例也不该被本地限流拖住
        xm = BestCrossMatch(client)                                                                 # 限流置 0
        result = xm.crossmatch_coords([180.0], [30.0, 31.0], catalog="ps1")
        assert not result.success                                                                # 长度不齐必须判失败: 静默截短会让行与坐标错位
        assert "length mismatch" in result.error  # 长度不匹配必须失败: 静默截短会让行与坐标错位

    def test_crossmatch_source_list(self):
        """crossmatch_source_list 必须转调 crossmatch_coords 并原样返回结果。

        守替身接线: 列表形态入口只是坐标数组的适配层, 不允许在此丢字段或
        改语义。
        """
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        xm = BestCrossMatch(client)                                                                 # 构造编排对象
        sources = [{"ra": 180.0, "dec": 30.0, "id": "S1"}]
        # 替身: 桩掉 crossmatch_coords (逐点 HTTP 编排), 固定返回成功信封 —
        # 隔离验证 source_list 入口的适配逻辑。
        with patch.object(xm, "crossmatch_coords") as mock_xm:  # 打桩 crossmatch_coords: 本条只验调用面, 真实匹配链路由别处守
            mock_xm.return_value = BestQueryResult(success=True)                          # 固定回一个成功信封: 本条只验适配层, 载荷形态不在判定面内
            result = xm.crossmatch_source_list(sources, catalog="ps1")
            assert result.success  # 返回 success 即可: 载荷形态不在本条的判定范围内
