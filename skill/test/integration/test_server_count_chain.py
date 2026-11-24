"""服务端计数链集成测试 (P0-2): total_count 必须是服务端计数并带 truncated 标志。

P0-2 起每次查询先发一次 getcount (服务端总数) 再分页取数; 旧代码上报本地
解析行数, max_rows 截断对调用方完全不可见 — 拿到 100 条会以为总共只有
100 条。本链守主契约 (服务端 1870 / 实取 2 条必须同时呈现并标记截断)、
无截断场景不滥报、计数端点失败的诚实降级 (server_total 置 None)、计数
端点自身软 404 只降级不整体失败, 以及无服务端计数时纯客户端 max_rows
上限也必须可见。全部离线: HTTP 层由 mock 注入, 不访问 nadc.china-vo.org。

本文件由原 test_integration.py 按链路拆出 (TestServerTotalCount)。拆分
只是搬家, 测试名与断言一条未改。
"""
from __future__ import annotations

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


class TestServerTotalCount:
    """P0-2: ``total_count`` 必须是服务端计数, 并带 ``truncated`` 截断标志。

    实测锚点: 受约束的 ps1 会话上 ``getcount`` 回答 ``total=1870``;
    (旧代码上报的是本地解析行数, 于是 ``max_rows`` 截断对
    调用方完全不可见 — 拿到 100 条会以为总共只有 100 条。
    """

    CSV = "ps1_ra,ps1_dec\n180.0,30.0\n181.0,31.0\n"                                        # 两行 CSV 数据页: 服务端计数与实取条数要能拉开差距

    def _mock_getcount_then_pages(self, mock_get, count_body, csv_text=CSV, pages=None):
        """首个 GET 是 getcount (服务端计数), 后续 GET 是 CSV 数据页。"""
        # 第三方: requests — RequestException 异常类型来源 (计数端点降级断言)
        import requests as _requests

        calls = {"n": 0}                                                                            # 调用计数: 断言要数"先问了几次总数"

        # 替身 side_effect: 按 URL 是否含 getcount 分派协议阶段 — 首个 GET
        # (计数请求) 回 count_body, 后续 GET (数据页) 回 CSV; 均 HTTP 200。
        # 这模拟 P0-2 起每次查询先问服务端总数、再分页取数的请求序列。
        def side_effect(url, **_kw):  # side_effect 按 URL 分派: 一次替身要同时扮演计数端点与数据页
            """替身: 按 URL 是否含 getcount 分派协议阶段, 并累计调用次数。"""
            calls["n"] += 1                                                                         # 先累计次数
            resp = Mock()                                                                           # 回包对象
            resp.status_code = 200                                                             # 计数页与数据页都是 200: 失败要用别的方式表达
            if "getcount" in url:  # getcount 判据是 URL 关键字: 与客户端构造 URL 的方式同口径
                resp.text = count_body                                                              # 计数端点回计数体
                return resp
            resp.text = csv_text                                                                    # 数据页回 CSV
            return resp

        mock_get.side_effect = side_effect  # 挂在 mock 上而非返回值: 有状态的分派必须用 side_effect
        return calls

    def test_total_count_reports_the_server_total_and_flags_truncated(self):
        """total_count 以服务端计数为准, 且本地取数被 max_rows 截断时置 truncated。

        守 P0-2 主契约: 服务端说 1870、本地只取到 2 条, 结果信封必须同时
        呈现两个数并标记截断 — 调用方从此能区分"只有这么多"和"被限制了"。
        """
        # 第三方: requests — 与其余 getcount 降级用例保持同一导入形态
        import requests as _requests

        client = BestClient(rate_limit=0)                                                           # 限流置 0
        # 替身序列: 首个 GET (getcount) 回 {"total": 1870}, 后续数据页回 2 行 CSV
        with patch.object(client.session, "get") as mock_get:                                       # 打桩在数据面
            self._mock_getcount_then_pages(mock_get, '{"total": 1870}')  # 总数 1870 与实取 2 拉开量级: 差得越大, 误报本地行数越显眼
            result = client._fetch_sqlid_data(                                                     # 走真实分页入口: 计数与截断的编排都在这里
                "s9999", output_format="csv",                                                       # 输出格式
                max_rows=100, page_size=50, catalog_path="ps1/q",                                   # 上限与页长
            )
        assert result.success is True                                                               # 主契约: 成功标志
        assert result.total_count == 1870  # 服务端真相: 上报本地 2 行时, max_rows 截断对调用方完全不可见
        assert result.returned_count == 2                                                       # 实取条数要如实上报: 上报本地解析行数正是旧缺陷
        assert result.truncated is True                     # 1870 > 2 才置截断: 计数与实取一致时滥报截断同样是缺陷
        assert result.query_params["server_total"] == 1870  # server_total 要进 query_params: 调用方据此判断计数是真是降级

    def test_truncated_is_false_when_every_row_was_fetched(self):
        """服务端总数与本地取数一致时 truncated 必须为 False (不许滥报截断)。"""
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        # 替身序列: getcount 回 {"total": 2}, 数据页恰好 2 行 — 无截断场景
        with patch.object(client.session, "get") as mock_get:                                       # 打桩在数据面
            self._mock_getcount_then_pages(mock_get, '{"total": 2}')  # 总数与实取同为 2: 这条专门挡「永远置 True」的过实现
            result = client._fetch_sqlid_data(                                                      # 走真实分页入口
                "s9999", output_format="csv",                                                       # 输出格式
                max_rows=100, page_size=50, catalog_path="ps1/q",                                   # 上限与页长
            )
        assert result.total_count == 2                                                            # 总数就是服务端计数: 两者相等时这条才断得住
        assert result.truncated is False                                                      # 未截断不许滥报: 无截断也报截断会让调用方白白去翻页
        assert len(result.sources) == 2                                                             # 实取条数与源列表必须一致

    def test_getcount_failure_falls_back_to_the_local_count(self):
        """getcount 请求失败必须降级为本地行数 (协议阶段失败不拖垮取数)。

        守降级语义: 计数端点是优化项不是必需项; 失败时 total_count 诚实
        退化为本地解析行数, server_total 置 None, 且不得误标 truncated。
        """
        # 第三方: requests — 在替身里抛 RequestException 模拟计数端点超时
        import requests as _requests

        client = BestClient(rate_limit=0)                                                           # 限流置 0
        # 替身 side_effect: getcount URL 抛 RequestException (模拟计数端点
        # 超时), 数据页正常回 2 行 CSV — 验证降级路径。
        with patch.object(client.session, "get") as mock_get:                                       # 打桩在数据面
            def side_effect(url, **_kw):
                """替身: getcount URL 抛 RequestException, 数据页回 2 行 CSV。"""
                if "getcount" in url:                                                               # 按 URL 分派两个阶段
                    raise _requests.RequestException("count endpoint timed out")  # 在计数请求上抛: 数据页抛就测不到「计数失败不拖垮取数」
                resp = Mock()                                                                       # 回包对象
                resp.status_code = 200                                                              # 计数页也是 200
                resp.text = self.CSV                                                                # 计数端点回同一份 CSV
                return resp

            mock_get.side_effect = side_effect                                                      # 把分派函数装到桩上
            result = client._fetch_sqlid_data(                                                      # 走真实分页入口
                "s9999", output_format="csv",                                                       # 输出格式
                max_rows=100, page_size=50, catalog_path="ps1/q",                                   # 上限与页长
            )
        assert result.success is True                                                               # 主契约: 成功标志
        assert result.total_count == 2                      # 诚实的本地降级计数: 拿 2 顶替时必须同时放弃截断判断
        assert result.query_params["server_total"] is None  # server_total 置 None: 有值就说明降级时把猜测当成了服务端事实
        assert result.truncated is False                                                         # 降级后不得滥报截断: 计数未知时截断标志是猜的

    def test_soft_error_on_getcount_degrades_instead_of_failing(self):
        """getcount 自身软 404 只降级, 不把整个查询判失败。

        守粒度: 计数端点的错误 body 不应触发 phase-2 的软 404 失败路径 —
        数据页才是查询本体, 计数缺失最多损失截断可见性。
        """
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        # 替身序列: getcount 回 {"error":"Not Found"}, 数据页正常 —
        # 验证计数端点软错误被吞成降级而非整体失败。
        with patch.object(client.session, "get") as mock_get:                                       # 打桩在数据面
            self._mock_getcount_then_pages(mock_get, '{"error":"Not Found"}')  # 计数端点回错误体: 错误发生在优化项上, 不该升级成整体失败
            result = client._fetch_sqlid_data(                                                      # 走真实分页入口
                "s9999", output_format="csv",                                                       # 输出格式
                max_rows=100, page_size=50, catalog_path="ps1/q",                                   # 上限与页长
            )
        assert result.success is True  # 整查询仍成功: 粒度是「计数缺失只损失可见性」, 不是查询失败
        assert result.total_count == 2                                                              # 总数与实取条数相等
        assert result.truncated is False                                                            # 不截断时不报截断

    def test_max_rows_cap_without_server_count_marks_truncated(self):
        """无服务端计数时, max_rows 截断也必须标记 truncated (客户端上限可见)。

        守另一半截断可见性: 计数端点不可用时, "被客户端 max_rows 停住"同样
        要让调用方看见, 不能伪装成"全部数据就是这么少"。
        """
        # 第三方: requests — 在替身里抛 RequestException 模拟计数端点不可用
        import requests as _requests

        client = BestClient(rate_limit=0)                                                           # 限流置 0
        # 替身 side_effect: getcount 抛异常 (无服务端计数), 数据页回 2 行
        # CSV, max_rows=1 — 验证纯客户端上限也能置 truncated。
        with patch.object(client.session, "get") as mock_get:                                       # 打桩在数据面
            def side_effect(url, **_kw):
                """替身: getcount 抛 RequestException, 数据页回 2 行 CSV。"""
                if "getcount" in url:                                                               # 按 URL 分派两个阶段
                    raise _requests.RequestException("no count")  # 计数不可用: 与「超时」那条同构, 差别只在 max_rows=1
                resp = Mock()                                                                       # 回包对象
                resp.status_code = 200                                                              # 计数页也是 200
                resp.text = self.CSV                                                                # 计数端点回同一份 CSV
                return resp

            mock_get.side_effect = side_effect                                                      # 把分派函数装到桩上
            result = client._fetch_sqlid_data(                                                      # 走真实分页入口
                "s9999", output_format="csv",                                                       # 输出格式
                max_rows=1, page_size=50, catalog_path="ps1/q",                                     # 上限刻意给 1: 纯客户端上限也必须可见
            )
        assert result.returned_count == 1  # 实取 1 行: max_rows=1 生效的直接证据, 少一行就测不到上限
        assert result.truncated is True    # 无服务端计数也能置截断: 客户端上限同样必须让调用方看见
