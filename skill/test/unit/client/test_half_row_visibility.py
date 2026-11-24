# -*- coding: utf-8 -*-
"""A2-01 / A7-04 守门: 行级损失必须在信封里可见, 连通性探测必须看软错误体。

复过的现 (A2-01): 末行被传输拦腰截断 (半行) 时, 协议层只发
``logger.warning`` 就把该行丢掉, ``truncated_rows`` 既不进 ``truncated``
也不进 ``skipped_malformed_rows`` —— 实测同一回包 2 行、末行 2/3 字段时
信封是 ``success=True returned=1 total=1 truncated=False``, 与"服务端就
只有 1 行"完全同形, 丢行对调用方不可见。getcount 不可用是线上可达分支,
所以"服务端计数兜底"并不成立。

复过的现 (A7-04): ``check_connection`` 只判 ``status_code == 200``, 而
BEST 的软 404 恰是 HTTP 200 + ``{"error":"Not Found"}``; 客户端其余每条
路径都调 ``is_soft_error()``, 唯独它没有 —— CLI info/doctor 判"站点可达"
的唯一依据, 故障会被读成健康。

全部离线: session.get 被替身接管, 不打真实站点。
"""
from __future__ import annotations

# 标准库: 响应替身 (Mock 骨架) / 测试发现
from unittest.mock import Mock

# 第三方: pytest (测试发现) / requests (网络异常类: getcount 不可用要走真实异常形态)
import pytest  # 测试发现: 本文件用例均为离线
import requests  # 端点故障的异常类型, 客户端只捕这一类

# 本地: 两阶段客户端 (被测对象) 与软错误判据 (A7-04 的协作件)
from src.client import BestClient
from src.protocol import is_soft_error

HEADER = "ps1_source_id,ps1_ra,ps1_dec,ps1_rpsf\n"  # 四列表头: 半行按"少于表头宽"判定
FULL_ROW = "S1,180.0001,30.0001,18.2\n"               # 完整行: 对照组与半行样本共用
HALF_ROW = "S2,180.0002,30.0002\n"                    # 传输截断的末行: 只有 3/4 字段
STRUCT_HALF = "S2,180.0002,,19.1\n"                   # 结构半行: 四字段齐全但赤纬为空


def _client(body: str) -> BestClient:
    """构造只回固定正文的客户端 (getcount 一律失败, 模拟线上可达分支)。

    ``getcount`` 失败时 ``server_total`` 为 None, 于是"服务端计数大于实收"
    这条截断依据也不存在 —— 正是丢行最容易被包装成成功的组合。
    """
    client = BestClient(rate_limit=0)  # 限流归零: 本组用例只验信封, 不该被真实 sleep 拖慢

    def fake_get(url, **kwargs):
        """替身 session.get: 靠 URL 关键字把计数页与数据页分流。"""
        resp = Mock()                                              # 回包对象
        resp.status_code = 200                                     # 状态码先置真: 让 raise_for_status 走真路径
        if "getcount" in url:                                      # 计数页: 模拟端点不可用
            resp.raise_for_status.side_effect = requests.RequestException("count endpoint down")  # 客户端只捕 RequestException, 故用真类型
            resp.text = ""
        else:                                                      # 数据页: 回给定正文
            resp.text = body
        return resp

    client.session.get = fake_get  # 离线守门: 替身装在真实 session 上, 走真实分页入口
    return client


def _fetch(body: str, **kwargs):
    """跑一次真实分页入口并返回信封 (委派壳 + client_paging 两层都在这条路上)。"""
    client = _client(body)  # 先造替身客户端
    return client._fetch_sqlid_data("s9001", catalog_path="ps1/q", max_rows=kwargs.pop("max_rows", 1000), **kwargs)


class TestTransportHalfRowIsVisible:
    """A2-01: 传输半行的丢弃数必须能对账, 且不能报成"已取全"。"""

    def test_dropped_half_row_shows_up_in_the_envelope(self):
        """末行半行 → 返回 1 行但丢 1 行的事实必须在信封里看得见。"""
        result = _fetch(HEADER + FULL_ROW + HALF_ROW)  # 两行回包, 末行 3/4 字段

        assert result.success is True, "半行丢弃不等于查询失败: 成功取到的那部分照常给"
        assert result.returned_count == 1, "半行不入库: 返回行数必须诚实"
        params = result.query_params
        assert params["skipped_malformed_rows"] == 1, "丢了 1 行必须报 1: 调用方按 returned + skipped 对账"
        breakdown = params["skipped_malformed_breakdown"]
        assert breakdown["truncated_transport_rows"] == 1, "细分计数必须指出这是传输截断而非结构问题"
        assert breakdown["malformed_coordinates"] == 0, "结构半行与传输半行是两回事, 不许混报"
        assert result.truncated is True, "少收了一行还报 truncated=False 等于把数据事故包装成成功"
        assert "transport_half_row_dropped" in params["truncation_reasons"], \
            f"截断来源必须可判定, 实际: {params['truncation_reasons']!r}"

    def test_complete_page_reports_no_loss(self):
        """对照组: 两行完整 → 零丢弃、零截断原因 (不许把干净回包也报成截断)。"""
        result = _fetch(HEADER + FULL_ROW + "S2,180.0002,30.0002,19.1\n")  # 同样两行, 末行完整

        assert result.returned_count == 2, "完整回包两行都该入库"
        assert result.query_params["skipped_malformed_rows"] == 0, "干净回包不许虚报丢行"
        assert result.query_params["truncation_reasons"] == [], \
            f"干净回包不该有截断原因, 实际: {result.query_params['truncation_reasons']!r}"
        assert result.truncated is False, "取全了就说取全了"

    def test_structural_and_transport_losses_are_counted_apart(self):
        """结构半行 + 传输半行同页出现 → 两类各记 1, 合计 2。"""
        result = _fetch(HEADER + FULL_ROW + STRUCT_HALF + HALF_ROW)  # 中间行缺赤纬, 末行被截断

        breakdown = result.query_params["skipped_malformed_breakdown"]
        assert breakdown == {"malformed_coordinates": 1, "truncated_transport_rows": 1}, \
            f"两类丢行必须分开记账, 实际: {breakdown!r}"
        assert result.query_params["skipped_malformed_rows"] == 2, "合计数 = 各类之和: 调用方按总数对账"
        assert [s.source_id for s in result.sources] == ["S1"], "只有完整行入库: 两种半行都不得补空当合法行"

    def test_max_rows_cap_is_distinguishable_from_half_row_loss(self):
        """触顶截断与半行丢失必须能被区分 —— 布尔位不得背两种含义。"""
        result = _fetch(HEADER + FULL_ROW + "S2,180.0002,30.0002,19.1\n", max_rows=1)  # 客户端主动停在 1 行

        assert result.truncated is True, "触顶即未取全"
        reasons = result.query_params["truncation_reasons"]
        assert "max_rows_cap" in reasons, f"触顶来源必须可判定, 实际: {reasons!r}"
        assert "transport_half_row_dropped" not in reasons, "触顶与半行丢失是两回事, 不许互相顶包"


class TestCheckConnectionReadsSoftErrors:
    """A7-04: 200 不等于可达, 软错误体同样是"站点在说不行"。"""

    @pytest.mark.parametrize("body", ['{"error":"Not Found"}', '{"error":"Internal Server Error"}', '{"error": "any soft failure"}'])
    def test_soft_error_body_is_unreachable(self, body):
        """HTTP 200 + 软错误体 → check_connection 必须 False。"""
        client = BestClient(rate_limit=0)
        resp = Mock()                       # 回包替身
        resp.status_code = 200              # 状态码故意置真: 只验软错误体这一层
        resp.text = body
        client.session.get = lambda url, **kwargs: resp  # 离线替身

        assert is_soft_error(body), "前置: 这段正文必须先被认成软错误体 (判据本身要钉住)"
        assert client.check_connection() is False, "站点在说 200+软错误体, 报成可达就是故障被读成健康"

    def test_real_home_page_is_reachable(self):
        """反向守门: 真正的首页正文不得被误判成不可达。"""
        client = BestClient(rate_limit=0)
        resp = Mock()                                    # 回包替身
        resp.status_code = 200                           # 正常 200
        resp.text = "<html><title>BEST</title></html>"  # 正常首页 HTML
        client.session.get = lambda url, **kwargs: resp  # 离线替身

        assert client.check_connection() is True, "别把补一层软错误判据变成恒假的空转实现"
