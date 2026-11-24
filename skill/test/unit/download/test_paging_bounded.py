# -*- coding: utf-8 -*-
"""分页有界性与"截断诚实"的回归 (P0-04 / P0-05)。

职责: 把两件事分开钉住 —— AE5 M4 指出它们不是一件事, 只修前者等于把缺陷换形态:

1. **页数有界** (P0-04)。`while total_fetched < max_rows` 只在"每页都有可用行"时
   才收敛: 整页都是结构半行时, 半行被 ``continue`` 跳过、不占 ``max_rows`` 配额,
   而末页判据 ``len(rows) < page_size`` 数的是**含半行的原始行**, 满页照样不触发
   ⇒ ``total_fetched`` 永不推进, 循环只能等服务端给出空页/短页才停。AC1 实跑时
   假 client 被守卫强行截停在**第 61 页**, 循环自身零终止条件。对公共站点这就是
   无界请求, 违反铁律 7(b) (串行 + 强制间隔是对站点的礼仪, 无界翻页直接毁掉它)。
2. **总数不被膨胀冒名** (P0-05)。全程无去重, 服务端忽略 offset 时同一批行被反复
   累加, 而 ``total_count = max(server_total, len(all_sources))`` 会把这个膨胀后
   的本地行数当"总数"报出去 ⇒ ``total_count == returned_count``, 正是 E4 登记的
   包装形态六 ``returned_as_total``, 样本量被悄悄算大。AC1 实测膨胀 **20×** (受
   ``max_rows=1000`` 约束, 1000 行里只有 50 行唯一)。

**为什么第 2 条既不去重、也不把 ``truncated`` 掰成 True**: 按 ``*_source_id`` 去重
会删真数据 —— LEG-51 实测 ``xpsp``/``scr_lamost`` 的 source_id 本身不唯一 (1 个 id
最多 27/16 行); 按整页内容停机也不安全 —— 排序列注入只是尽力而为 (ps1 注入的排序
列线上整列为空), 无 ORDER BY 时两页重合是**文档化的可能**而非故障证据; 而"重复"
不等于"没取全", 把它报成 ``truncated`` 既语义错、又会正好凑出形态六的判据
(truncated 且 total == returned), 还会误伤 ``initial_sources`` 本就超过本次会话
计数的合法续传。所以处置是: **计数暴露出来 + 总数回到服务端这个独立证据**, 而不是
替调用方决定哪些行是重复的。

依赖: 全离线 —— 替身 session 发的是构造出来的 CSV 文本, 零真实网络。
每个用例都带 ``timeout``: 修前的失败形态是**挂死**而非断言失败, 不配超时的话
"红"会退化成"卡", 测试自己成为新的挂死源 (AC5 §4 与 AE5 攻击 A 都点了这一条)。
"""
from __future__ import annotations

# 标准库: 上下文管理器 (替身 session 用) / unittest.mock 的 patch (只打在数据面)
from contextlib import contextmanager
from unittest.mock import patch

# 第三方: pytest (timeout 标记是本文件的承重件, 见模块 docstring 末段)
import pytest

# 本地: 权威客户端 (走真实分页入口与真实解析路径) / phase-2 取数引擎 (被测函数)
# 与它的两道有界性常量 —— 断言直接引用常量而不是写死数字, 否则调阈值就会静默失去保护;
# BestSource 只用于造续传基线 (initial_sources)
from src.client import BestClient
from src.client_paging import (
    _MAX_NO_PROGRESS_PAGES,  # 停滞闸阈值: 连续多少页零可用行即停
    _MAX_PAGES_FACTOR,  # 页数上限系数: 缺省上限 = ceil(max_rows/page_size) × 本值
    fetch_sqlid_data,
)
from src.models import BestSource  # 续传基线要真源对象: 用 dict 顶替会绕开 from_row 的列名解析

HEADER = "ps1_ra,ps1_dec,ps1_source_id\n"  # 表头即协议层的列名认据 (ps1 带前缀)
ROW_OK = "180.001,30.001,A1\n180.002,30.002,A2\n"          # 两行结构完好: 都会计入 total_fetched
ROW_HALF = ",,GHOST1\n,,GHOST2\n"                           # 两行结构半行: 坐标列在而值空 ⇒ 全被跳过
PAGE_OK = HEADER + ROW_OK
PAGE_HALF = HEADER + ROW_HALF


class _Resp:
    """最小回包替身: 只带分页链真正读到的两个属性 (text / status_code)。"""

    def __init__(self, text: str, status: int = 200) -> None:
        """按给定正文与状态码造一个回包替身。"""
        self.text = text           # 协议层读它判软错误与解析 CSV
        self.status_code = status  # 留作人工排障线索
        self.content = text.encode("utf-8")

    def raise_for_status(self) -> None:
        """不抛: 失败路径由单独用例显式构造异常, 不靠这个方法制造。"""


@contextmanager
def _serving(calls: list[int], responder):
    """把 ``session.get`` 换成按 URL 页号回包的替身, 并把翻过的页号记进 ``calls``。

    ``responder(page) -> str`` 由用例给: 返回 None 表示"这一页服务端不给了",
    此时回空串走既有的"空页即末页"分支。
    """
    client = BestClient(rate_limit=0)  # 限流归零: 替身不占配额, 用例只关心页数语义

    def fake_get(url, **_kw):  # noqa: ANN001, ANN202 - 替身签名随 requests
        """从 URL 取页号, 交给 responder, 并记录这次翻页。"""
        page = int(url.split("page=")[1].split("&")[0])  # 页号在查询串里: 判据就是"翻了几页"
        calls.append(page)
        return _Resp(responder(page) or "")

    with patch.object(client.session, "get", side_effect=fake_get):
        yield client


def _with_total(client: BestClient, total: int | None) -> BestClient:
    """替换计数端点: total=None 走"无服务端计数"分支, 与真实降级路径同形。"""
    client._count = lambda _sqlid: total
    return client


class TestNoProgressPagesAreBounded:
    """P0-04: 整页结构半行时循环必须有终止条件, 不能靠服务端施舍一个空页。"""

    @pytest.mark.timeout(30)
    def test_all_half_row_pages_stop_instead_of_paging_forever(self):
        """修前红: 服务端永远给满页半行 ⇒ 旧实现无界翻页 (本用例会挂到超时)。"""
        calls: list[int] = []
        with _serving(calls, lambda _page: PAGE_HALF) as client:  # 任何页号都回同一份满页半行
            result = fetch_sqlid_data(
                _with_total(client, None), "s4997", output_format="csv",
                max_rows=100, page_size=2, catalog_path="ps1/q",
            )
        assert len(calls) == _MAX_NO_PROGRESS_PAGES, calls  # 停在停滞闸上, 不是停在服务端给的空页上
        assert result.truncated is True, result.query_params  # 主动收手 = 没取全, 不许报完整
        assert result.query_params["bound_stop_reason"] == "no_progress_pages", result.query_params
        assert "no_progress_pages" in result.query_params["truncation_reasons"]
        assert result.returned_count == 0  # 半行一行都没入库: 停滞不是因为"取满了"

    @pytest.mark.timeout(30)
    def test_sparse_pages_are_not_mistaken_for_stall(self):
        """反向对照: 每页出一行可用数据就不算停滞, 不能被停滞闸误伤。"""
        pages = {1: HEADER + "180.001,30.001,A1\n,,GHOST\n",   # 1 可用 + 1 半行 = 满页, 末页判据不触发
                 2: HEADER + "180.002,30.002,A2\n,,GHOST\n",
                 3: HEADER + "180.003,30.003,A3\n"}             # 短页 = 正常末页信号
        calls: list[int] = []
        with _serving(calls, pages.get) as client:
            result = fetch_sqlid_data(
                _with_total(client, 3), "s4997", output_format="csv",
                max_rows=100, page_size=2, catalog_path="ps1/q",
            )
        assert len(calls) == 3, calls                       # 一直翻到真末页, 没被停滞闸提前掐断
        assert result.query_params["bound_stop_reason"] == "", result.query_params
        assert result.truncated is False, result.query_params  # 3 行全取到 = 真的完整
        assert result.returned_count == 3
        assert result.query_params["skipped_malformed_rows"] == 2  # 两个半行仍如实计数, 不是静默丢


class TestPageCeilingIsBounded:
    """P0-04 的第二道闸: 每页只出一行时"有进展但极慢", 只有绝对页数上限兜得住。"""

    @pytest.mark.timeout(30)
    def test_explicit_max_pages_stops_the_loop(self):
        """显式 max_pages 必须真的生效, 而不是只写进 query_params 当装饰。"""
        def slow(page: int) -> str:
            """每页回 1 行可用 + 1 行半行: 有进展 ⇒ 停滞闸不触发, 只有页数上限兜得住。"""
            return HEADER + f"180.00{page},30.00{page},A{page}\n,,GHOST\n"

        calls: list[int] = []
        with _serving(calls, slow) as client:
            result = fetch_sqlid_data(
                _with_total(client, None), "s4997", output_format="csv",
                max_rows=10000, page_size=2, max_pages=5, catalog_path="ps1/q",
            )
        assert len(calls) == 5, calls                        # 停在给的页数上限上
        assert result.query_params["page_ceiling"] == 5, result.query_params
        assert result.query_params["bound_stop_reason"] == "page_ceiling_reached", result.query_params
        assert result.truncated is True, result.query_params  # 撞闸 = 没取全
        assert result.returned_count == 5                    # 5 页各 1 行可用

    def test_default_ceiling_derives_from_max_rows_and_page_size(self):
        """缺省上限 = ceil(max_rows/page_size) × 系数; 不给系数就没法判"停在哪算撞闸"。"""
        calls: list[int] = []
        with _serving(calls, lambda _p: HEADER + "180.001,30.001,A1\n") as client:
            result = fetch_sqlid_data(
                _with_total(client, None), "s4997", output_format="csv",
                max_rows=100, page_size=2, catalog_path="ps1/q",
            )
        assert result.query_params["page_ceiling"] == (100 // 2) * _MAX_PAGES_FACTOR, result.query_params

    def test_ceiling_survives_page_size_zero_without_crashing(self):
        """page_size=0 时算上限会除零: 上限推导必须先把它夹到 >=1。"""
        calls: list[int] = []
        with _serving(calls, lambda _p: "") as client:  # 空页即末页: 本用例只验上限算得出来
            result = fetch_sqlid_data(
                _with_total(client, None), "s4997", output_format="csv",
                max_rows=100, page_size=0, catalog_path="ps1/q",
            )
        assert result.query_params["page_ceiling"] == 100 * _MAX_PAGES_FACTOR, result.query_params


class TestDuplicatePagesDoNotInflateTotal:
    """P0-05: 重复页把行数抬上去之后, 不许把膨胀后的行数当"总数"报出去。"""

    @pytest.mark.timeout(30)
    def test_inflated_rows_do_not_get_reported_as_the_total(self):
        """修前红: 服务端总数 2、落地 6 行, 旧实现报 ``total_count = max(2, 6) = 6``。

        "总数 == 返回数"正是 E4 登记的包装形态六 ``returned_as_total``
        (``evals/robustness/graders.py:274-276``): 样本量被悄悄算大, 下游按它
        算密度/比例全错。修法**不是**把 ``truncated`` 掰成 True —— 重复不等于
        "没取全", 而且续传时 ``initial_sources`` 本就可能让本地行数超过本次会话
        的服务端计数, 那样会误伤合法续传; 掰成 True 还会正好凑出形态六的判据
        (truncated 且 total == returned)。所以这里让 ``total_count`` 回到唯一的
        独立证据 —— 服务端计数, 使 ``total < returned`` 的矛盾**暴露**出来。
        """
        calls: list[int] = []
        with _serving(calls, lambda _page: PAGE_OK) as client:  # 每页都回同一份 2 行 = 服务端忽略 offset
            result = fetch_sqlid_data(
                _with_total(client, 2), "s4997", output_format="csv",
                max_rows=6, page_size=2, catalog_path="ps1/q",
            )
        assert result.query_params["duplicate_pages"] == 2, result.query_params  # 后两页是重放, 如实报出来
        assert result.returned_count == 6                      # 不去重: 不替调用方决定哪几行是重复的
        assert result.total_count == 2, result.query_params     # 总数取服务端值, 不取被膨胀的本地行数
        assert not (result.truncated and result.total_count == result.returned_count), (
            "包装形态六: truncated 与「总数 == 返回数」不得同现"
        )

    @pytest.mark.timeout(30)
    def test_overlapping_but_distinct_pages_are_not_flagged(self):
        """反向对照: 两页只有一行重合 (线上实测形态) 不算重放, 一行都不许丢。"""
        pages = {1: HEADER + "180.001,30.001,A1\n180.002,30.002,A2\n",   # A1 A2
                 2: HEADER + "180.002,30.002,A2\n180.003,30.003,A3\n",   # A2 A3 —— 与上页重合一行
                 3: HEADER + "180.004,30.004,A4\n"}                      # 短页 = 末页
        calls: list[int] = []
        with _serving(calls, pages.get) as client:
            result = fetch_sqlid_data(
                _with_total(client, 5), "s4997", output_format="csv",
                max_rows=100, page_size=2, catalog_path="ps1/q",
            )
        assert result.query_params["duplicate_pages"] == 0, result.query_params  # 内容不同就不是重放
        assert result.returned_count == 5, result.sources     # 5 行全留: 重合的那行没被当重复删掉
        assert result.total_count == 5                        # 无重放时仍走 max() 口径, 不被新分支改写
        assert result.truncated is False, result.query_params
        assert result.query_params["bound_stop_reason"] == ""

    @pytest.mark.timeout(30)
    def test_resume_with_more_rows_than_session_count_is_not_treated_as_duplicate(self):
        """反向对照: 续传叠加让本地行数超过本次会话计数是**合法**的, 不许改 total_count。

        这条钉住新分支的触发条件里 ``duplicate_pages`` 那一半是承重的 —— 只看
        "本地行数 > 服务端计数" 会把正常续传误判成重放。
        """
        prior = [BestSource.from_row({"ps1_ra": "1.0", "ps1_dec": "2.0", "ps1_source_id": "P1"}, catalog="ps1"),
                 BestSource.from_row({"ps1_ra": "1.1", "ps1_dec": "2.1", "ps1_source_id": "P2"}, catalog="ps1")]
        calls: list[int] = []
        with _serving(calls, lambda _p: HEADER + "180.009,30.009,A9\n") as client:  # 短页即末页, 只翻一页
            result = fetch_sqlid_data(
                _with_total(client, 2), "s4997", output_format="csv", max_rows=100,
                page_size=2, catalog_path="ps1/q", start_page=4, initial_sources=prior,
            )
        assert result.query_params["duplicate_pages"] == 0, result.query_params
        assert result.returned_count == 3                     # 2 行续传基线 + 1 行本轮
        assert result.total_count == 3                        # 走 max(2, 3): 续传叠加, 不是重放
        assert result.query_params["pages_fetched"] == 1      # 本轮只实取 1 页 (H3-06 口径, 不被本波改动)
