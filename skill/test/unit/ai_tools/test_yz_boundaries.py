# -*- coding: utf-8 -*-
"""YZ 系列缺陷回归 (YZ-03/04/14/15/16/18/44) — 工具边界校验与信封降级。

每条守的缺陷与修法都写在用例 docstring 里。修法不在 client 层, 全部落在
``src.ai_tools`` 的工具边界 (工具层是唯一对外工具面, 协议层不替它做边界
校验, 校验必须落在这里 — 否则 schema 声明与实现脱节, 非法值原样进 URL)。

依赖: 全离线 — 客户端方法被 patch 成返回构造好的结果对象, 零真实网络。
"""
from __future__ import annotations

# 标准库: patch 只打在客户端方法上, 不碰协议层
from unittest.mock import patch

# 第三方: pytest (fixture 注入工具面; 参数化当前不用但随用例增减不必再改 import)
import pytest

# 本地: 被测工具面 / 信封错误码 / URI 段形态守卫 (守卫取信封层的**公开**名,
# 不取 ai_tools 内的私有名别名 —— 那个别名只是同模块调用点的读法)
from src.ai_tools import (
    E_INVALID_INPUT,
    MAX_FETCH_PAGE_SIZE,
    ToolBox,
    is_safe_uri_segment,
)

# 本地: 客户端与结果载体 —— 只为把工具面拼起来并造结果对象, 不参与被测逻辑
from src.client import BestClient
from src.models import BestQueryResult, ResolvedName


@pytest.fixture
def box() -> ToolBox:
    """限流归零的工具面: 本文件全离线, 用例不发请求, 留限流只会拖慢。

    原先每个用例各写一遍 ``box = _toolbox()``, 24 ���逐字相同 —— 补 24 遍行尾
    注释是制造重复注释噪音, 而逐行对照率门禁要的只是症状。fixture 一处定义、
    隐式注入, 重复本身消失。
    """
    return ToolBox(BestClient(rate_limit=0))


def _ok_result(**overrides) -> BestQueryResult:
    """造一个"客户端已判成功"的最小结果: 默认无行无数, 可被覆盖。"""
    base = dict(success=True, total_count=0, returned_count=0, sources=[])
    base.update(overrides)
    return BestQueryResult(**base)


class TestFetchPageMaxRowsCap:
    """YZ-03: ``max_rows`` 无上限时单次调用可驱动无界翻页, 必须与 schema 对齐。"""

    def test_max_rows_above_cap_is_rejected(self, box):
        """``max_rows > MAX_FETCH_PAGE_SIZE`` 必须 E_INVALID_INPUT, 不发出任何请求。"""
        with patch.object(box.client, "fetch_page") as mock_fetch:
            res = box.fetch_page(sqlid="s9999", max_rows=MAX_FETCH_PAGE_SIZE + 1)
        assert res.status["ok"] is False
        assert res.status["error_code"] == E_INVALID_INPUT
        mock_fetch.assert_not_called()  # 边界校验先于任何请求: 非法值绝不进 URL

    def test_max_rows_at_cap_is_allowed(self, box):
        """``max_rows == MAX_FETCH_PAGE_SIZE`` 是合法边界, 必须放行。"""
        with patch.object(box.client, "fetch_page", return_value=_ok_result()):
            res = box.fetch_page(sqlid="s9999", max_rows=MAX_FETCH_PAGE_SIZE)
        assert res.status["ok"] is True


class TestFetchPageMaxRowsPositive:
    """YZ-04: ``max_rows<=0`` 与非整数不能被工具边界静默接受。"""

    def test_zero_max_rows_is_rejected(self, box):
        """``max_rows=0`` 修前返回 ok=True + 0 行, 与"真的没有行"不可区分。"""
        with patch.object(box.client, "fetch_page") as mock_fetch:
            res = box.fetch_page(sqlid="s9999", max_rows=0)
        assert res.status["ok"] is False
        assert res.status["error_code"] == E_INVALID_INPUT
        mock_fetch.assert_not_called()

    def test_negative_max_rows_is_rejected(self, box):
        """负数预算同样必须拒, 不是被 int() 静默当成非法再绕回去。"""
        res = box.fetch_page(sqlid="s9999", max_rows=-5)
        assert res.status["ok"] is False
        assert res.status["error_code"] == E_INVALID_INPUT

    def test_float_max_rows_is_rejected(self, box):
        """非整数 (如 1.5) 不得被 int() 静默取整后放行。"""
        res = box.fetch_page(sqlid="s9999", max_rows=1.5)
        assert res.status["ok"] is False
        assert res.status["error_code"] == E_INVALID_INPUT

    def test_bool_max_rows_is_rejected(self, box):
        """bool 是 int 的子类, isinstance(True, int) 为真, 必须显式排掉。"""
        res = box.fetch_page(sqlid="s9999", max_rows=True)
        assert res.status["ok"] is False
        assert res.status["error_code"] == E_INVALID_INPUT


class TestCountDegradedTotal:
    """YZ-14: ``total=None`` 是计数降级, 不能与"服务端确认 0 行"压成同一信封。"""

    def test_none_total_marks_degraded(self, box):
        """上游降级 (getcount 失败/软错误) 时, status 必须显式带 degraded 位。"""
        with patch.object(box.client, "count", return_value=None):
            res = box.count("s9999")
        assert res.status["ok"] is True  # ok 契约不动: 端点本身成功回来了
        assert res.status["degraded"] is True  # 降级显式标注
        assert res.status["degraded_reason"] == "total_not_available"
        assert res.data["total"] is None  # 不调包成 0: 0 会被读成"服务端确认 0 行"

    def test_zero_total_is_not_degraded(self, box):
        """真正的 0 行不得误标降级 — 那会把"无结果"谎报成"计数不可信"。"""
        with patch.object(box.client, "count", return_value=0):
            res = box.count("s9999")
        assert res.status["ok"] is True
        assert "degraded" not in res.status  # 真 0 行不携带降级位
        assert res.data["total"] == 0

    def test_none_total_differs_from_zero_total(self, box):
        """降级与真 0 行必须是两个可区分的信封 — 这正是 YZ-14 的危害本体。"""
        with patch.object(box.client, "count", return_value=None):
            degraded = box.count("s9999")
        with patch.object(box.client, "count", return_value=0):
            zero = box.count("s9999")
        assert degraded.to_dict() != zero.to_dict(), "降级与真空压成同一信封 = 缺陷未修"
        assert degraded.provenance["data_hash"] != zero.provenance["data_hash"]


class TestStableUriSegmentValidation:
    """YZ-15: stable_uri 的拼接段过形态校验, 脏段不生成句柄 (不归一化)。"""

    def test_name_with_slash_drops_stable_uri(self, box):
        """含段分隔符的 name 若原样拼接, 会拼出歧义句柄, 必须放弃生成。"""
        with patch.object(box.client, "resolve_name") as mock_resolve:
            mock_resolve.return_value = ResolvedName(
                name="a/b", ra=1.0, dec=2.0, remark="", remark_external=False,
            )
            res = box.resolve_name("a/b")
        assert res.status["ok"] is True  # 解析本身成功
        assert res.provenance["stable_uri"] == ""  # 但引用句柄不生成, 不伪造歧义键

    def test_clean_name_keeps_stable_uri(self, box):
        """合法 name 的 stable_uri 必须保持原行为, 不被误伤。"""
        with patch.object(box.client, "resolve_name") as mock_resolve:
            mock_resolve.return_value = ResolvedName(
                name="M31", ra=10.68470833, dec=41.26875, remark="", remark_external=False,
            )
            res = box.resolve_name("M31")
        assert res.status["ok"] is True
        assert res.provenance["stable_uri"] == "best://nss/solve?obj=M31"

    def test_sqlid_stable_uri_guard_is_defense_in_depth_only(self, box):
        """``_is_safe_uri_segment`` 对 fetch_page 的 sqlid 是**第二道**防线。

        fetch_page 先过 ``normalize_sqlid`` (只认 ``s?\\d+``), 任何能走到
        ``stable_uri`` 拼接处的 sqlid 必然也过 URI 段白名单 —— 所以这条用例
        守的是"前一道没被拆掉时兜底仍生效", 而不是可达路径上的拒收。
        真正可达的拒收形态见 :class:`TestFetchPageSqlidValidation`。
        """
        with patch.object(box.client, "fetch_page", return_value=_ok_result()):
            res = box.fetch_page(sqlid="s9999")
        assert res.status["ok"] is True
        assert res.provenance["stable_uri"] == "best://sqlid/s9999?page=1&rows=1000"


class TestStableUriGuardJudgesTheEmbeddedText:
    """YZ-15 的第二半: 判据必须落在**将被拼进去的那份原文**上。

    守的是一个已修的真缺陷: 守卫曾先 strip 再判, 而调用方把原值拼进 URI —
    于是 ``"s9999\\n"`` 判过 (strip 后干净) 却把换行拼进句柄, 校验通过而
    产物带不可见分隔符。``count`` 是可达路径 (它此前不在工具边界归一)。
    """

    def test_guard_rejects_leading_or_trailing_whitespace(self):
        """首尾空白即拒: 不做"strip 后放行"那种判据/产物错位。"""
        assert is_safe_uri_segment("s9999") is True
        assert is_safe_uri_segment("s9999\n") is False
        assert is_safe_uri_segment(" s9999") is False
        assert is_safe_uri_segment("s9999 ") is False
        assert is_safe_uri_segment("   ") is False  # 纯空白段拼出来是无主段

    def test_guard_rejects_control_and_separator_chars(self):
        """控制字符与段/键分隔符同拒, 标识符常用字符放行。"""
        assert is_safe_uri_segment("ps1") is True
        assert is_safe_uri_segment("gaia_dr3_18-source.1:x") is True
        assert is_safe_uri_segment("a/b") is False  # 段分隔符: 拼出额外段
        assert is_safe_uri_segment("a?b") is False  # 查询串起始
        assert is_safe_uri_segment("a&b=c") is False  # 伪造键值对
        assert is_safe_uri_segment("a\x00b") is False  # 控制字符不可见

    def test_count_normalizes_sqlid_before_building_envelope(self, box):
        """count 归一后才建信封: 载荷/血缘/句柄三处同源, 不混原文。"""
        with patch.object(box.client, "count", return_value=0) as mock_count:
            res = box.count("s9999\n")
        assert res.status["ok"] is True
        assert mock_count.call_args.args[0] == "s9999"  # 客户端收到的是归一值
        assert res.data["sqlid"] == "s9999"  # 回显与实发请求同一份
        assert res.provenance["stable_uri"] == "best://sqlid/s9999/count"  # 句柄无不可见分隔符
        assert res.provenance["lineage"]["sqlid"] == "s9999"  # 血缘同样用归一值

    def test_count_rejects_non_whitelist_sqlid(self, box):
        """白名单外形态在工具边界就拒, 不进客户端。"""
        with patch.object(box.client, "count") as mock_count:
            res = box.count("../admin")
        assert res.status["ok"] is False
        assert res.status["error_code"] == E_INVALID_INPUT
        mock_count.assert_not_called()


class TestFetchPageSqlidValidation:
    """YZ-16: fetch_page 边界必须先过 normalize_sqlid, 不绕过协议层白名单。"""

    def test_sqlid_with_path_traversal_is_rejected(self, box):
        """``../`` 形态的脏 sqlid 修前会原样拼进 /sqlid 分页路径。"""
        with patch.object(box.client, "fetch_page") as mock_fetch:
            res = box.fetch_page(sqlid="../admin")
        assert res.status["ok"] is False
        assert res.status["error_code"] == E_INVALID_INPUT
        mock_fetch.assert_not_called()

    def test_sqlid_with_surrounding_whitespace_is_normalized(self, box):
        """``normalize_sqlid`` 去首尾空白是既有语义: 归一后合法即放行。

        归一后的值才是发请求与拼句柄的那一份 —— 原值里那点空白不会流到 URL。
        真正必须拒的是白名单外的形态, 见下一条。
        """
        with patch.object(box.client, "fetch_page", return_value=_ok_result()) as mock_fetch:
            res = box.fetch_page(sqlid="s9999\n")
        assert res.status["ok"] is True  # strip 后 s9999 合法, 这是 normalize 的既有语义
        assert mock_fetch.call_args.args[0] == "s9999"  # 归一值进客户端, 空白不流到 URL

    def test_sqlid_with_whitelist_violation_is_rejected(self, box):
        """白名单外的形态必须拒, 且在发请求之前。"""
        with patch.object(box.client, "fetch_page") as mock_fetch:
            res = box.fetch_page(sqlid="s99x99")
        assert res.status["ok"] is False
        assert res.status["error_code"] == E_INVALID_INPUT
        mock_fetch.assert_not_called()  # 边界校验先于任何请求


class TestFetchPagePageTypeStrictness:
    """YZ-18: page/page_size 必须是严格的 int, 非整数与 bool 一律拒。"""

    def test_float_page_is_rejected_not_truncated(self, box):
        """``page=1.5`` 修前被 int() 静默取整成 1 后原样进 URL。"""
        with patch.object(box.client, "fetch_page") as mock_fetch:
            res = box.fetch_page(sqlid="s9999", page=1.5)
        assert res.status["ok"] is False
        assert res.status["error_code"] == E_INVALID_INPUT
        mock_fetch.assert_not_called()

    def test_float_page_size_is_rejected_not_truncated(self, box):
        """``page_size=1.5`` 同理, 不得静默取整成 1。"""
        res = box.fetch_page(sqlid="s9999", page_size=1.5)
        assert res.status["ok"] is False
        assert res.status["error_code"] == E_INVALID_INPUT

    def test_bool_page_is_rejected(self, box):
        """``page=True`` 是 int 子类, 不排掉会被当成 1 放行。"""
        res = box.fetch_page(sqlid="s9999", page=True)
        assert res.status["ok"] is False
        assert res.status["error_code"] == E_INVALID_INPUT

    def test_bool_page_size_is_rejected(self, box):
        """``page_size=False`` 同理。"""
        res = box.fetch_page(sqlid="s9999", page_size=False)
        assert res.status["ok"] is False
        assert res.status["error_code"] == E_INVALID_INPUT

    def test_int_page_boundary_still_works(self, box):
        """合法 int 边界必须放行, 只拒不放到最后连正常翻页也用不了。"""
        with patch.object(box.client, "fetch_page", return_value=_ok_result()):
            res = box.fetch_page(sqlid="s9999", page=1, page_size=1)
        assert res.status["ok"] is True


class TestTruncatedReasonSurfaces:
    """YZ-44: truncated 布尔位之外, 成因清单必须上浮到 data.truncated_reason。"""

    def test_fetch_page_truncated_carries_reason(self, box):
        """截断时成因进 data; 布尔契约不动 (status.truncated 仍是 True)。"""
        result = _ok_result(truncated=True, returned_count=5, total_count=10)
        result.query_params["truncation_reasons"] = ["server_total_exceeds_returned"]
        with patch.object(box.client, "fetch_page", return_value=result):
            res = box.fetch_page(sqlid="s9999")
        assert res.status["truncated"] is True  # 布尔位不动
        assert res.data["truncated_reason"] == ["server_total_exceeds_returned"]  # 成因上浮

    def test_fetch_page_not_truncated_has_no_reason_key(self, box):
        """未截断时不得凭空给 truncated_reason, 免得调用方误判。"""
        with patch.object(box.client, "fetch_page", return_value=_ok_result()):
            res = box.fetch_page(sqlid="s9999")
        assert res.status["truncated"] is False
        assert "truncated_reason" not in res.data

    def test_truncated_reason_falls_back_when_upstream_missing(self, box):
        """上游没登记 truncation_reasons 时回退到泛化成因, 不让键缺位。"""
        result = _ok_result(truncated=True)  # 无 truncation_reasons
        with patch.object(box.client, "fetch_page", return_value=result):
            res = box.fetch_page(sqlid="s9999")
        assert res.status["truncated"] is True
        assert res.data["truncated_reason"] == ["max_rows_cap"]  # 泛化回退, 与 docstring 口径一致
