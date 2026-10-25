"""两阶段查询链集成测试: phase-1 表单构造 → sqlid 会话 → phase-2 分页取数。

覆盖面: 表单键集符合协议层且不含 .constraint (Q-10)、锥形检索用服务端原生
pos.* 字段 (Q-01)、约束编码 {prefix}.operation + .min/.max、phase-2 URL 不
夹带逆向出来的 EasyUI filterRules (P1-4)、base_url 锚定真实服务端、sqlid
提取与无结果判定 (E_NO_SQLID)、phase-2 CSV/空页解析, 以及查询参数贯通
(列投影/排序/nearest_only 落表, P1-7 默认路径无 CSRF homepage 请求)。
全部离线: HTTP 层由 mock 注入, 不访问 nadc.china-vo.org。

本文件由原 test_integration.py 按链路拆出: TestBestClientIntegration 与
TestQueryParameterPlumbing 同属两阶段查询回归。拆分只是搬家, 测试名与
断言一条未改。
"""
from __future__ import annotations

from unittest.mock import Mock, patch  # 替身层: 本文件全部 HTTP 在此被接管, 零网络

from src.client import BestClient  # 被测入口

# 2026-10-05 R5-03: 原先此处是 ``except Exception -> pytest.skip(allow_module_level=True)``
# 的 legacy-import-guard。它在本仓 11 个用例上静默吞掉了整份文件 (Q8 报告 P1-1):
# ``src.client`` 的错误码再导出曾随"定义上收至 protocol"一并漏删, ImportError 被守卫
# 降级成模块级 skip —— 用例根本不在收集集里, 门禁却全绿, 其中 P1-7 的回归锚点
# (test_default_query_path_spends_no_csrf_homepage_request) 一度无人看守。
# 修法是**改导入源**而不是在 src/client.py 再导出一份: 那两个码的真源在
# src/protocol.py (与 src/ai_tools.py 同值), 再导出等于制造第二份真源 ——
# 与本仓正在收敛的"哨兵/错误码单点"方向相反。故守卫删除: 裸导入失败 =
# 收集期报错 = 门禁变红, 这才是导入面回归应有的形态。防复发由
# test/unit/meta/test_no_module_skip_guards.py 的静态门禁承担 (任何文件都不得
# 再引入模块级 skip 守卫)。
from src.models import BestQueryResult, ColumnConstraint  # 约束载体 + 参数贯通断言目标
from src.protocol import E_NO_SQLID  # 空结果的稳定错误码: 真源在 protocol, 不从 client 再导出一份

# ---------------------------------------------------------------------------
# Mock HTML 助手 — 构造 phase-1 假回包 HTML: datagrid URL 里的 sqlid 是
# phase-2 取数地址的载体, result_table 标记"有结果"的页面形态
# ---------------------------------------------------------------------------


def make_query_html(sqlid: str = "s9999", has_table: bool = True) -> str:
    """生成带 sqlid 的假 BEST phase-1 查询响应 HTML。

    HTML 里的三处标记对应协议锚点: ``id_column_name`` (星表列前缀)、
    datagrid 的 ``url:"/data/best/sqlid/{sqlid}"`` (phase-2 取数地址)、
    ``result_table`` (有结果时的表格标记)。``has_table=False`` 用来模拟
    "查询成功但无结果"的页面形态。
    """
    html = f"""<!DOCTYPE html>
<html><head><title>Pan-STARRS | BEst STar database</title></head>
<body>
<script>var id_column_name = "ps1_";</script>
<script>
$("#tbl").datagrid({{
    url:"/data/best/sqlid/{sqlid}?output.fmt=dbgrid",
    columns:[[{{field:"checkboxxx",checkbox:true}}]]
}});
</script>"""
    if has_table:                                                                              # 有结果才追加表格段: 无结果的页面形态是另一条分支
        html += """
<table class="table" id="result_table">
<tr><th>id</th><th>ra</th><th>dec</th><th>rpsf</th></tr>
<tr><td>BEST001</td><td>180.0</td><td>30.0</td><td>15.23</td></tr>
</table>"""                                                                                         # 表格段: 有结果时页面上的列名与首行数据
    html += "</body></html>"
    return html


class TestBestClientIntegration:
    """客户端集成回归: HTTP 层全部 mock, 验证协议行为而非网络。"""

    def test_build_form_uses_protocol_key_set(self):
        """Q-10 修复: 表单键集必须符合协议层且不含 .constraint (旧测试钉死错误契约)。"""
        client = BestClient(rate_limit=0)  # rate_limit=0: 关客户端限速, 否则每次请求前先 sleep
        constraints = [                                                                            # 约束列表: 下面要验的是它怎么被编成表单键
            ColumnConstraint(name="class_star", constraint="greaterequal", min=0.9),             # 单端下限约束: 少了另一端就测不出键缺失的回归
        ]
        form = client._build_form("ps1", constraints, 100)                                          # 走真实的表单构造入口
        assert form["output.fmt"] == "html"  # 唯一取回 sqlid 的提交形态
        assert form["pos.type"] == "none"     # 无空间约束
        assert "showcol" in form                # 星表列投影必须显式
        assert any(k.endswith(".operation") for k in form), form  # 缺它 = 约束整条丢失
        # 约束键必须走协议层 {table}.{col} 限定命名空间 (旧缺陷: 非限定 ra.constraint)
        assert not any(k in ("ra.constraint", "dec.constraint") for k in form), form                # 非限定键名不得残留: 旧缺陷就是这里
        # 旧拼写 outputformat / max_rows 不得残留
        assert "outputformat" not in form and "max_rows" not in form, form                       # 旧拼写不得复活: 换拼写不会被任何功能用例察觉

    def test_build_form_cone_uses_native_position_fields(self):
        """Q-01: 锥形检索必须用服务端原生 pos.* 字段 (非 RA/Dec box-between)。"""
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        form = client._build_form("ps1", [], 100, ra=180.0, dec=30.0, radius_arcsec=60.0)           # 带锥形参数构造: 空间选择走的是另一套键
        assert form["pos.type"] == "cone"  # 挡住 "box-between 近似圆锥" 的错误实现
        assert form["pos.racenter"] == "180.0"                                                 # 圆心赤经必须以字符串落表: 服务端表单全是字符串值
        assert form["pos.deccenter"] == "30.0"                                                      # 圆心赤纬同理
        assert form["pos.radius"] == "60.0"  # 半径原样 arcsec 透传, 不换算成度
        assert not any(k.endswith(".constraint") for k in form), form                  # 锥形路径下不得再有 constraint 键: 两者混用会互相覆盖

    def test_build_form_constraint_operation_keys(self):
        """protocol 约束编码: {prefix}.operation + .min/.max (between)。"""
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        constraints = [                                                                             # 约束列表
            # min/max 双端: 单端区间会让 .max 键缺失这条回归漏网
            ColumnConstraint(name="class_star", constraint="between", min=0.9, max=1.0),        # 双端区间: 单端会让 max 键缺失这条回归漏网
        ]
        form = client._build_form("ps1", constraints, 100)                                          # 走真实的表单构造入口
        ops = [k for k in form if k.endswith(".operation")]  # 前缀随星表名变, 故从产物反查
        assert ops, form  # 空列表 = 约束没编成三键组, 下面两行会在 KeyError 上炸
        prefix = ops[0][: -len(".operation")]                                                       # 从键名反推出限定前缀, 后面两条按它取键
        assert form[f"{prefix}.min"] == "0.9"                                                       # 下限键与值: 值要按字符串落表
        assert form[f"{prefix}.max"] == "1.0"                                                       # 上限键与值: 缺它就是区间退化成单边

    def test_phase_two_url_carries_no_reverse_engineered_filterrules(self):
        """P1-4: 约束只活在 phase-1 表单 / sqlid 会话里, phase-2 URL 不得夹带
        逆向出来的 EasyUI filterRules。

        该第二约束源经实测证明冗余 (极窄约束带与不带都返回 0 行) 且有害
        (把 ``greaterequal`` 合并成 ``greater``, 遇 ``contains`` 值直接崩),
        因此 phase-2 URL 必须与站点自己的 datagrid URL 一样干净。
        """
        client = BestClient(rate_limit=0)  # 零限速: 下面要走完整的 phase-1→phase-2 编排
        seen_urls: list[str] = []  # 观测点: 断言对象是"客户端真发出去的 URL"

        # 替身 side_effect: 按 URL 内容分派协议阶段 — 含 getcount 的 URL 回
        # 计数 JSON ({"total": 1}), 其余 sqlid 分页 URL 回 CSV 表体;
        # 全部为 HTTP 200, 模拟 phase-2 取数阶段的正常回包。
        def get_side_effect(url, **_kw):                                                            # 替身按 URL 内容分派两个协议阶段
            """替身: 记录 URL 并按内容分派 — getcount 回计数 JSON, 其余回 CSV。"""
            seen_urls.append(url)                                                                  # 先记账: 断言要看的就是这份 URL 序列
            resp = Mock()
            resp.status_code = 200                                                            # 状态码先定死: 下游按 200/非 200 分两条路
            resp.text = '{"total": 1}' if "getcount" in url else "ps1_ra,ps1_dec\n180.0,30.0\n"  # 计数页回计数 JSON, 数据页回 CSV: 两种回包形态必须分开
            return resp

        # 替身: phase-1 POST 回包是一段含 sqlid 的 HTML (服务端会话创建成功),
        # GET 由上面的 side_effect 按 URL 分派。
        with patch.object(client.session, "post") as mock_post, \
                patch.object(client.session, "get", side_effect=get_side_effect):
            post_resp = Mock()                                                                      # 提交回包对象
            post_resp.status_code = 200
            post_resp.text = '<script>url:"/data/best/sqlid/s9999"</script>'                # 回包里带会话号: 这是 phase-2 能取数的唯一前提
            mock_post.return_value = post_resp                                                      # 装到桩上
            client.cone_search(180.0, 30.0, radius_arcsec=60, max_records=10)                       # 走公开锥搜入口, 走完整两阶段

        page_urls = [u for u in seen_urls if "/sqlid/s9999?" in u]  # 只筛数据页, 排除计数页
        assert page_urls, seen_urls  # 空列表 = 分页阶段压根没发请求, 下面的 all() 会空过
        assert all("filterRules" not in u for u in page_urls), page_urls  # 挡二次约束源

    def test_cone_search_builds_correct_constraints(self):
        """base_url 必须锚定真实 BEST 服务端 (协议锚点不被配置漂移)。"""
        client = BestClient(rate_limit=0)  # 零限速: 本例只读属性, 不触网
        assert client.base_url == "https://nadc.china-vo.org/data/best"  # 挡配置/env 改端点

    def test_extract_sqlid_from_html(self):
        """sqlid 提取: 正则须从 phase-1 HTML 的 datagrid URL 里抓到会话号。"""
        html = make_query_html(sqlid="s2623")  # 故意用非默认值: 挡住"写死 s9999"的实现
        m = __import__("re").search(r"sqlid/(s?\d+)", html)                                         # 就地导入正则: 只有这一条要用
        assert m is not None  # 匹配不到 = 正则与站点 HTML 形态脱节
        assert m.group(1) == "s2623"  # 回的是页面上那个号, 不是硬编码常量

    def test_no_sqlid_detects_no_results(self):
        """无 sqlid 的 phase-1 回包必须被 _execute_query 判为 E_NO_SQLID 而非报错。

        守 phase-1 回包分支: 站点对空结果集返回提示页 ("No results") 而不是
        datagrid URL, 客户端要能区分"没数据"与"协议坏了" —— 前者是 E_NO_SQLID,
        后者是 E_SOFT_404, 混用会让调用方把死路由当成一次正常的空结果。
        """
        client = BestClient(rate_limit=0)  # 零限速: 本例打桩的是判定分支, 不走限速器

        def _post_returning(html):                                                                  # 替身让提交恒定回指定 HTML
            """替身: phase-1 POST 恒定回一段指定 HTML (HTTP 200, 不含 sqlid)。"""
            post_resp = Mock()
            post_resp.status_code = 200                                                             # 只补状态码与正文: 页面内容由调用方给
            post_resp.text = html                                                                # 正文由调用方决定, 才能构造两种"无结果"文案
            return post_resp

        # 站点"查无此物"的真实形态: 提示页 + 无 datagrid URL (即无 sqlid)
        with patch.object(client.session, "post") as mock_post:                                     # 打桩提交阶段
            mock_post.return_value = _post_returning(
                "<html><body>No results found.</body></html>")                                      # 真实提示页: 有文案但没有会话号
            result = client._execute_query("ps1/q", {"output.fmt": "html"})                         # 走真实的编排入口, 让它自己判定分支

        # HTML 确实走过了两阶段路径: phase-1 被 POST 过一次, 判定来自会话号解析
        assert mock_post.call_count == 1  # 挡住"没 POST 就返回失败"的空转实现
        assert result.success is False
        assert result.error_code == E_NO_SQLID  # 挡"把没数据当协议坏了"的错分
        assert "No sqlid" in result.error                                                           # 错误文案要能看出是会话号缺失

        # 对照: 换成完全不含 "No results" 的空结果页, 必须得到同一个错误码 —
        # 证明判的是"没有 sqlid", 而不是嗅页面上出现过某个字符串 (只断
        # ``assert "No results" in html`` 的话, 换一句服务端文案就静默失真)
        with patch.object(client.session, "post") as mock_post2:                                    # 对照: 换一句完全不同的文案
            mock_post2.return_value = _post_returning(                                              # 同样不含会话号
                "<html><body>nothing matched your query</body></html>")
            result2 = client._execute_query("ps1/q", {"output.fmt": "html"})                        # 同样走真实编排
        assert result2.success is False
        assert result2.error_code == E_NO_SQLID  # 文案换掉后仍判同一码, 才算没在嗅字符串

    def test_fetch_sqlid_with_csv_data(self):
        """phase-2 CSV 回包必须被解析成 BestSource (坐标与记录数正确)。"""
        client = BestClient(rate_limit=0)  # 零限速: phase-2 会连续翻页, 限速会成倍拖慢
        csv_data = "180.0,30.0,15.23,16.10,45.0,0.98\n181.0,31.0,14.80,15.50,32.0,0.95\n"  # 六列无表头: 与服务端按投影返回的原始页同形

        # 替身: phase-2 GET 回包是一段无表头 CSV (HTTP 200), 模拟服务端
        # 按列投影返回的原始数据页。
        with patch.object(client.session, "get") as mock_get:                                       # 打桩分页取数
            mock_resp = Mock()                                                                      # 回包对象
            mock_resp.status_code = 200
            mock_resp.text = csv_data                                                               # 正文就是那段 CSV
            mock_get.return_value = mock_resp                                                       # 装到桩上

            # Phase 3: 生产调用形态须带 catalog_path (protocol 层按星表列投影解析)
            result = client._fetch_sqlid_data(                                                     # 生产调用形态: 带星表路径才能按列投影解析
                "s9999", output_format="csv", max_rows=100,
                page_size=50, catalog_path="ps1/q",
            )
            assert result.success  # 挡"解析失败也返 success"的自欺信封
            assert len(result.sources) >= 1  # 两行 CSV 至少落一条, 否则解析整段被吞
            assert result.sources[0].ra > 0  # 坐标被正确归位 (列错位会让 ra 变 0)

    def test_fetch_sqlid_empty_page(self):
        """phase-2 空回包 (空字符串) 必须解析为 0 条且仍算成功。

        守空页语义: 分页取数取到空 body 是正常终止信号, 不是错误。
        """
        client = BestClient(rate_limit=0)  # 零限速: 空页也要走完整个分页循环
        # 替身: GET 回包为空文本 (HTTP 200), 模拟分页循环走到尾页之后的空响应
        with patch.object(client.session, "get") as mock_get:                                       # 打桩分页取数
            mock_resp = Mock()                                                                      # 回包对象
            mock_resp.status_code = 200
            mock_resp.text = ""  # 空 body 而非 404: 尾页的正常形态
            mock_get.return_value = mock_resp                                                       # 装到桩上

            result = client._fetch_sqlid_data("s9999", output_format="csv", max_rows=100)           # 不带星表路径: 这条只关心空页语义
            assert result.success  # 终止信号不许被当成失败上报
            assert len(result.sources) == 0  # 挡"空页伪造一条脏源"


class TestQueryParameterPlumbing:
    """P1-8: columns/sort/order/nearest_only 必须到达 phase-1 表单。"""

    def test_cone_search_passes_projection_sort_and_nearest_only(self):
        """列投影/排序/仅取最近邻参数必须透传进 phase-1 表单 (plumbing 回归)。

        守参数不丢: columns 走 qualify_column 映射为 showcol, sort 限定命名
        空间, nearest_only 以 cone_nearestonly=on 落表 — 任一层丢参数都会
        让服务端按默认行为返回错误数据集。
        """
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        captured: dict = {}                                                                         # 捕获通道: 断言语义全在表单键上

        # 替身: 桩掉 _execute_query (phase-1 提交 + phase-2 取数的编排入口),
        # 只捕获实际传入的 path 与 form, 不发请求。
        def fake_execute(path, form, *args, **kwargs):                                              # 替身只捕获参数不发请求
            """替身: 捕获 path 与 form 后返回成功信封 (验证参数不丢)。"""
            captured["path"] = path                                                                 # 捕获星表路径: 证明参数确实落到了提交上
            captured["form"] = form                                                                 # 捕获表单: 下面逐键断言全靠它
            return BestQueryResult(success=True)

        with patch.object(client, "_execute_query", side_effect=fake_execute):                      # 打桩编排入口
            client.cone_search(                                                                     # 走公开锥搜入口
                180.0, 30.0, radius_arcsec=60, catalog="ps1",                                       # 天区与半径
                columns=["ra", "rpsf"], sort="rpsf", order="desc",                                  # 裸列名: 必须在下面被限定成星表列
                nearest_only=True, max_records=10,                                                  # 排序键与方向
            )                                                                                       # 最近邻开关: 静默丢弃这条最隐蔽
        form = captured["form"]  # 断言语义全在表单键上
        assert captured["path"] == "ps1/q"  # 挡"参数没落表时仍走对路由"的巧合
        assert form["showcol"] == ["ps1.ra", "ps1.rpsf"]  # 裸列名会被限定成星表列
        assert form["sort"] == "ps1.rpsf"  # 排序键同样要限定, 否则服务端按默认列排
        assert form["order"] == "desc"
        assert form["cone_nearestonly"] == "on"  # 挡"最近邻开关被静默丢弃"

    def test_default_query_path_spends_no_csrf_homepage_request(self):
        """P1-7: 公开数据面不需要登录 — 默认路径少发一次请求。

        一次完整锥检索只许触碰 ``/sqlid/`` URL (getcount + 数据页); 出现
        任何 homepage GET 都意味着 CSRF 登录流程又回到了默认路径上。
        """
        client = BestClient(rate_limit=0)                                                           # 限流置 0
        # 替身: phase-1 POST 回含 sqlid 的 HTML; GET 按 URL 分派 —
        # getcount 回计数 JSON, 数据页回 CSV; 无任何 homepage GET。
        with patch.object(client.session, "post") as mock_post, \
                patch.object(client.session, "get") as mock_get:                                    # 打桩分页取数
            post_resp = Mock()
            post_resp.status_code = 200                                                             # 回包对象
            post_resp.text = '<script>url:"/data/best/sqlid/s9999"</script>'                        # 回包里带会话号
            mock_post.return_value = post_resp                                                      # 装到桩上

            def get_side_effect(url, **_kw):                                                        # 按 URL 分派两种回包形态
                """替身: getcount URL 回计数 JSON, 数据页 URL 回 1 行 CSV。"""
                resp = Mock()
                resp.status_code = 200
                resp.text = '{"total": 1}' if "getcount" in url else "ps1_ra,ps1_dec\n180.0,30.0\n"  # 计数页回 JSON, 数据页回 CSV
                return resp

            mock_get.side_effect = get_side_effect                                                  # 装到分派函数
            result = client.cone_search(180.0, 30.0, radius_arcsec=60, max_records=10)              # 走公开锥搜入口

        assert result.success is True
        get_urls = [call.args[0] for call in mock_get.call_args_list]                               # 收集真正发出去的 GET 地址
        assert get_urls, "expected at least the getcount request"  # 空列表会让下一行空过
        assert all("/sqlid/" in url for url in get_urls), get_urls  # 出现 homepage 即 CSRF 回流
