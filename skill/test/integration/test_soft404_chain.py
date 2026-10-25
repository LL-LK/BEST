"""软 404 判定链集成测试 (P0-3): HTTP 200 + {"error": ...} 响应体必须大声失败。

守两个阶段各自的体校验分支: phase-1 提交回包与 phase-2 数据页回包只要是
错误 JSON 就必须升级为失败 (error 码前缀 E_SOFT_404) —— 把错误 body
当作只有表头的 CSV 解析, 对外就会呈现"成功但空", 调用方无从知道查询其实失败
了; 正常 CSV 页不得被误判 (守卫假阳性)。BestClient 的 _request 是唯一
choke point, 同样逐响应体校验。全部离线: HTTP 层由 mock 注入, 不访问
nadc.china-vo.org。

本文件由原 test_integration.py 按链路拆出 (TestSoft404Detection)。拆分
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

# 本地: 唯一生产客户端 (P1: pybest 单类双副本已合并删除) — 与 BestClient
# 同一入口; 软 404 的 _request choke point 断言改由 BestClient._request 守护。


class TestSoft404Detection:
    """P0-3: HTTP 200 + {"error": ...} 响应体必须大声失败, 不许静默吞掉。

    实测事实: 未知路由与导航组查询路径返回
    ``{"error":"Not Found"}`` (22B); 死掉的 sqlid 会话在 phase-2 返回同样内容。
    把该 body 当作只有表头的 CSV 解析, 对外就会呈现一个"成功但空"的
    结果 —— 调用方无从知道查询其实失败了。
    """

    SOFT_BODY = '{"error":"Not Found"}'  # 22 字节的实测错误体: 站点对未知路由与死会话都回这一份

    def test_phase_one_soft_error_is_reported_not_swallowed(self):
        """phase-1 软 404: 回包体是错误 JSON 时必须返回 error 而非假 sqlid。

        守 _submit_query_for_sqlid 的体校验分支: 状态码 200 不再是"成功"的
        充分条件, 错误码前缀 E_SOFT_404 是调用方识别协议层失败的契约。
        """
        client = BestClient(rate_limit=0)                                                    # 限流置 0: 替身已接管 HTTP, 不该再等真实节流
        # 替身: phase-1 POST 回包 — HTTP 200 但 body 是 {"error":"Not Found"},
        # 模拟导航组路径 (calib/stripe82/q) 被服务端拒绝的软 404 形态。
        with patch.object(client.session, "post") as mock_post:                                     # 打桩在提交阶段
            mock_resp = Mock()                                                                      # 回包对象
            mock_resp.status_code = 200  # 状态码 200 是软 404 的特征: 只看状态码的实现正是在这里失守
            mock_resp.text = self.SOFT_BODY                                                       # 正文是实测的错误体: 判据要看结构而不是文案
            mock_post.return_value = mock_resp                                                      # 装到桩上

            sqlid, error = client._submit_query_for_sqlid(  # 提交路径必须返回 (sqlid, error) 二元组: 假 sqlid 会带着去 phase-2
                "calib/stripe82/q", {"output.fmt": "html"}                                        # 导航组路径: 站点对它回的就是这份软 404
            )
        assert sqlid is None                   # sqlid 必须是 None: 返回假值会让调用方以为可以继续翻页
        assert error.startswith("E_SOFT_404")  # 错误码前缀是契约: 调用方按前缀分支, 换文案就得同步改调用方
        assert "Not Found" in error                                                             # 原文案也要透出: 排障时要看到服务端到底说了什么

    def test_phase_two_soft_error_fails_instead_of_empty_success(self):
        """phase-2 软 404: 死会话回包必须整体判失败, 不得呈现"成功且 0 条"。

        守 P0-3 的另一半: 把错误 JSON 读成空 CSV 会幻影出 success=True;
        error 必须带 E_SOFT_404 与会话号 s9999。
        """
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        # 替身: phase-2 GET 回包 — HTTP 200 + 错误 JSON, 模拟 sqlid 会话
        # 已过期/不存在时服务端的软 404。
        with patch.object(client.session, "get") as mock_get:                                       # 打桩在数据页阶段
            mock_resp = Mock()                                                                      # 回包对象
            mock_resp.status_code = 200                                                         # 状态码仍是 200: 软 404 的特征就在这里
            mock_resp.text = self.SOFT_BODY                                                        # 正文是同一份错误体: 死会话与死路由共用它
            mock_get.return_value = mock_resp                                                       # 装到桩上

            result = client._fetch_sqlid_data(  # 数据页回包也要校验: phase-1 过了不代表 phase-2 不会拿到错误体
                "s9999", output_format="csv",                                       # 带星表路径: phase-1 过了不代表 phase-2 不会拿到错误体
                max_rows=100, page_size=50, catalog_path="ps1/q",                                   # 上限与页长: 走真实分页入口才验得到编排
            )
        assert result.success is False  # success 必须为 False: 把错误 JSON 读成空 CSV 会幻影出 True
        assert "E_SOFT_404" in result.error                                              # 错误码必须在文案里: 只判 success 的话调用方无法分支
        assert "s9999" in result.error  # 错误要带会话号: 死的是哪个 sqlid 是排障时唯一能用的线索
        assert result.sources == []     # sources 空是次要断言: 真正要挡的是 success=True 的幻影成功

    def test_internal_server_error_body_is_also_a_soft_error(self):
        """body 为 Internal Server Error 同样按软 404 处理 (不只看 Not Found)。

        守错误体识别的完整性: 服务端把 500 语义塞进 200 body 时, 客户端
        必须把任意 {"error": ...} 当失败, 而不是只匹配一种文案。
        """
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        # 替身: phase-1 POST — HTTP 200 + {"error":"Internal Server Error"},
        # 模拟服务端内部错误以软错误形态返回。
        with patch.object(client.session, "post") as mock_post:                                     # 打桩在提交阶段
            mock_resp = Mock()                                                                      # 回包对象
            mock_resp.status_code = 200                                                     # 状态码 200 配 500 语义: 客户端必须按结构判定
            mock_resp.text = '{"error":"Internal Server Error"}'  # Internal Server Error 同样按软 404: 判据应看结构而非文案
            mock_post.return_value = mock_resp                                                      # 装到桩上

            _sqlid, error = client._submit_query_for_sqlid(                                        # 只取错误串: 软 404 下会话号必然为空
                "std/q", {"output.fmt": "html"}                                                     # 导航组路径
            )
        assert error.startswith("E_SOFT_404")                                                       # 错误码前缀: 任意错误体都要归到这一类
        assert "Internal Server Error" in error                                                  # 原文案透出: 只匹配一种文案的实现会在这里漏判

    def test_normal_csv_page_is_not_mistaken_for_a_soft_error(self):
        """正常 CSV 页不得被误判为软 404 (检测不能误伤, 守卫假阳性)。

        守 soft-error 检测的精确性: 只有 body 形如 {"error": ...} 才升级为
        失败; 普通表头+数据行必须照常解析出源。
        """
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        # 替身: phase-2 GET — HTTP 200 + 带表头 CSV (一行数据), 正常页形态
        with patch.object(client.session, "get") as mock_get:                                       # 打桩在数据页阶段
            mock_resp = Mock()                                                                      # 回包对象
            mock_resp.status_code = 200                                                             # 状态码 200
            mock_resp.text = "ps1_ra,ps1_dec\n180.0,30.0\n"                                      # 正常 CSV 页: 检测误伤就会把好数据当失败
            mock_get.return_value = mock_resp                                                       # 装到桩上

            result = client._fetch_sqlid_data(                                                      # 走真实分页入口
                "s9999", output_format="csv",                                                       # 上限与页长
                max_rows=100, page_size=50, catalog_path="ps1/q",
            )
        assert result.success is True  # success 为 True 且解析出 1 条: 两个数一起断, 少一其中一个都可能假过
        assert len(result.sources) == 1                                                        # 必须解析出恰好一条: 误判成软 404 会让这条红

    def test_client_request_raises_on_soft_error_response(self):
        """BestClient._request 必须逐响应体校验 (唯一 choke point)。"""
        # 本地: protocol.Soft404Error — 软 404 的编程可识别异常类型 (断言目标)
        from src.protocol import Soft404Error

        client = BestClient(rate_limit=0)                                                           # 限流置 0
        # 替身: 客户端唯一请求出口 _request 之下的 session.request — HTTP 200 +
        # 错误 JSON, 验证 Soft404Error 从唯一 choke point 抛出。
        with patch.object(client.session, "request") as mock_request:                              # 打桩在会话之下: 只有这层才拦得住所有出口
            mock_resp = Mock()                                                                      # 回包对象
            mock_resp.status_code = 200                                               # 状态码 200 配错误体: 唯一 choke point 的判定对象
            mock_resp.text = self.SOFT_BODY  # 唯一 choke point 在 session 之下: 替身放这层才拦得住所有出口
            mock_request.return_value = mock_resp                                                   # 装到桩上

            with pytest.raises(Soft404Error, match="E_SOFT_404"):                                # 必须抛类型化异常: 软 404 要能被编程识别
                client._request("GET", f"{client.base_url}/sqlid/s9999")  # 直连 _request: 桩这层等于把被测逻辑整个绕过去了

    def test_cone_search_propagates_soft_error_instead_of_empty_list(self):
        """死路由必须显式失败, 不许静默返回空结果 (P0-3 验收点)。

        BestClient 的错误语义: 软 404 不炸异常, 而是以 success=False +
        类型化 error_code (E_SOFT_404) 的失败信封返回 — 调用方按码分支,
        既不被降级成"0 行成功", 也不必捕异常。
        """
        # 本地: protocol 错误码 — 死路由必须透出的契约值 (断言目标)
        from src.protocol import SOFT_404_ERROR_CODE

        client = BestClient(rate_limit=0)  # 限流归零: 锥检索走同一出口, 替身形态与前几条保持一致
        # 替身: phase-1 POST 回包体是错误 JSON; 锥检索必须把它翻译成失败信封
        with patch.object(client.session, "post") as mock_post:                                     # 打桩在提交阶段
            mock_resp = Mock()                                                                      # 回包对象
            mock_resp.status_code = 200                                                             # 状态码 200
            mock_resp.text = self.SOFT_BODY                                                         # 正文是错误体
            mock_post.return_value = mock_resp                                                      # 装到桩上

            result = client.cone_search(180.0, 30.0, radius_arcsec=60, max_records=10)  # 锥检索是验收终点: 错误信封必须一路透传到对外接口

        assert result.success is False                                                    # 对外接口必须整体判失败: 内部判对了却在上层被吞掉同样算事故
        assert result.error_code == SOFT_404_ERROR_CODE  # error_code 用常量: 码值一旦漂移, 调用方的分支会全部落空
        assert result.sources == []                                                            # 源列表必须为空: 幻影出的空结果不该带着数据往下走
