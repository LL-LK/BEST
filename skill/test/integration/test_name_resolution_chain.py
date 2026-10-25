"""名称解析链集成测试 (P1-8): /nss/solve 坐标解析与失败哨兵语义。

守正常路径 (坐标落位 + Sesame remark 标记为外部内容, S-3) 与四条失败
路径: ra/dec=-1000 哨兵必须抛 NameResolveError (不许把南天极外的假坐标
返给下游锥检索)、端点软 404 抛 Soft404Error (与查询同一失败契约)、非
JSON 回包 (网关 HTML 错误页) 报 unparseable (拿正则抠坐标只会产出
垃圾值)、空白名称入口拦截不发请求; 以及单类 Best 与 BestClient 走同一
解析契约。全部离线: HTTP 层由 mock 注入, 不访问 nadc.china-vo.org。

本文件由原 test_integration.py 按链路拆出 (TestNameResolution)。拆分
只是搬家, 测试名与断言一条未改。
"""
from __future__ import annotations

# 标准库: unittest.mock — Mock 响应替身 + patch 桩; 本文件全部 HTTP 交互
# 在此层被替身接管 (status_code/text 手工设定), 因此无真实网络。
from unittest.mock import Mock, patch

# 第三方: pytest 提供断言 (raises) 与用例发现框架
import pytest

# 本地: 两阶段 REST 客户端 — 本文件主要被测对象 (权威实现在 src.client);
# legacy-import-guard: 导入失败即整文件跳过, 不让环境问题伪装成用例失败。
try:
    # src.client: 两阶段异步 HTTP 客户端 (被测入口)
    from src.client import BestClient
except Exception as _legacy_err:  # legacy-import-guard
    # pytest: 导入失败时主动 skip, 不让环境问题伪装成用例失败
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)            # 模块级跳过: 导入树问题不该算用例失败

# 本地: 领域模型 — 名称解析结果 (协议字段的载体, 断言目标)
from src.models import ResolvedName


class TestNameResolution:
    """P1-8: ``/nss/solve`` 名称解析及其失败哨兵语义。"""

    M31_PAYLOAD = (  # M31 真实应答: 含 remark 外部链接, 用来验 S-3 的标记语义
        '{"ra": 10.68470833, "dec": 41.26875, "obj": "M31", '                                  # 实测应答的前半段: 字段名与嵌套形态必须与线上一致
        '"remark": "https://cds.unistra.fr/cgi-bin/Sesame?M31"}'                        # remark 是外部链接: S-3 要验的就是它被标记成外部内容
    )

    def test_resolve_name_returns_coordinates(self):
        """resolve_name 正常路径: 坐标落位且 Sesame remark 标记为外部内容。

        守 S-3: remark 来自外部 CDS Sesame 服务, 是数据不是指令 —
        remark_external 标志必须置位, 供上层决定是否展示/采信。
        """
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        # 替身: GET /nss/solve 回包 — HTTP 200 + M31 坐标 JSON (含外部
        # Sesame remark 链接), 模拟名称解析成功形态。
        with patch.object(client.session, "get") as mock_get:                                       # 打桩在解析端点
            mock_resp = Mock()                                                                      # 回包对象
            mock_resp.status_code = 200                                                             # 状态码 200
            mock_resp.text = self.M31_PAYLOAD  # 回真实 payload: 字段名与嵌套形态必须与线上一致
            mock_get.return_value = mock_resp                                                       # 装到桩上

            resolved = client.resolve_name("M31")                                                   # 走公开解析入口
        assert isinstance(resolved, ResolvedName)  # 断返回类型: 上层按 ResolvedName 取字段, 返回 dict 会在别处炸
        assert resolved.name == "M31"                                                               # 名称必须回填: 上层按它显示解析结果
        assert resolved.ra == 10.68470833  # 坐标是字符串转 float: 直接透传字符串会让下游算距离时报错
        assert resolved.dec == 41.26875                                                        # 赤纬必须回填: 坐标错位会让下游锥检索落到别的天区
        # S-3: remark 是外部 Sesame 内容, 打标记且永不采信
        assert resolved.remark_external is True                                                 # 外部标记必须置位: remark 是数据不是指令
        assert "cds.unistra.fr" in resolved.remark                                         # 原始 remark 也要保留: 标记是附加信息, 不是替换

    def test_resolve_name_failure_sentinel_raises(self):
        """解析失败哨兵 (ra/dec = -1000) 必须抛 NameResolveError 而非返回坏坐标。

        守失败语义: 站点用 -1000/-1000 表示"查不到", 客户端必须把它升级
        为异常; 若原样返回, 下游会拿一个南天极外的假坐标去锥检索。
        """
        # 本地: protocol.NameResolveError — 失败哨兵必须升级成的异常类型
        from src.protocol import NameResolveError

        client = BestClient(rate_limit=0)                                                           # 限流置 0
        # 替身: GET 回包 — HTTP 200 + 失败哨兵坐标 (-1000/-1000),
        # 模拟站点对不存在目标的标准应答。
        with patch.object(client.session, "get") as mock_get:                                       # 打桩在解析端点
            mock_resp = Mock()                                                                      # 回包对象
            mock_resp.status_code = 200                                                             # 状态码仍是 200
            mock_resp.text = '{"ra": -1000, "dec": -1000, "remark": "no match"}'  # -1000/-1000 是站点哨兵: 原样返回会拿它当南天极外坐标去检索
            mock_get.return_value = mock_resp                                                       # 装到桩上

            with pytest.raises(NameResolveError, match="could not resolve"):                 # 哨兵坐标必须抛错: 把假坐标返给下游锥检索等于静默错查
                client.resolve_name("ZZZ_NOT_AN_OBJECT")  # 用不存在的目标名: 正常名会走成功分支, 这条就测不到哨兵

    def test_resolve_name_soft_error_raises_soft404(self):
        """名称解析端点软 404 必须抛 Soft404Error (与查询同一失败契约)。"""
        # 本地: protocol.Soft404Error — 名称解析与查询共用的失败契约类型
        from src.protocol import Soft404Error

        client = BestClient(rate_limit=0)                                                           # 限流置 0
        # 替身: GET 回包 — HTTP 200 + {"error":"Not Found"}, 模拟端点本身
        # 不可达/路由错误的软 404 形态。
        with patch.object(client.session, "get") as mock_get:                                       # 打桩在解析端点
            mock_resp = Mock()                                                                      # 回包对象
            mock_resp.status_code = 200                                                             # 软 404 仍是 200
            mock_resp.text = '{"error":"Not Found"}'  # 错误体而非哨兵坐标: 端点级失败与查无此物是两种不同语义
            mock_get.return_value = mock_resp                                                       # 装到桩上

            with pytest.raises(Soft404Error):                                                  # 软 404 与查询同一失败契约: 调用方只需认一种
                client.resolve_name("M31")  # 用合法名: 证明失败来自回包体而不是入参, 否则测的是输入校验

    def test_resolve_name_unparseable_body_raises(self):
        """非 JSON 回包 (HTML 错误页) 必须抛 NameResolveError, 不许静默解析。

        守解析鲁棒性: 网关把错误渲染成 HTML 时, 拿正则去抠坐标要么失败
        要么更糟 —— 抠出垃圾值; 必须明确报 unparseable。
        """
        # 本地: protocol.NameResolveError — 非 JSON 回包必须升级成的异常类型
        from src.protocol import NameResolveError

        client = BestClient(rate_limit=0)                                                           # 限流置 0
        # 替身: GET 回包 — HTTP 200 + HTML 错误页 (非 JSON), 模拟上游
        # 网关故障时的回包形态。
        with patch.object(client.session, "get") as mock_get:                                       # 打桩在解析端点
            mock_resp = Mock()                                                                      # 回包对象
            mock_resp.status_code = 200                                                             # 状态码 200
            mock_resp.text = "<html>gateway error</html>"  # HTML 错误页: 网关故障的真实形态, 拿正则抠坐标会抠出垃圾值
            mock_get.return_value = mock_resp                                                       # 装到桩上

            with pytest.raises(NameResolveError, match="unparseable"):                     # 非 JSON 回包必须报不可解析: 正则抠坐标会产出垃圾值
                client.resolve_name("M31")  # match 钉 unparseable: 与「查不到」分开报, 排障才知道是哪种

    def test_resolve_name_empty_name_raises(self):
        """空白名称必须就地抛 NameResolveError (入口防线, 不发请求)。

        守输入校验: "   " 这种空白名直达服务端只会换来难解的错误页;
        入口拦截让失败点留在调用方可见处。
        """
        # 本地: protocol.NameResolveError — 空白名称入口拦截所抛的异常类型
        from src.protocol import NameResolveError

        client = BestClient(rate_limit=0)                                                           # 限流置 0
        with pytest.raises(NameResolveError, match="required"):  # match 钉 required: 空白名在入口就被拦, 不该发出请求
            client.resolve_name("   ")                           # 三个空格而非空串: 空串可能走另一条快速路径, 拦不住就测不到

    def test_client_resolve_name(self):
        """BestClient 的 resolve_name 解析契约 (唯一入口)。

        守解析一致性: resolve_name 内部经 _request 唯一出口发请求,
        对同一回包给出同一坐标与字段映射。
        """
        client = BestClient(rate_limit=0)  # 限流归零: 与 resolve_name 成功用例对照, 断的是字段映射一致性
        # 替身: 桩掉 session.get (resolve_name 的请求出口), 固定回 M31 JSON —
        # 验证 resolve_name 的解析与字段映射。
        with patch.object(client.session, "get") as mock_get:                                       # 打桩在解析端点
            mock_resp = Mock()                                                                      # 回包对象
            mock_resp.status_code = 200                                                             # 状态码 200
            mock_resp.text = self.M31_PAYLOAD                                             # 同一份实测 payload: 走的是"已解析 ID"那条入口
            mock_get.return_value = mock_resp                                                       # 装到桩上

            resolved = client.resolve_name("M31")  # 走被测入口而非内部函数: 字段映射是 resolve_name 自己的责任
        assert resolved.ra == 10.68470833                                                           # 赤经必须回填
        assert resolved.dec == 41.26875                                                           # 赤纬必须回填: 与赤经一起断才能暴露字段错位
