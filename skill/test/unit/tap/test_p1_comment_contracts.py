# -*- coding: utf-8 -*-
"""D1 五条 P1 的核实回归: 把"注释承诺 vs 实现行为"钉成可执行断言。

为什么单独一个文件: 这批用例守的不是路由语义 (那由 test_service.py 负责), 而是
**三条被 D1 判错的注释结论**, 具体是 (a) 哪些不可达是**有意**的防御, (b) 哪些
分支注释说错了触发条件。删掉本文件等于允许后人按错误注释"修"实现, 从而造出真 bug。

本文件只连 127.0.0.1 回环 (唯一 socket 冒烟用例在此), 绝不触外网。

对应关系:
  - P1-2 (client.py 空 query/fragment 放行)  -> TestEmptyQueryFragmentIsAccepted
  - P1-4 (adql.py 别名归一不可达)            -> TestCatalogAliasNormalizationUnreachable
  - P1-5 (service.py Content-Length 二次防线) -> TestContentLengthSecondDefense
"""
from __future__ import annotations

import socket
import threading

# 第三方: pytest 承载
import pytest

# 本地: 被测三处 (TAP URL 强校验 / ADQL 解析 / 网关 socket 适配层)
from src.tap.adql import parse_adql
from src.tap.client import _gateway_api_url, _validated_tap_url
from src.tap.executor import TapExecutor
from src.tap.service import TapGateway, TapHTTPServer


class _FakeBest:
    """替身上游: 供需要真网关的 socket 冒烟用例用, 保持零外网。"""

    def query(self, **_kwargs):
        """无视入参回吐固定行: 替身一旦校验参数就会遮住上游真实行为。"""
        return [{"ps1_ra": "1.0", "ps1_rpsf": "2.0", "ps1_source_id": "S1"}]  # 一行够序列化分支用: 多行会引入截断语义干扰


class _CountingGateway(TapGateway):
    """记录 ``max_body_bytes`` 被读了几次, 用来区分两道 413 各由哪一行发出。

    这是本文件的关键探针: 只看状态码无法区分"声明长度超限"与"实际字节超限",
    两条分支发的是同一个 413。计数是唯一能证明 L365 真被走到��办法。
    """

    def __init__(self, *args, limit: int = 1048576, **kwargs):
        """先落计数与上限再调基类: 基类构造期就会写一次 max_body_bytes。"""
        self._reads = 0  # 计数初值: 判定"拦截发生在哪一道"的唯一依据
        self._limit = limit  # 上限存字段: 读写都走 property, 不落到实例 __dict__ 绕过计数
        super().__init__(*args, **kwargs)  # 基类只需执行器: 网关构造不触网

    @property
    def max_body_bytes(self) -> int:
        """每次被读都记账: L360 读一次, 越过它才会再读一次 (即 L365)。"""
        self._reads += 1
        return self._limit

    @max_body_bytes.setter
    def max_body_bytes(self, value: int) -> None:
        """保留写入路径: 基类 __init__ 会赋值, 不接住就会 AttributeError。"""
        self._limit = value  # 只存值: 读路径才计数, 写路径不参与"读了几次"的判定

    @property
    def reads(self) -> int:
        """暴露计数: 断言"拦截发生在哪一道"时读它。"""
        return self._reads


def _post_raw(port: int, content_length: str | None, body: bytes, *, timeout: float = 8.0) -> str:
    """裸 socket 发一笔 POST 并回读状态行 (只走回环, 不触外网)。

    半关写端 (``SHUT_WR``) 是必需的: 否则服务器 ``read(-1)`` 等不到 EOF 会挂到超时,
    那样就测不出"读到 EOF 后实际字节超限"这条真实路径。
    """
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        header = f"Content-Length: {content_length}\r\n" if content_length is not None else ""
        sock.sendall(
            (f"POST /tap/sync HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n{header}"
             f"Content-Type: application/x-www-form-urlencoded\r\n"
             f"Connection: close\r\n\r\n").encode() + body
        )
        sock.shutdown(socket.SHUT_WR)  # 半关: 让 read(-1) 拿到 EOF, 否则只能测到超时
        sock.settimeout(timeout)
        buf = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
        head = buf.split(b"\r\n\r\n")[0].decode("latin-1")
        return head.split("\r\n")[0] if head else ""
    finally:
        sock.close()


class TestEmptyQueryFragmentIsAccepted:
    """P1-2: 裸 ``?``/``#`` 会被放行, 且**不**构成泄漏面 (改的是注释不是实现)。"""

    @pytest.mark.parametrize("raw", ["http://h/tap?", "http://h/tap#", "http://h/tap?#"])
    def test_bare_query_or_fragment_passes_validation(self, raw):
        """urlparse 对裸 ?/# 返回空串 (假值) -> 不触发拒绝, 原样返回。"""
        assert _validated_tap_url(raw) == raw  # 原样返回即"放行"; 若日后改成拒, 此断言会红

    @pytest.mark.parametrize("raw", [
        "ftp://h/tap", "http:///tax", "http://user@h/tap", "http://user:pw@h/tap",
        "http://h/tap?a=1", "http://h/tap#f",
    ])
    def test_real_credentials_and_nonempty_query_are_rejected(self, raw):
        """**非空** query/fragment 与凭据照旧拒绝 — 放行面仅限空串, 不得放宽。"""
        with pytest.raises(ValueError):
            _validated_tap_url(raw)

    @pytest.mark.parametrize("raw", ["http://h:8000/tap?", "http://h:8000/tap#", "http://h:8000/tap?#"])
    def test_bare_query_cannot_carry_token_into_endpoint(self, raw):
        """放行的残余面为何无害: urljoin 把裸 ?/# 整段丢掉, token 不会落进 URL。"""
        base = _validated_tap_url(raw)
        assert _gateway_api_url(base, "/api/v1/auth/nadc/token") == "http://h:8000/api/v1/auth/nadc/token"


class TestCatalogAliasNormalizationUnreachable:
    """P1-4: adql/service 的别名归一当前**不可达**, 且这是有意的 (E4 要求拒旧拼写)。"""

    def test_alias_left_key_is_not_a_whitelisted_catalog(self):
        """根因即不变量: 别名左键与白名单键集不相交 -> .get() 恒取默认值。"""
        from src.protocol import CATALOG_ALIASES, CATALOG_PATHS  # 局部导入: 只本用例需要键集

        assert not set(CATALOG_PATHS) & set(CATALOG_ALIASES)  # 不相交即恒等映射
        assert all(CATALOG_ALIASES.get(key, key) == key for key in CATALOG_PATHS)  # 逐键确认: 交集为空蕴含此式

    @pytest.mark.parametrize("table", [
        "best.gaia_dr3", "gaia_dr3", "BEST.GAIA_DR3", "x.best.gaia_dr3", "best.gaia_dr3.",
    ])
    def test_old_spelling_table_name_is_rejected(self, table):
        """旧拼写在 FROM 阶段就被拒: 注释曾许诺的"用户可写旧拼写"能力并不存在。"""
        with pytest.raises(Exception) as exc:  # ADQLError 的具体类不在本用例关注面
            parse_adql(f"SELECT ra FROM {table}")
        assert "Unknown BEST table" in str(exc.value)

    def test_canonical_spelling_still_works(self):
        """守住另一侧: 归一虽不可达, 但规范 id 的列白名单必须照常工作。"""
        assert parse_adql("SELECT ra FROM best.ps1").columns == ("ps1_ra",)


class TestContentLengthSecondDefense:
    """P1-5: L365 那道"二次防线"**物理上可达** (经 ``Content-Length: -1``), 不得删。"""

    @pytest.fixture
    def server(self):
        """起一个真回环网关; 计数型网关用于判定拦截发生在哪一道。"""
        gateway = _CountingGateway(TapExecutor(_FakeBest()), limit=1048576)
        httpd = TapHTTPServer(("127.0.0.1", 0), gateway)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            yield httpd.server_address[1], gateway
        finally:
            httpd.shutdown()  # 先停循环再关端口: 反序会留下 TIME_WAIT 悬挂句柄
            httpd.server_close()

    def test_declared_length_over_limit_is_rejected_at_first_check(self, server):
        """声明长度就超限 -> 只读一次上限, 即由 L360 拦下。"""
        port, gateway = server
        status = _post_raw(port, "2000000", b"x=1")
        assert "413" in status
        assert gateway.reads == 1  # 只被读一次 => 越过 L360 的分支从未进入

    def test_negative_one_length_lets_read_consume_past_the_limit(self, server):
        """``Content-Length: -1`` 使 read(-1) 读到 EOF, 实际字节可超限 -> **L365 真的触发**。

        这条是 D1 判错的关键反例: 删掉该分支等于给 ``-1`` 开一个读满全连接的口子。
        """
        port, gateway = server
        body = b"QUERY=SELECT+ra+FROM+best.ps1&x=" + b"a" * 3_000_000  # 真体 3MB > 1MB 上限
        status = _post_raw(port, "-1", body)
        assert "413" in status
        assert gateway.reads == 2  # 第二次读上限 = 确实走进了 L365 的实际字节检查

    def test_negative_one_small_body_is_not_over_limit(self, server):
        """同一哨兵但真体未超限 -> 放行进业务分支, 证明上面不是恒 413 的假阳性。"""
        port, gateway = server
        status = _post_raw(port, "-1", b"QUERY=SELECT+ra+FROM+best.ps1")
        assert "200" in status
        assert gateway.reads == 2  # 走到了 L365 但未超限, 故不拒
