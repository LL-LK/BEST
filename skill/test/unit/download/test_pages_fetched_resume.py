# -*- coding: utf-8 -*-
"""断点续传场景下 ``pages_fetched`` 语义的回归 (H3-06 / G6-F5)。

职责: 把 sidecar 的 ``query_params.pages_fetched`` 钉成"**本轮实际取到的页
数**", 而不是"循环退出时的页号"。旧实现写的是后者, 于是从第 1 页起跑时碰巧
正确, 一旦**续传起点 > 1** 就会虚报: 实翻 24 页 (3…26) 报成 26。sidecar 是人工
复核的事实源, 复核人拿它对账请求日志必然对不上, 且完全看不出发生过一次续传。

覆盖: ``src.client_paging.fetch_sqlid_data`` 的三个出口信封 (正常完成 / 首页
网络失败 / 软错误) 在 ``start_page > 1`` 时的 ``pages_fetched``。
依赖: 全离线 —— 替身 session 发的是构造出来的 CSV 文本, 零真实网络。
历史沿革: 该字段此前**没有**任何测试覆盖 (G6 实跑才在续传场景撞出来), 而既有
断点测试的起点全是 1, 所以这个 bug 一直躲着。
"""
from __future__ import annotations

# 标准库: 上下文管理器 (替身 session 用) / unittest.mock 的 patch (只打在数据面)
from contextlib import contextmanager
from unittest.mock import patch

# 第三方: pytest (参数化) + requests (网络异常类型)
import pytest
import requests

# 本地: 权威客户端 (走真实分页入口与真实解析路径) / phase-2 取数引擎 (被测函数)
from src.client import BestClient
from src.client_paging import fetch_sqlid_data

# 一页 2 行的最小 CSV: 末页判据靠"返回行数 < page_size", 行数必须真的少一点
HEADER = "ps1_ra,ps1_dec,ps1_source_id\n"  # 表头即协议层的列名认据 (ps1 带前缀)
PAGE_FULL = HEADER + "180.001,30.001,A1\n180.002,30.002,A2\n"  # 满页 (2 == page_size): 循环继续翻
PAGE_LAST = HEADER + "180.003,30.003,A3\n"                       # 不满页: 末页终止信号


class _Resp:
    """最小回包替身: 只带分页链真正读到的两个属性 (text / status_code)。"""

    def __init__(self, text: str, status: int = 200) -> None:
        """按给定正文与状态码造一个回包替身。"""
        self.text = text        # 协议层读它判软错误与解析 CSV
        self.status_code = status  # 留作人工排障线索
        self.content = text.encode("utf-8")  # 字节长度供日志/断言用

    def raise_for_status(self) -> None:
        """不抛: 失败路径由单独的用例显式构造异常, 不靠这个方法制造。"""


@contextmanager
def _paged(calls: list[int], pages: dict[int, str], total: int | None = None):
    """按请求 URL 里的 ``page=N`` 逐页发回包, 并把取过的页号记进 ``calls``。"""
    client = BestClient(rate_limit=0)  # 限流归零: 替身不占配额, 用例只关心页数语义
    client._count = lambda _sqlid: total  # 计数替身: total=None 时走"无服务端计数"分支

    def fake_get(url, **_kw):  # noqa: ANN001, ANN202 - 替身签名随 requests
        """从 URL 里取页号, 按预置表回对应正文, 并记录这次翻页。"""
        page = int(url.split("page=")[1].split("&")[0])  # 页号在查询串里: 判据就是"这一轮翻了几页"
        calls.append(page)  # 调用方据 calls 与 sidecar 的 pages_fetched 对账
        return _Resp(pages[page])

    with patch.object(client.session, "get", side_effect=fake_get):
        yield client


class TestPagesFetchedCountsPagesNotPageNumbers:
    """``pages_fetched`` = 本轮实取页数, 与末页页号不是一回事。"""

    def test_resume_from_page_three_reports_24_not_26(self):
        """G6 实跑的形态: 起点 3, 翻到 26 共 24 页, sidecar 必须报 24。"""
        pages = {p: PAGE_FULL for p in range(3, 26)}  # 3…25 满页 → 继续翻
        pages[26] = PAGE_LAST                          # 26 不满页 → 末页终止
        calls: list[int] = []
        with _paged(calls, pages) as client:
            result = fetch_sqlid_data(client, "s4997", output_format="csv", max_rows=6000,  # 实测参数: 200/页, 上限 6000
                                      page_size=2, catalog_path="ps1/q", start_page=3)  # 起点 3 = 断点续传
        assert calls[0] == 3, calls                     # 起点没被吃掉: 第一发就是断点页
        assert len(calls) == 24, calls                  # 实翻 24 页 (3…26)
        assert result.query_params["pages_fetched"] == 24, result.query_params  # 报 24, 不是末页页号 26
        assert result.query_params["pages_fetched"] != calls[-1], "报末页页号 26 在此形态下恰好像对, 但那不是本字段的语义"

    def test_fresh_run_from_page_one_is_unaffected(self):
        """起点 1 的形态: 实取页数与末页页号相同 —— 这正是旧 bug 躲这么久的原因。"""
        pages = {1: PAGE_FULL, 2: PAGE_FULL, 3: PAGE_LAST}  # 1、2 满页, 第 3 页不满即末页
        calls: list[int] = []
        with _paged(calls, pages) as client:  # 起点 1: 与续传形态的唯一差别就在起点
            result = fetch_sqlid_data(client, "s4997", output_format="csv", max_rows=6000,
                                      page_size=2, catalog_path="ps1/q")
        assert result.query_params["pages_fetched"] == 3 == calls[-1]  # 两种口径在此重合, 所以旧实现看不出错

    def test_first_page_network_failure_reports_zero(self):
        """首页即失败: 一页都没取到, 报 0 而不是页号 1 (否则"取到 1 页"是假的)。"""
        client = BestClient(rate_limit=0)  # 限流归零: 替身失败不耗配额
        client._count = lambda _sqlid: 100  # 计数替身: 服务端说有 100 行, 实际首页就断
        with patch.object(client.session, "get", side_effect=requests.RequestException("boom")):
            result = fetch_sqlid_data(client, "s4997", output_format="csv", max_rows=100,
                                      page_size=2, catalog_path="ps1/q", start_page=5)  # 起点 5: 报 5 同样是假的
        assert result.success is False                       # 首页失败即判失败 (既有语义, 本用例不放松它)
        assert result.query_params["pages_fetched"] == 0, result.query_params  # 一页都没取到就是 0

    def test_soft_error_page_is_not_counted_as_fetched(self):
        """软错误页: 请求发出去了但内容不可用, 不计入"取到的页数"。"""
        client = BestClient(rate_limit=0)  # 限流归零: 同上
        client._count = lambda _sqlid: None  # 无计数: 排除"计数分支影响页数判读"这个变量
        soft = '{"error":"Not Found"}'     # 协议层登记的软错误体之一 (SOFT_ERROR_BODIES)

        def fake_get(url, **_kw):  # noqa: ANN001, ANN202 - 替身签名随 requests
            """第 7 页给真数据, 第 8 页给软错误体, 复现"翻到一半会话死掉"。"""
            page = int(url.split("page=")[1].split("&")[0])  # 页号取自 URL
            return _Resp(PAGE_FULL if page == 7 else soft)  # 8 页起是软错误

        with patch.object(client.session, "get", side_effect=fake_get):
            result = fetch_sqlid_data(client, "s4997", output_format="csv", max_rows=6000,
                                      page_size=2, catalog_path="ps1/q", start_page=7)
        assert result.success is False                      # 软错误即判失败 (既有语义)
        assert result.query_params["pages_fetched"] == 1, result.query_params  # 只取到第 7 页, 死在第 8 页

    def test_max_rows_cap_still_reports_pages_actually_taken(self):
        """触顶停机: 报真取到的页数 (末页只取部分行也计 1 页)。"""
        pages = {1: PAGE_FULL, 2: PAGE_FULL, 3: PAGE_FULL}  # 三页都满: 停机原因是 max_rows 而非末页
        calls: list[int] = []
        with _paged(calls, pages) as client:  # 起点 1 的普通跑批形态
            result = fetch_sqlid_data(client, "s4997", output_format="csv", max_rows=5,  # 上限 5: 第 3 页取 1 行即触顶
                                      page_size=2, catalog_path="ps1/q")
        assert result.truncated is True                     # max_rows 触顶即置截断
        assert result.query_params["pages_fetched"] == 3, result.query_params  # 3 页都发出并取回了
        assert result.returned_count == 5                   # 触顶后的实得行数与页数一致
