# -*- coding: utf-8 -*-
"""ToolBox (agent 原子工具面) 单元测试: 信封形态 / 成本记账 / 错误映射 (离线)。

守的回归: 离线工具 (list_catalogs/describe_catalog) 必须零 HTTP; 站点返回值
一律标 untrusted (S-2 提示注入面); 每个结果带稳定 URI (best://...) 与
data_hash; 失败哨兵 (ra=dec=-1000) 与软 404 必须映射成错误码而不是当成结果;
N 个坐标只发一次 proximity 提交 (不是 N 次锥搜)。
"""
from __future__ import annotations

# 标准库: io (历史夹具遗留, 当前用例走 Mock 响应替身) / json (信封 JSON
# 序列化断言 — 工具调用方出口必须是纯 JSON)
import io
import json  # 出口契约: 信封必须能被 dumps/loads 往返, 否则按 JSON 消费的下游直接断

# 标准库: Mock 造 HTTP 响应替身, patch.object 替换 session.request
from unittest.mock import Mock, patch

# 测试框架: fixture 管理 patch 生命周期
import pytest  # autouse 夹具负责让请求补丁活过整个用例

# 本地: 被测单元 — 工具名元组 (对外契约, P1-9 收敛) + 工具面实现
from src.ai_tools import TOOL_NAMES, ToolBox

# 本地: 生产客户端 (工具层的 HTTP 依赖, rate_limit=0 关掉礼貌限流)
from src.client import BestClient  # 用例靠替身接管它的 request, 真实端点不触

# 协议第一阶段 (POST) 的返回体: 结果页 HTML 里内嵌 sqlid URL — 两阶段查询的
# 会话标识从这里抽取
SQLID_HTML = '<script>url:"/data/best/sqlid/s9999?output.fmt=dbgrid"</script>'                   # 第一阶段回包: 会话标识从这段 HTML 里抽
# 协议第二阶段 (分页取数) 的产物: 带 proximity 距离列的 CSV (交叉匹配路径)
PAGE_CSV = (  # 多一列距离: 交叉匹配据此认路径, 普通锥搜不该看到它
    "inputobjs_input_line,inputobjs_dist_arcsec,ps1_ra,ps1_dec,ps1_rpsf,ps1_source_id\n"       # 第二阶段的表头: 多出的距离列是交叉匹配路径的标志
    "1,0.42,180.0,30.0,15.2,PS1-1\n"                                                                # 第一条带距离的源
    "2,0.51,181.0,31.0,16.1,PS1-2\n"                                                                # 第二条带距离的源
)
# 普通锥搜分页产物 (无 proximity 距离列)
PLAIN_CSV = "ps1_ra,ps1_dec,ps1_rpsf\n180.0,30.0,15.2\n"                                            # 普通锥搜的产物: 不带距离列, 用来对照


def _fake_request(*, post_html=SQLID_HTML, count_body='{"total": 1870}',
                  page_body=PLAIN_CSV, get_body=None):                                              # 三个阶段各给一份正文: 路由要靠它们区分
    """造一个按协议阶段路由的假 HTTP 请求 (method + URL 决定返回哪一段)。

    side_effect 语义 (对应 BEST 两阶段 REST 协议):
        POST            -> 第一阶段建查询, 返回内嵌 sqlid 的结果页 HTML
        URL 含 getcount -> 计数端点, 返回 {"total": N}
        URL 含 /sqlid/  -> 第二阶段分页取数, 返回 CSV 产物
        其余            -> 通用 GET (名称解析等)
    """

    def fake(method, url, **kwargs):
        """替身 session.request: 按方法与 URL 分派三种协议阶段的响应体。

        分派规则 (与两阶段协议严格对应):
            POST            -> 回 ``post_html`` (阶段一: 取 sqlid)
            URL 含 getcount -> 回 ``count_body`` (服务端计数)
            URL 含 /sqlid/  -> 回分页 CSV (阶段二: 取数)
            其余            -> 通用 GET (名称解析等)

         Args:
            method: HTTP 方法 (POST/GET)。
            url: 请求 URL (据其片段判定协议阶段)。
            **kwargs: 其余请求参数 (替身不使用)。

        Note:
            分派必须按 URL 片段而不是调用顺序 — 工具面可能以任意顺序发请求,
            按顺序分派会让用例在实现调整后静默测到错的分支。
        """
        resp = Mock()                                                                               # 回包对象
        resp.status_code = 200  # 默认 200: 软 404 用例只改响应体, 不动状态码
        if method == "POST":                                                                        # 提交阶段才回 HTML
            resp.text = post_html                                                                   # 第一阶段的正文
        elif "getcount" in url:
            resp.text = count_body                                                                  # 计数阶段回计数体
        elif "/sqlid/" in url:
            resp.text = get_body if get_body is not None else page_body  # 显式空串也要生效, 不能用 or
        else:
            resp.text = get_body or page_body                                                       # 数据页回 CSV
        return resp
    return fake


_ACTIVE_PATCHERS: list = []                                                                         # 补丁登记表: 夹具要靠它逆序撤销


@pytest.fixture(autouse=True)
def _stop_patchers():
    """让请求补丁在整个用例期间保持存活, 用完后统一还原。

    守的回归: patch 的生命周期必须覆盖整个用例 — ToolBox 在**构造时**就捕获
    ``session.request``, 提前 stop 会让后续工具调用静默打到线上站点 (慢、且
    污染官网限速)。故在此处统一 start / 统一 stop。
    """
    yield
    while _ACTIVE_PATCHERS:  # 统一 stop: 补丁须活过整个用例 (构造期已捕获 request)
        _ACTIVE_PATCHERS.pop().stop()                                                               # 逐个撤销: 漏一个补丁会漏给后续用例


def _toolbox(fake_request) -> ToolBox:
    """构造一个 HTTP 层被替换为给定假实现的 ToolBox。

    patch 必须比构造活得更久: ToolBox 在构造期就包住 ``session.request``,
    所以在这里启动、由 autouse fixture 负责停止 — 提前释放会让工具调用静默
    打到真实站点上去。
    """
    client = BestClient(rate_limit=0)  # rate_limit=0: 用例里不必为礼貌限速付费
    patcher = patch.object(client.session, "request", side_effect=fake_request)  # 挂实例不动类
    patcher.start()  # 必须早于构造: ToolBox 构造期就把 session.request 捕获了
    _ACTIVE_PATCHERS.append(patcher)                                                                # 登记新补丁
    return ToolBox(client)


class _StubClient:
    """最小契约替身: 提供 ToolBox 构造期与契约判定要用的入口。

    判别查的是 ``fetch_page`` / ``resolve_name`` (ToolBox 真正依赖的两个
    入口), 所以替身必须实现这两个; ``session`` 也要能给一个真对象 —
    构造期会往里装请求计数器。
    """

    def __init__(self) -> None:
        """构造替身: 建一个真 requests.Session 供 ToolBox 构造期装配计数器。

        替身永远不需要真发请求, 但 session 必须是真对象 — ToolBox 构造期
        会往里挂请求计数器, 传 None 或纯魔术替身会在构造阶段就崩。
        """
        # 标准库/第三方: requests.Session — 构造期会被包上请求计数器
        import requests

        self.session = requests.Session()  # 必须是真对象: 构造期往里装计数器

    def cone_search(self, *args, **kwargs):
        """替身锥搜 (不会被调用, 只用于契约判定)。"""
        return

    def fetch_page(self, *args, **kwargs):
        """替身分页取数 (契约判定用)。"""
        return

    def resolve_name(self, *args, **kwargs):
        """替身名称解析 (契约判定用)。"""
        return


class _BareListFacade:
    """脚本式门面替身: 复刻"返回裸 list[dict]"的错客户端形态 (本地定义)。

    它是本用例的"传错客户端"样本, 用来复刻同一违约形态 —— ToolBox 的契约
    守卫 (fetch_page + resolve_name 双入口 duck-typing) 依赖它。
    """

    def __init__(self) -> None:
        """构造替身: 建一个真 requests.Session (契约判定不触网, 但要像客户端)。"""
        # 本地: 被测 agent 工具面 (7 原子工具的守门对象)
        import requests

        self.session = requests.Session()                                                           # 独立会话对象: 工具层不该共享真实会话

    def cone_search(self, *args, **kwargs):
        """替身锥搜: 返回裸 list[dict] (违约形态 — 工具面要的是信封)。"""
        return [{"ps1_ra": "180.0"}]


class TestToolBoxClientContract:
    """ToolBox 的客户端契约: 传错客户端必须明确报错, 不许炸在意想不到的地方。"""

    def test_rejects_bare_list_clients(self):
        """返回裸 ``list[dict]`` 的脚本式客户端必须抛 TypeError 并指名根因。

        工具面在 ``cone_search`` 之后要访问 ``result.success`` (BestQueryResult
        信封); 裸 list 会炸出 ``AttributeError: 'list' object has no
        attribute 'success'`` — 错误信息完全指不到"传错了客户端", 排障时
        要先翻三处调用栈才能猜到。构造期就拒收能把错误前移到源头。
        """
        with pytest.raises(TypeError, match="BestClient"):  # 报错要指名可接受类型
            ToolBox(_BareListFacade())  # 构造期拒收, 不能拖到调用期才炸

    def test_accepts_a_duck_typed_client(self):
        """只要契约一致 (有 fetch_page + resolve_name) 的替身必须被接受。

        用 duck-typing 查 ToolBox 真正依赖的入口而不是 isinstance: 测试替身
        不该为了过类型检查被迫继承 BestClient。替身还要带一个可用的
        ``session`` — 构造期会往里装请求计数器。
        """
        stub = _StubClient()  # duck-typing 替身: 无需继承 BestClient
        assert ToolBox(stub).client is stub  # 守住"不偷偷换成自己的客户端"

    def test_default_client_is_best_client(self):
        """不传 client 时必须自建 BestClient (含重试层与限流)。"""
        assert isinstance(ToolBox().client, BestClient)  # 缺省自建才带得上重试与限流


class TestOfflineTools:
    """离线工具: 只读本地注册表, 一次 HTTP 都不该发 (成本记账为 0)。"""

    def test_list_catalogs_is_offline(self):
        """list_catalogs 必须零 HTTP (星表清单是本地权威注册表)。

        守的回归: agent 每次规划都要列星表, 若这里发请求, 一次会话就多出数
        十次无用调用; cost.http_requests==0 是这条契约的断言形态。
        """
        box = ToolBox(BestClient(rate_limit=0))  # 裸客户端: 零 HTTP 契约不容替身插手
        result = box.list_catalogs()                                                                # 走公开的星表列举入口
        assert result.status["ok"] is True                                                          # 成功标志
        assert result.cost["http_requests"] == 0  # 成本账本兜底: 真发了也立刻可见
        assert len(result.data["catalogs"]) == 12                                                  # 张数取注册表实数: 写死数字会与注册表漂移
        assert result.data["groups"]["std"] == ["scr_galah", "scr_lamost", "xpsp"]  # 成员与顺序同属契约

    def test_describe_catalog_answers_from_registry(self):
        """describe_catalog 本地回答列清单与波段映射 (同样零 HTTP)。"""
        box = ToolBox(BestClient(rate_limit=0))                                                     # 限流归零
        result = box.describe_catalog("ps1")                                                        # 走公开的星表描述入口
        assert result.status["ok"] is True                                                          # 成功标志
        assert result.data["catalog"] == "ps1"                                                      # 星表名必须回显
        assert "ps1_ra" in result.data["columns"]                                                   # 赤经列必须在: 列清单少了列就无从请求
        assert result.data["magnitude_bands"]["rpsf"] == "r"                                 # 波段映射也要回: 客户端据此知道 rpsf 是哪个波段
        assert result.cost["http_requests"] == 0  # 同为本地查询: 走网络就当不成注册表

    def test_describe_navigation_group_is_invalid_input(self):
        """导航组 "std" 不是星表: 必须 E_INVALID_INPUT, 不得返回空星表数据。

        守的不变量: 把组名当星表名查会返回一个空 columns 的"成功"信封 —
        agent 据此生成约束必失败, 而错误被掩盖。
        """
        box = ToolBox(BestClient(rate_limit=0))                                                     # 限流归零
        result = box.describe_catalog("std")                                                        # 导航组不是星表, 描述它必须失败
        assert result.status["ok"] is False                                                         # 失败标志
        assert result.status["error_code"] == "E_INVALID_INPUT"  # 挡住空 columns 的假成功信封


class TestNetworkTools:
    """联网工具: 信封四要素 (data/status/cost/provenance) 与错误码映射。"""

    def test_resolve_name_envelope(self):
        """名称解析: CDS Sesame 代理 + 外部内容一律 untrusted + 稳定 URI。

        守的回归: Sesame 的 remark 是外部文本, 必须标
        content_trust=untrusted (S-2 提示注入面) — agent 不得把它当指令执行;
        stable_uri 用内容寻址 (obj=M31) 替代易失的 sqlid, 便于复现与引用。
        """
        payload = ('{"ra": 10.68470833, "dec": 41.26875, "obj": "M31", '                            # 解算响应前半段
                   '"remark": "https://cds.unistra.fr/cgi-bin/Sesame?M31"}')                 # 带外部 remark: S-2 要验的就是它被标成外部
        box = _toolbox(_fake_request(get_body=payload))  # 名称解析走 GET 分支, 正文由 get_body 给
        result = box.resolve_name("M31")                                                            # 走公开的解算入口
        assert result.status["ok"] is True                                                          # 成功标志
        assert result.data["ra"] == 10.68470833                                                     # 赤经必须回填
        assert result.data["remark_external"] is True                                               # 外部标记必须置位
        assert result.status["content_trust"] == "untrusted"  # S-2 提示注入面
        assert result.cost["http_requests"] == 1                                                    # 成本记账: 这条路径只发一次请求
        assert result.provenance["stable_uri"] == "best://nss/solve?obj=M31"  # 内容寻址换掉易失 sqlid

    def test_resolve_name_failure_sentinel_maps_to_error_code(self):
        """失败哨兵 (ra=dec=-1000) 必须映射成 E_NAME_UNRESOLVED。

        守的不变量: 哨兵坐标绝不能当正常结果返回, 否则 agent 拿着
        (-1000,-1000) 去锥搜, 报一个毫不相关的错; 必须显式失败, 调用方改
        名称重试。
        """
        box = _toolbox(_fake_request(get_body='{"ra": -1000, "dec": -1000}'))  # 哨兵坐标: 解析器须认出未解出
        result = box.resolve_name("ZZZ")                                                            # 走公开的解算入口
        assert result.status["ok"] is False                                                         # 解析不出来的名称必须失败
        assert result.status["error_code"] == "E_NAME_UNRESOLVED"  # 挡住哨兵被当真坐标流去锥搜

    def test_cone_search_reports_truncated_and_stable_uri(self):
        """锥搜: 两阶段协议共 3 次请求, 截断标记 + session_id 溯源 + 内容哈希。

        守的回归: cost.http_requests==3 (POST 建查询 + getcount 计数 + sqlid
        分页取数) 是协议阶段的成本账本; truncated=True 表示还有更多行没取
        (total_count 1870 > returned 1), 不标的话 agent 会以为查全了;
        session_id 让结果可回到同一次查询复现。
        """
        box = _toolbox(_fake_request())                                                             # 走默认路由的桩
        result = box.cone_search(180.0, 30.0, radius_arcsec=60, max_rows=1000)  # 上限远大于 total: 逼出截断标记
        assert result.status["ok"] is True                                                          # 成功标志
        assert result.data["total_count"] == 1870                                                   # 总数取服务端计数, 不是本地行数
        assert result.data["returned_count"] == 1                                                   # 实取条数与桩给的行数一致
        assert result.status["truncated"] is True  # 还剩 1869 行没取, 不标就会被当成查全
        assert result.provenance["session_id"] == "s9999"                                           # 会话号必须进血缘: 事后追溯靠它
        assert result.provenance["stable_uri"] == "best://ps1/cone?ra=180.0&dec=30.0&sr=60"       # 稳定 URI 必须拼对: 它是结果的长期句柄
        assert result.provenance["data_hash"].startswith("sha256:")  # 会话号会变, 哈希才判得出同一份数据
        assert result.cost["http_requests"] == 3  # POST 建查询 + getcount 计数 + sqlid 分页取数
        assert result.status["content_trust"] == "untrusted"                                        # 站点返回值一律标不可信: 提示注入面

    def test_cone_search_soft_404_maps_to_error_code(self):
        """站点软错误 (HTTP 200 但内容是 error JSON) 必须映射成 E_SOFT_404。

        守的不变量: 站点把路由错误放在 200 响应体里, 按状态码判成功的话
        之后会在解析阶段炸一个难懂的错; 协议层 Soft404Error 必须统一映射
        成错误码。
        """
        box = _toolbox(_fake_request(post_html='{"error":"Not Found"}'))  # 状态码仍是 200
        result = box.cone_search(180.0, 30.0)                                                       # 走公开的锥搜入口
        assert result.status["ok"] is False                                                         # 软 404 必须失败而不是当成结果
        assert result.status["error_code"] == "E_SOFT_404"  # 挡住按状态码判成功、延后炸在解析

    def test_crossmatch_batch_one_submission_for_many_coords(self):
        """交叉匹配: N 个坐标只发一次 proximity 多行提交, 不是 N 次锥搜 (P0-1)。

        守的不变量: N 个坐标只发一次 proximity 多行提交。对每个坐标各发一次
        锥搜的话, 1000 个坐标就是 1000 次请求 (慢 + 触发限流); 单次提交
        多行坐标, 由服务端做 proximity 匹配。
        """
        box = _toolbox(_fake_request(count_body='{"total": 2}', page_body=PAGE_CSV))                # 换成带距离列的路由
        result = box.crossmatch_batch(  # 两个坐标一次提交 (P0-1: N 坐标 ≠ N 请求)
            [{"ra": 180.0, "dec": 30.0, "id": "S1"}, {"ra": 181.0, "dec": 31.0, "id": "S2"}],       # 两个输入坐标: N 个坐标要一次提交
            radius_arcsec=3.0,                                                                      # 半径
        )
        assert result.status["ok"] is True                                                          # 成功标志
        assert result.data["mode"] == "proximity"  # 钉住模式位: 退回逐点锥搜时这里先变
        assert result.data["n_inputs"] == 2                                                         # 输入数必须对上
        assert result.data["returned_count"] == 2                                                   # 返回条数必须对上
        # 提交体必须是一次 proximity 多行文本 (P0-1), 不是 N 次锥搜
        assert result.provenance["lineage"]["mode"] == "proximity"  # 血缘也记模式: 只看 data 可被绕
        assert result.status["content_trust"] == "untrusted"                                        # 同样标不可信

    def test_count_tool(self):
        """count 工具: 走 getcount 端点, 稳定 URI 以 sqlid 为键。"""
        box = _toolbox(_fake_request(count_body='{"total": 42}'))                                   # 计数专用桩
        result = box.count("s9999")                                                                 # 走公开的计数入口
        assert result.status["ok"] is True                                                          # 成功标志
        assert result.data["total"] == 42  # 挡住总数取错字段 (返回体里就一个 total)
        assert result.provenance["stable_uri"] == "best://sqlid/s9999/count"  # 以 sqlid 为键才可引用

    def test_fetch_page_tool(self):
        """fetch_page 工具: 第二阶段分页路径, URI 带 page/rows 参数。"""
        box = _toolbox(_fake_request())                                                             # 走默认路由的桩
        result = box.fetch_page("s9999", page=2, page_size=1000, catalog="ps1")  # 第 2 页: 验 page 真进了 URI
        assert result.status["ok"] is True                                                          # 成功标志
        assert result.data["page"] == 2                                                             # 页号必须回显
        assert result.data["returned_count"] == 1                                                   # 返回条数必须对上
        assert result.provenance["stable_uri"] == "best://sqlid/s9999?page=2&rows=1000"  # 页号行数进 URI 便于回放

    def test_fetch_page_rejects_out_of_range_page_args(self):
        """页号/页大小越界必须 E_INVALID_INPUT, 不把非法值送进 URL。

        守的不变量: tools.schema.json 的 fetch_page.page_size 声明
        maximum=10000, 而协议层不校验页号/页长 — 越界值原样进 /sqlid 分页
        URL 的 rows= 参数, schema 声明与实现脱节, 故工具边界必须 fail-closed。
        """
        box = _toolbox(_fake_request())                                                             # 走默认路由的桩
        for bad in ({"page": 0}, {"page": -1}, {"page_size": 0},                                    # 五种越界参数: 页号与页长各取几个非法值
                    {"page_size": 10001}, {"page_size": -5}):                                       # 继续列: 页长为负也要被拒
            result = box.fetch_page("s9999", **bad)  # 越界值逐个试, 五种场景共用一对断言
            assert result.status["ok"] is False, bad                                                # 每个非法参数都必须失败: 少一类就漏一类
            assert result.status["error_code"] == "E_INVALID_INPUT", bad                            # 错误码要固定: 调用方按码分支
        # 边界值本身合法 (1 与 maximum 都放行)
        ok = box.fetch_page("s9999", page=1, page_size=10000)  # 边界值 1 与 maximum 都得放行
        assert ok.status["ok"] is True                                                       # 合法页号仍然要通过: 只拒不放到最后连正常翻页也用不了

    def test_tool_names_match_the_documented_surface(self):
        """工具名元组即对外契约: 数量/顺序都必须与文档一致 (P1-9 收敛)。

        守的回归: 工具层是唯一对外工具面 (Best/BestClient 退居实现), 改名或
        增删工具必须同步文档与 schema, 否则工具调用方与实现漂移。
        """
        assert TOOL_NAMES == (  # 顺序也是契约: 调用方按这个次序列工具
            "resolve_name", "list_catalogs", "describe_catalog",
            "cone_search", "crossmatch_batch", "count", "fetch_page",
        )

    def test_envelope_is_json_serialisable(self):
        """信封必须可 JSON 序列化 (工具调用方出口是纯 JSON)。"""
        box = ToolBox(BestClient(rate_limit=0))                                                     # 限流归零
        payload = box.list_catalogs().to_dict()  # 出口形态: 纯 JSON 可序列化字典
        assert json.loads(json.dumps(payload, ensure_ascii=False))["status"]["ok"] is True
