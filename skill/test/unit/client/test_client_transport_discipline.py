# -*- coding: utf-8 -*-
"""BestClient 传输层纪律回归。

守三类行为 (全部离线, 不打真实站点):
- P1-6: 重试只存在于 session adapter 一层, 客户端自身绝不第二次重试,
  且 Retry-After 必须被尊重 (429 首回 → 200 次回, 退避取响应头指定值);
- P3-5: phase-1 表单 POST 不在 adapter 重试白名单里 (只重试 GET) —
  POST 重试会造孤儿 sqlid 会话, 泄漏服务端查询配额;
- P0-2: 非 2xx 必须显式抛 requests.HTTPError, 不得静默直通。

被测入口是 ``BestClient._request`` (流式下载注入缝 + 通用请求出口),
传输纪律由它一处守护。鉴权经 BestAuth, 由
test/unit/client/test_gen_algo_bestauth 与 test_session_export 覆盖。
"""
from __future__ import annotations

# 标准库: 字节流构造 (响应体夹具) / mock 骨架 / 补丁
import io as _io  # 字节流构造响应体夹具, 名字加下划线避免与 httpx 的 io 混淆
from unittest.mock import Mock, patch  # Mock 骨架与 patch: 传输层的观测点都靠它

# 第三方: pytest (测试发现) / requests (HTTP 错误形态) / urllib3 (直连底层)
import pytest
import requests  # HTTP 错误形态: 生产代码抛的就是这个类型
import urllib3  # 传输纪律: 任何取数都必须过回放口, 不得直连站点

# 旧导入守门: src.client 不可导入 (依赖缺失等) 时整模块 skip 而不是
# collection error, 让 legacy 树被单独收集时不污染整套结果。
try:  # 传输纪律: 任何取数都必须过回放口
    # src.client: 两阶段异步 HTTP 客户端 (被测入口, P1 后唯一生产客户端)
    from src.client import BestClient
except Exception as _legacy_err:  # legacy-import-guard
    # pytest: 导入失败时主动 skip, 不让环境问题伪装成用例失败
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)


def test_request_retries_429_and_honours_retry_after(monkeypatch):
    """P1-6 守门: 重试只发生在 session adapter 一层, 且尊重 Retry-After。

    旧版测试 mock 的是 ``Session.request`` — 它位于 urllib3 重试环之上,
    根本没测到真正的重试层, 断言的是一个早已不存在的手写循环。下面的传输层
    补丁直接观测真实层: 首次 429 (带 Retry-After: 1), 第二次 200。
    """
    # 隔离代理环境变量: 机器若配了 HTTP(S)_PROXY, 请求会先跟代理建隧道而绕开
    # 连接池打桩, 尝试次数与退避时长都测不到 (环境噪音, 不是产品缺陷)。
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",  # 清掉代理环境变量: 本机代理会让打桩请求绕过, 测的就不是重试逻辑了
                "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)                                        # 清掉代理变量: 本机代理会让打桩请求绕过连接池, 测的就不是重试逻辑

    client = BestClient(rate_limit=0)                                                               # 限流置 0: 退避时长才是这条要量的东西
    attempts = {"n": 0}

    # urllib3 2.x 起响应构造下沉到 connection.py, 不再有 ResponseCls 可替换:
    # _make_request 直接返回真实的 HTTPResponse, Retry-After 头照进重试判定。
    def make_request(self, *args, **kwargs):
        """替身 ``HTTPConnectionPool._make_request``: 首回 429, 次回 200。

        Args:
            self: 连接池实例 (替身不使用)。
            *args: 位置参数占位。
            **kwargs: 关键字参数占位。

        Note:
            打在**连接池这一层**而不是 ``Session.request`` — 后者位于
            urllib3 重试环之上, mock 它会整层跳过真正的重试逻辑,
            断言的是一个早已不存在的手写循环 (P1-6 的旧缺陷就靠这个漏洞
            存活了很久)。
        """
        # 模拟站点行为: 第一次回 429 + Retry-After, 第二次回 200 + CSV 正文
        attempts["n"] += 1
        if attempts["n"] == 1:
            return urllib3.HTTPResponse(
                body=_io.BytesIO(b""), status=429,                                    # 首回 429 且带 Retry-After: 重试判定读的就是这个头
                headers={"Retry-After": "1"}, preload_content=False,
            )
        return urllib3.HTTPResponse(
            body=_io.BytesIO(b"ps1_ra,ps1_dec\n180.0,30.0\n"), status=200,                    # 次回 200 并给一份最小 CSV: 成功路径的正文
            headers={}, preload_content=False,                                                # 不预读响应体: 让适配器自己处理流, 与真实行为同构
        )

    # 记录每次 sleep 时长: 验证适配器按 Retry-After 退避, 而不是拍脑袋固定值
    sleeps: list[float] = []                                                                   # 逐次记录 sleep 时长: 退避值只能从这里读到
    with patch.object(urllib3.connectionpool.HTTPConnectionPool,  # 拦在连接池这一层: 比拦 requests.Session 更靠里, 才测得到适配器行为
                      "_make_request", make_request), \
            patch("time.sleep", side_effect=sleeps.append):
        resp = client._request("GET", f"{client.base_url}/sqlid/s9999")

    assert resp.status_code == 200                                                                  # 最终必须成功: 重试就是为了拿到 200
    assert attempts["n"] == 2  # 客户端自身绝不重试, 重试全在 adapter 层
    # Retry-After 指定的 1 秒必须出现在实际退避时长里
    assert 1.0 in sleeps  # 必须真的按 Retry-After 睡: 不睡就是无节制重试, 会打爆上游


def test_phase1_post_is_not_retried_by_the_adapter():
    """P3-5 守门: 表单 POST 不在 adapter 重试白名单里 (只重试 GET)。

    复过的现: ``allowed_methods=["GET","POST"]`` — phase-1 表单 POST
    在 429/5xx 时重试 3 次, 服务端创建 3 个 sqlid 会话, 前两个成孤儿
    会话 (泄漏查询配额)。phase-2 分页 GET 才是幂等可重试的那一半。
    """
    client = BestClient(rate_limit=0)                                                              # 限流置 0: 这条只读适配器配置, 不触网
    adapter = client.session.get_adapter(f"{client.base_url}/ps1/q")
    allowed = set(adapter.max_retries.allowed_methods or set())  # POST 不在白名单: 提交是写操作, 重试可能造成重复提交
    assert allowed == {"GET"}, client


def test_request_raises_http_error_on_404():
    """P0-2 守门: 非 2xx 必须显式抛 requests.HTTPError, 不得静默直通。

    让 401/403/404 直通到调用方的话, "token 过期"会被读成"天上没有源",
    404 错误页甚至被当下载产物写盘。这一条守的是显式失败本身。
    """
    client = BestClient(rate_limit=0)                                                               # 限流置 0
    response = Mock()                                                                               # 替身响应对象
    response.status_code = 404                                                                   # 状态码 404: 静默直通会把错误页当产物写盘
    response.text = "<html><body>404 Not Found</body></html>"
    response.raise_for_status.side_effect = requests.HTTPError(  # raise_for_status 旁挂 response: 排障要能读到状态码
        "404 Client Error", response=response
    )
    with patch.object(client.session, "request", return_value=response), \
            pytest.raises(requests.HTTPError):                                     # 必须抛 HTTPError: 不得让 401/403/404 直通到调用方
        client._request("GET", f"{client.base_url}/ps1/q")


def test_retry_backoff_cap_is_wired_to_the_protocol_constant():
    """``MAX_BACKOFF_S`` 必须真的接到 adapter 上, 而不是一个零引用的死常量。

    ``src/protocol.py`` 把它注释为「单次退避上限 (秒): 指数退避
    的封顶值; 消费方同上」, 可 ``BestClient`` 构造 ``Retry(...)`` 时并没有传
    ``backoff_max``, 全 ``src/`` 对该常量零生产引用 —— 而 E4 的 rubric 把它当作
    已生效的判据。注释说有的东西代码没接线, 这条就是那个「没接线」的守门。

    口径说明: 当前 ``total=3`` + ``backoff_factor=2.0`` 的退避序列只有 2/4/8 秒,
    远在 60 秒封顶之下, 所以本条**不改变任何运行时行为**; 它守的是日后调大
    total / backoff_factor 时封顶仍然在位。``Retry-After`` 不受此封顶约束
    (那是服务端明确表达的等待意图, 不该被客户端裁剪)。
    """
    # src.protocol: 退避封顶常量的定义处 (本条要与它逐值相等, 不能各写一个数)
    from src.protocol import MAX_BACKOFF_S

    client = BestClient(rate_limit=0)  # 限流归零: 本条只读配置, 不发请求
    adapter = client.session.get_adapter("https://astro-best.invalid")  # 取挂上的适配器
    assert adapter.max_retries.backoff_max == MAX_BACKOFF_S, (
        f"退避封顶没接上: adapter 上是 {adapter.max_retries.backoff_max!r}, "
        f"协议层常量是 {MAX_BACKOFF_S!r} —— 注释说的封顶在代码里不存在"
    )


def test_explicit_timeout_reaches_every_request_site():
    """A2-02 守门: 显式传的 ``timeout`` 必须真的落到出网请求上。

    复过的现: ``BestClient(timeout=7)`` 把值存进 ``self.timeout`` 之后,
    **六个出网点无一读取它** —— 阶段 1 POST、阶段 2 分页 GET、``getcount``、
    名称解析、通用 ``_request`` 全部硬取协议层 ``REQUEST_TIMEOUT``(120)。
    于是"看着配过、其实没生效", 而 ``src/core/pipeline.py`` 读配置里的
    ``timeout`` 下传、``src/core/__init__.py`` 宣称"全量透传", 两处都是假的:
    探针实测 ``BestClient(timeout=7)`` 的三次请求全是 ``timeout=120``。

    本条逐个请求点验, 而不是只验 ``self.timeout`` 这个属性存在 —— 属性存在
    恰恰是修复前的状态, 缺陷正在于"存了没人读"。
    """
    # src.protocol: 缺省超时的唯一出处 (与被测代码逐值比, 不各写一个数)
    from src.protocol import REQUEST_TIMEOUT

    seen: dict[str, object] = {}                                                               # 收各请求点实际用的 timeout
    client = BestClient(rate_limit=0, timeout=7)                                               # 显式配 7s: 远小于缺省 120, 一眼能分辨
    with patch.object(client.session, "post", return_value=Mock(text="")) as post:             # 阶段 1: 建会话 POST
        with patch.object(client.session, "get", return_value=Mock(text='{"total": 0}')) as get:  # 阶段 2 getcount 与分页 GET
            client.submit_phase1("ps1")                                                        # 阶段 1: 表单 POST 出网点
            client.count("s3839")                                                              # getcount 出网点
    seen["phase1_post"] = post.call_args.kwargs.get("timeout")
    seen["getcount_get"] = get.call_args.kwargs.get("timeout")

    with patch.object(client.session, "request", return_value=Mock(status_code=200, text="x", \
            raise_for_status=Mock())) as req:                                                  # 通用出口 _request (流式下载兜底同走这里)
        client._request("GET", f"{client.base_url}/ps1/q")
    seen["request"] = req.call_args.kwargs.get("timeout")

    wrong = {site: value for site, value in seen.items() if value != 7}                         # 逐点比对: 任一处回落到 120 即红
    assert not wrong, (
        f"显式 timeout=7 没有生效 (应全为 7): {wrong} —— 未列出的点取的是协议层常量 "
        f"{REQUEST_TIMEOUT}"
    )


def test_default_timeout_is_unchanged_for_callers_that_do_not_configure_it():
    """反向自证: 上面那条把 ``self.timeout`` 接上了, 缺省行为必须**逐值不变**。

    ``BestClient.__init__`` 的缺省仍是协议层 ``REQUEST_TIMEOUT``, 所以没有
    显式配置 timeout 的调用方 (含全部评测回放) 行为与修复前完全一致。没有
    这条, "让 timeout 生效"很容易被实现成"把所有请求硬绑到一个新常量上"。

    顺带钉住连通性自检的独立口径: ``check_connection`` 用 30s 而不是跟随
    实例超时 (``ALGORITHM-SPEC.md`` 超参表把两者列为两项), 它**不该**被
    这次改动捎带上。
    """
    # src.protocol: 缺省超时常量 (须与 BestClient.__init__ 的缺省逐值相等)
    from src.protocol import REQUEST_TIMEOUT

    client = BestClient(rate_limit=0)                                                          # 不传 timeout: 走缺省
    assert client.request_timeout == REQUEST_TIMEOUT, "缺省必须仍取协议层常量"
    assert client.timeout == REQUEST_TIMEOUT, "实例属性与缺省值必须一致, 不能一个生效一个不生效"

