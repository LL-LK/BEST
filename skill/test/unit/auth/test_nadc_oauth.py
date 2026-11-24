# -*- coding: utf-8 -*-
"""Phase 6 NADC OAuth 身份层测试 (全 mock, 零网络零凭据)。

覆盖: 授权 URL 构造/state 生成; code 交换 (成功/HTTP 错误/缺 token); profile 解析
(业务码/字段映射); TokenStore (0600/过期判断/清除/静态保护); 手动粘贴流 (URL 与裸
code); 本地回环流的 state 校验与超时; 登出 URL; ensure_access_token 过期恢复单点。
"""
from __future__ import annotations

# 标准库: JSON 响应体编解码、回环服务器线程、超时控制、HTTP 错误类型、
# 本地 HTTP 服务器 (回环收 code 用) 与路径/补丁工具
import json  # 只为造桩响应体: 令牌与 profile 都是 JSON
import threading  # 回环替身服务器跑在守护线程上, 不阻塞用例主线程
import time  # 超时控制: 替身与超时用例都要它
import urllib.error  # 替身要抛原生 HTTPError, 由生产代码负责翻译
from http.server import BaseHTTPRequestHandler, HTTPServer  # 回环替身: 只需回 200
from pathlib import Path  # 令牌文件路径由夹具给, 不碰真实 home
from unittest.mock import patch  # patch 拦掉真实网络: 本文件零凭据零外网

# 第三方: pytest (raises 断言 — 授权失败/HTTP 错误/业务码非 200/超时都必须抛错)
import pytest  # 本文件以失败语义为主力, raises 是断言主干

# 本地: NADC OAuth2.0 身份层权威入口 —— 授权 URL/换 token/取 profile/令牌存储/两种登录流
from src.auth import (
    ENV_CLIENT_ID,  # client_id 的环境变量名: 运维脚本与文档的契约
    ENV_CLIENT_SECRET,  # client_secret 的环境变量名: 同上
    NadcOAuthError,  # 统一的业务异常: 授权/换码/profile 三处失败都收敛到它
    OAuthProfile,  # profile 载体: 属主判定与配额分组都读它
    TokenExpiredError,  # 过期异常: 无交互通道时上层靠它决定怎么恢复
    TokenStore,  # 令牌存储: 权限位与过期判断的契约都在这里
    build_authorize_url,  # 授权 URL 构造: 协议参数少一个就被授权页拒跳
    build_logout_url,  # 登出 URL: 前端"退出登录"按钮直接拼它
    ensure_access_token,  # 过期恢复单点: 有效直通/回调恢复/无通道抛错三条路
    exchange_code,  # code 换令牌: 表单体写错只在线上暴露
    get_profile,  # 取 profile: 业务码非 200 必须抛错
    run_manual_paste_flow,  # 手动粘贴兜底流: 回环被挡时的唯一出路
)

# 模块级夹具: NADC profile 接口的成功响应体 (HTTP 200 + 业务 code 200 + data.user 段),
# 供字段映射用例复用; 权威来源是 NADC 用户信息接口的实际返回结构。
PROFILE_PAYLOAD = {                                                                        # 照真实用户信息接口的返回结构造: 键名错位就是字段映射错位
    "code": 200,
    "message": "success",
    "data": {"user": {
        "umtId": "UMT-123", "unionId": "", "ldap_id": "astro",
        "name": "Test User", "email": "t@example.org", "phone": "",
        "confirmed": True, "locked": False, "avatar_url": "",
    }},
}


class TestAuthorizeUrl:
    """授权 URL 构造: 协议参数齐全、state 随机生成、缺 client_id 本地拒绝。"""

    def test_url_contains_protocol_params(self):
        """授权 URL 必须带齐 response_type=code/client_id/scope/state 且指向官方 authorize 端点。

        回归锚点: 少任一协议参数, NADC 授权页会直接拒绝跳转, 用户看到的是白屏而非错误。
        """
        url, state = build_authorize_url("cid", "http://127.0.0.1:8765/callback", state="s1")  # 显式 state 便于断言
        assert "response_type=code" in url
        assert "client_id=cid" in url
        assert "scope=profile" in url
        assert "state=s1" in url
        assert url.startswith("https://oauth.china-vo.org/oauth/authorize")  # 端点写错会跳去别的域, 用户只看到白屏

    def test_state_generated_when_absent(self):
        """未显式传 state 时必须随机生成且两次不重复 (OAuth2.0 CSRF 防护的生命线)。"""
        _, s1 = build_authorize_url("cid", "http://x/cb")  # 省略 state 即走随机生成分支
        _, s2 = build_authorize_url("cid", "http://x/cb")                                        # 再生成一次: 两次必须不同才谈得上防 CSRF
        assert s1 and s2 and s1 != s2  # 随机且不重复

    def test_missing_client_id_raises(self):
        """client_id 为空必须在本地就抛错, 不允许发出一个注定失败的授权请求。"""
        with pytest.raises(NadcOAuthError):  # 本地就拒: 省一次注定失败的授权往返
            build_authorize_url("", "http://x/cb")


class TestExchangeCode:
    """code 换 token: 成功表单、HTTP 错误、响应缺 access_token 三种语义。"""

    def test_success(self):
        """成功路径: 请求体必须是 grant_type=authorization_code + client_secret 的表单编码。

        回归锚点: grant_type 写错会被 NADC 当 invalid_grant 拒掉, 而错误只出现在线上。
        """
        captured = {}  # 替身与断言之间的唯一通道: 请求体与端点都记在这里

        # 替身 HTTP 响应: 状态 200, read() 返回令牌 JSON, 并实现 __enter__/__exit__
        # 以兑现 urlopen 返回对象的上下文管理器契约
        class _Resp:
            """替身 HTTP 响应: 伪装 urllib 的响应对象 (状态码 + read + 上下文管理)。

            为什么必须自己造: ``urllib.request.urlopen`` 的返回值要实现
            ``read()`` 与 ``__enter__``/``__exit__``, 生产代码用
            ``with urlopen(...) as r:`` 取值; 少了上下文管理协议, 桩对象连
            ``with`` 都进不去, 测的就不是生产代码了。
            """

            status = 200                                                                        # 成功替身给 200, 让生产代码走成功分支取令牌

            def read(self):
                """返回令牌 JSON 的字节体 (urllib 契约: read() 给 bytes 不给 str)。"""
                return json.dumps({"access_token": "tok-1", "expires_in": 3600}).encode()  # urllib 契约: read() 给 bytes

            def __enter__(self):
                """进入 with 块时返回自身 (兑现上下文管理器协议)。"""
                return self                                                              # 第一次进入: 生产代码用 with 取 read() 的值, 少了它连块都进不去

            def __exit__(self, *a):
                """退出 with 块; 返回 False 表示不吞异常。"""
                return False                                                           # 第一处不吞异常: 生产代码的清理逻辑要能跑

        # 替身 urlopen: 捕获实际发出的请求体与 URL 后返回上面的 _Resp, 全程不触网
        def fake_urlopen(request, timeout=None):
            """替身 urlopen: 记录真实请求体与 URL, 返回上面的 _Resp (零网络)。

            Args:
                request: 生产代码构造的 ``urllib.request.Request`` (含 data/full_url)。
                timeout: 超时秒数 (替身不使用, 只为签名对齐)。

            Note:
                捕获 ``request.data`` 是为了断言 POST 体里确实带了
                ``grant_type=authorization_code`` 与 ``client_secret`` —
                这两个字段缺一个, 令牌交换就会以 invalid_request 失败。
            """
            captured["body"] = request.data.decode()  # 断言表单体: grant_type 与 client_secret 都在里面
            captured["url"] = request.full_url  # 记端点: 换错 host 时能一眼看出
            return _Resp()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            payload = exchange_code("code-1", "cid", "sec", "http://x/cb")
        assert payload["access_token"] == "tok-1"  # 挡住"HTTP 200 即成功"的误判
        assert "grant_type=authorization_code" in captured["body"]  # 写错会被判 invalid_grant, 且只在线上暴露
        assert "client_secret=sec" in captured["body"]  # 缺 secret 的请求必被 NADC 拒

    def test_http_error_raises(self):
        """令牌端点返回 HTTP 401 时, 异常消息必须带上状态码便于定位。"""

        # 替身 urlopen: 模拟令牌端点 401 Unauthorized (urllib 的 HTTPError 形态)
        def fake_urlopen(request, timeout=None):                                      # 替身签名要与 urlopen 对齐, 否则 patch 上去就调不动
            """替身 urlopen: 一律抛 401 HTTPError (模拟令牌端点拒绝)。

            Args:
                request: 生产代码构造的请求对象 (替身不使用)。
                timeout: 超时秒数 (替身不使用, 签名对齐用)。

            Note:
                断言异常消息里含 ``401`` 是为了让运维看到状态码就能定位 —
                只报 "token exchange failed" 的消息会让人去查 code/secret,
                而真实原因往往是端点临时不可用。
            """
            raise urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)  # 抛原生类型: 翻译是生产代码的活

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with pytest.raises(NadcOAuthError, match="401"):  # 消息带状态码: 运维看一眼就能定位
                exchange_code("c", "cid", "sec", "http://x/cb")

    def test_missing_access_token_raises(self):
        """HTTP 200 但响应里没有 access_token 也必须判失败。

        回归锚点: NADC 用业务错误体表达失败; 只看 HTTP 状态码会把 invalid_grant
        当成登录成功, 让后续请求带着空 token 四处撞 401。
        """
        # 替身 HTTP 响应: 状态 200, 但 body 是错误体而非令牌
        class _Resp:
            """替身 HTTP 响应: 状态 200 + 业务错误体 (模拟 NADC 的失败表达方式)。

            NADC 用响应体而不是状态码表达业务失败, 所以"HTTP 200"完全不等于
            "成功"; 这个桩专门用来验证生产代码会去解析 body。
            """

            status = 200                                                                 # 失败也回 200: NADC 用业务体表达失败, 状态码不作数

            def read(self):
                """返回错误体字节 (``{"error": "invalid_grant"}``)。"""
                return json.dumps({"error": "invalid_grant"}).encode()  # 业务错误体: NADC 的失败表达方式

            def __enter__(self):                                                                    # 第二次进入: 错误体那一份同样要兑现 with 协议
                """进入 with 块时返回自身。"""
                return self

            def __exit__(self, *a):
                """退出 with 块; 返回 False 不吞异常。"""                                                     # 第二处不吞异常: 错误体替身同样不能吞
                return False

        with patch("urllib.request.urlopen", return_value=_Resp()):
            with pytest.raises(NadcOAuthError, match="access_token"):        # 缺 access_token 即判失败: 否则后续请求带空 token 四处撞 401
                exchange_code("c", "cid", "sec", "http://x/cb")


class TestGetProfile:
    """profile 解析: Bearer 头格式、业务码非 200、空 token 三种边界。"""

    def test_profile_parsing(self):
        """Authorization 头必须是 "Bearer <token>" (单空格), 且业务字段正确映射。

        回归锚点: 官方规范对 Bearer 后的单空格敏感; umtId/ldap_id 映射错位会让
        属主判定与配额分组整体错乱。
        """
        # 替身 HTTP 响应: 状态 200 + PROFILE_PAYLOAD 业务体, 支持 with 语法
        class _Resp:
            """替身 HTTP 响应: 状态 200 + profile 业务体 (支持 with 语法)。"""

            status = 200                                                                  # profile 替身同样给 200, 字段映射才有机会被验到

            def read(self):
                """返回 profile 业务体的字节形式。"""
                return json.dumps(PROFILE_PAYLOAD).encode()  # 字段映射的输入: 键名错位在这里暴露

            def __enter__(self):                                                                    # 第三次进入: profile 那一份的 with 协议
                """进入 with 块时返回自身。"""
                return self

            def __exit__(self, *a):
                """退出 with 块; 返回 False 不吞异常。"""                                                     # 第三处不吞异常: profile 替身也不能吞
                return False

        captured = {}                                                                          # 捕获头的通道: Bearer 格式只能从请求头上验

        # 替身 urlopen: 捕获 Authorization 头后返回 _Resp, 验证请求头发送形态
        def fake_urlopen(request, timeout=None):
            """替身 urlopen: 捕获 Authorization 头 (断言 Bearer 格式) 后返回 _Resp。

            Args:
                request: 生产代码构造的请求对象 (取其 headers)。
                timeout: 超时秒数 (替身不使用, 签名对齐用)。

            Note:
                Bearer 与 token 之间必须是**单个空格**; 少一个字符服务端就按
                无法识别的 scheme 处理, 报 401 且看不出是格式问题。
            """
            captured["auth"] = request.headers.get("Authorization")  # 头格式错, 服务端只会回 401
            return _Resp()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            profile = get_profile("tok-1")  # 假 token 即可: 真实网络已由 patch 拦掉
        # Bearer 与 token 间必须有空格 (官方规范)
        assert captured["auth"] == "Bearer tok-1"
        assert isinstance(profile, OAuthProfile)                                    # 必须解析成 profile 载体: 返回裸 dict 会让上层取不到字段
        assert profile.umt_id == "UMT-123"  # 属主判定靠 umt_id: 映射错位会整片错分组
        assert profile.ldap_id == "astro"                                                    # ldap 账号也是属主判定的输入, 映射错同样会错分组
        assert profile.email == "t@example.org"                                                     # 邮箱字段映射: 通知与配额归属都读它
        assert profile.confirmed is True                                               # 确认位必须映射成布尔: 字符串 "true" 会在下游被当真值处理

    def test_business_code_non_200_raises(self):
        """HTTP 200 但业务 code=401 (token 失效) 必须抛错, 不能当已登录放行。"""
        # 替身 HTTP 响应: 传输层 200, 业务层 401 invalid token
        class _Resp:
            """替身 HTTP 响应: 传输层 200 但业务 code=401 (token 已失效)。"""

            status = 200                                                                 # 传输层 200 配业务 401: 只看状态码的实现会当成已登录

            def read(self):
                """返回业务错误体的字节形式。"""
                return json.dumps({"code": 401, "message": "invalid token"}).encode()     # 传输层 200 但业务层 401: 只看状态码就会当成已登录

            def __enter__(self):                                                                    # 进入 with 块时返回自身
                """进入 with 块时返回自身。"""
                return self

            def __exit__(self, *a):
                """退出 with 块; 返回 False 不吞异常。"""
                return False                                                                        # 返回 False 不吞异常

        with patch("urllib.request.urlopen", return_value=_Resp()), pytest.raises(NadcOAuthError, match="401"):
            get_profile("bad")

    def test_empty_token_raises(self):
        """空 token 在本地即被拒绝, 不发请求 (省一次注定 401 的往返)。"""
        with pytest.raises(NadcOAuthError):                                            # 空 token 必须本地拒, 不值得为它发一次注定 401 的请求
            get_profile("")  # 空 token 本地拒: 省一次注定 401 的往返


class TestTokenStore:
    """TokenStore 磁盘契约: 存取、过期判断、损坏容错、0600 权限。"""

    def test_save_load_expire_clear(self, tmp_path):
        """save/load/is_expired/clear 四件套闭环, 且令牌文件权限必须是 0600。

        回归锚点: 令牌落盘权限过宽 (0644) 会把 access_token 暴露给同机其他用户,
        这是安全评审的硬项; 清除后 load 必须回 None 让上层按未登录处理。
        """
        store = TokenStore(path=tmp_path / "tok.json")  # 路径由 tmp_path 给: 不碰真实 home
        record = store.save({"access_token": "t1", "expires_in": 3600})  # save 顺手补齐缺省字段
        assert record["access_token"] == "t1"
        assert store.load()["access_token"] == "t1"
        assert store.is_expired() is False                                                       # 刚存的令牌当然没过期: 这是四件套闭环的第三步
        # 0600 权限 (POSIX); Windows 上跳过权限位断言
        import os  # 局部导入: 只有权限位这一条要用

        if os.name == "posix":                                                            # 权限位只在 POSIX 成立, Windows 上没有这一说
            assert oct(store.path.stat().st_mode & 0o777) == "0o600"  # 0644 会把 token 露给同机其他用户
        store.clear()                                                                           # 清除要真删磁盘文件, 令牌不留在盘上等下次被读到
        assert store.load() is None                                                               # 清除后必须回 None, 让上层按未登录处理

    def test_expired_token_detected(self, tmp_path):
        """skew_seconds 提前量内的 token 要判过期, valid_token 返回 None。

        回归锚点: expires_in=1 配 skew=3600 模拟"即将过期"; 少了提前量会让请求在
         token 到期瞬间批量 401。
        """
        store = TokenStore(path=tmp_path / "tok.json")                                              # 令牌文件路径由夹具给
        store.save({"access_token": "t1", "expires_in": 1})  # 1 秒寿命 + 3600 提前量 = 立即判过期
        assert store.is_expired(skew_seconds=3600) is True  # 提前量是防"到期瞬间批量 401"那道闸
        assert store.valid_token() is None                                                 # valid_token 也要跟着判过期: 两处口径必须一致

    def test_corrupt_file_returns_none(self, tmp_path):
        """令牌文件损坏 (半截 JSON) 时 load 返回 None 而不是抛异常。

        回归锚点: 上次异常退出可能留下写了一半的文件; 此处炸栈会让 CLI 每次启动都崩。
        """
        p = tmp_path / "tok.json"
        p.write_text("{broken", encoding="utf-8")  # 半截 JSON: 模拟上次异常退出留下的文件
        assert TokenStore(path=p).load() is None  # 损坏降级成未登录, 不许炸栈


class TestEnsureAccessToken:
    """ensure_access_token: token 过期恢复单点 (auth §5.5, 2026-09-30)。

    NADC 无 refresh_token, 过期后唯一合法续期是重走 Authorization Code
    流。本类钉住三件事: 有效 token 直通; 有交互通道时经 reauth 恢复并落盘;
    无交互通道时抛 TokenExpiredError (消息带恢复命令) 而不是把过期令牌
    当有效身份返回。
    """

    def test_valid_token_returned_directly(self, tmp_path):
        """有未过期 token 时原样返回, 不碰 reauth (零网络零交互)。"""
        store = TokenStore(path=tmp_path / "tok.json")                                              # 令牌文件路径由夹具给
        store.save({"access_token": "good", "expires_in": 3600})                                   # 长寿命令牌: 有效期内不该触发任何恢复流程
        assert ensure_access_token(store=store) == "good"  # 有效 token 直通: 不碰 reauth, 零交互

    def test_expired_token_recovered_via_reauth(self, tmp_path):
        """过期 + 提供 reauth: 走恢复回调, 新 token 落缓存后返回。"""
        store = TokenStore(path=tmp_path / "tok.json")                                              # 令牌文件路径由夹具给
        store.save({"access_token": "stale", "expires_in": -10})  # 负寿命: 免 sleep 造出过期态
        calls = {"n": 0}                                                                            # 调用计数: 用来证明只问了用户一次

        def reauth():
            """替身恢复流: 记一次调用, 回一枚 3600s 寿命的新令牌。"""
            calls["n"] += 1                                                                         # 先记一次调用
            return {"access_token": "fresh", "expires_in": 3600}

        assert ensure_access_token(store=store, reauth=reauth) == "fresh"                           # 恢复后应返回新令牌
        assert calls["n"] == 1  # 挡住每次调用都再问一次用户的实现
        # 恢复后的 token 必须落盘: 否则下次调用还要再问一次用户
        assert store.valid_token() == "fresh"                                                 # 恢复后的令牌必须落盘, 否则下次调用还要再问一次用户

    def test_expired_token_without_reauth_raises_with_command(self, tmp_path):
        """过期 + 无 reauth: 抛 TokenExpiredError, 消息带恢复命令。

        回归锚点: 无头批处理不能把过期令牌当有效凭据用 (那会让 401 晚一个
        任务周期才暴露); 消息里的命令是运维的唯一恢复入口, 必须可复制执行。
        """
        store = TokenStore(path=tmp_path / "tok.json")                                              # 令牌文件路径由夹具给
        store.save({"access_token": "stale", "expires_in": -10})
        with pytest.raises(TokenExpiredError, match="oauth login"):
            ensure_access_token(store=store)                                              # 不传 reauth 即无交互通道, 过期令牌只能抛错不能顶替

    def test_missing_token_without_reauth_raises(self, tmp_path):
        """从没有缓存时同样抛 TokenExpiredError (与过期同一恢复路径)。"""
        store = TokenStore(path=tmp_path / "absent.json")                                     # 指向一个不存在的文件: 与"已过期"是同一条恢复路径
        with pytest.raises(TokenExpiredError):                                              # 从未缓存与已过期共用同一条恢复路径, 上层只需认一个异常
            ensure_access_token(store=store)                                              # 无 reauth 时唯一合法出口就是抛错, 不返回任何令牌串

    def test_reauth_returning_bare_string_is_accepted(self, tmp_path):
        """reauth 允许返回裸 token 字符串 (调用方只拿得到 token 时)。"""
        store = TokenStore(path=tmp_path / "tok.json")                                              # 令牌文件路径由夹具给
        store.save({"access_token": "stale", "expires_in": -10})
        token = ensure_access_token(store=store, reauth=lambda: "bare-token")               # 返回裸字符串也要被接受: 调用方有时只拿得到 token
        assert token == "bare-token"
        assert store.load()["token_type"] == "Bearer"  # save 补齐的缺省字段

    def test_reauth_returning_garbage_raises_protocol_error(self, tmp_path):
        """reauth 返回的载荷没有 access_token: 抛 NadcOAuthError (不静默)。"""
        store = TokenStore(path=tmp_path / "tok.json")                                              # 令牌文件路径由夹具给
        store.save({"access_token": "stale", "expires_in": -10})
        with pytest.raises(NadcOAuthError, match="reauth"):
            ensure_access_token(store=store, reauth=lambda: {"nope": 1})


class TestManualPasteFlow:
    """手动粘贴兜底流: 回环 URL 输入、裸 code 输入、空输入拒绝。"""

    def test_callback_url_input(self, tmp_path):
        """用户把浏览器跳回的回调 URL 整个粘进来时, 要能从中抠出 code。

        回归锚点: 手动流是回环流被防火墙/无头环境挡住时的唯一兜底; 解析不出 code
        等于登录功能整体失效。
        """
        calls = {"n": 0}                                                                            # 调用计数: 断言令牌交换确实发生了一次

        # 替身 exchange_code: 断言抽出的 code 正确, 并回一枚可用令牌
        def fake_exchange(code, cid, sec, redirect, **kw):
            """替身令牌交换: 校验从回调 URL 里抠出的 code, 并回一枚可用令牌。

            Args:
                code: 生产代码从回调 URL 解析出的授权码。
                cid: client_id (替身不使用)。
                sec: client_secret (替身不使用)。
                redirect: 回调地址 (替身不使用)。
                **kw: 其余关键字参数占位。

            Note:
                这里断言 ``code == "the-code"`` 是整条用例的核心 — 从整段 URL
                里正确抠出 code 是手动粘贴流能工作的前提。
            """
            calls["n"] += 1                                                                         # 先记一次调用
            assert code == "the-code"  # 整条用例的核心: 从整段 URL 里正确抠出 code
            return {"access_token": "tok-x", "expires_in": 3600}

        # 替身 get_profile: 用令牌换回一个最小 profile
        def fake_profile(token, **kw):
            """替身 profile 获取: 忽略 token, 回一个最小可用的 profile 对象。"""
            return OAuthProfile(umt_id="U1", name="N")                                           # 最小可用 profile: 替身不必回完整结构

        with patch("src.auth.nadc_oauth.exchange_code", side_effect=fake_exchange), \
             patch("src.auth.nadc_oauth.get_profile", side_effect=fake_profile), \
             patch("src.auth.nadc_oauth.TokenStore") as store_cls:
            store_cls.return_value.save.return_value = {}                               # 手动流只验 profile 装配, 落盘形态由存储自己的用例负责
            profile = run_manual_paste_flow(                                                        # 走手动粘贴流
                "cid", "sec", "http://x/cb",
                "http://127.0.0.1:8765/callback?code=the-code&state=s")                  # 粘的是整段回调 URL: 能从中抠出 code 才是这条的意义
        assert profile.umt_id == "U1"                                                    # 抠出的 code 正确才换得到令牌, 也就才有 profile
        assert calls["n"] == 1                                                                  # 恰好换了一次: 多次说明重试了, 手动流不该重试

    def test_bare_code_input(self):
        """用户只贴裸 code (不带 URL) 时同样要能走完换 token + 取 profile。"""
        with patch("src.auth.nadc_oauth.exchange_code",                                             # 打桩换令牌, 按 code 分派
                   side_effect=lambda code, *a, **k: {"access_token": "t", "expires_in": 60}   # 只有裸 code 匹配才回令牌, 走错解析就换不到
                   if code == "bare" else {}), \
             patch("src.auth.nadc_oauth.get_profile",
                   side_effect=lambda token, **k: OAuthProfile(umt_id="U2")), \
             patch("src.auth.nadc_oauth.TokenStore"):
            profile = run_manual_paste_flow("cid", "sec", "http://x/cb", "bare")              # 只贴裸 code: 用户从地址栏只复制了参数值的情形
        assert profile.umt_id == "U2"

    def test_empty_input_raises(self):
        """空输入必须本地抛错, 不能拿空 code 去换 token。"""
        with pytest.raises(NadcOAuthError):                                                         # 空输入必须本地抛错
            run_manual_paste_flow("cid", "sec", "http://x/cb", "")


class TestLocalCallbackFlow:
    """本地回环流: state 校验 (CSRF) 与超时两条失败语义。"""

    def test_state_mismatch_rejected(self):
        """回环收到的 state 与本地生成值不一致时必须拒绝 (OAuth CSRF 防护)。

        回归锚点: 攻击者可用自己的 code 诱导受害者完成授权; state 不匹配就是拦这道
        攻击的唯一闸门, 且失败必须抛错而非静默放行。

        **B5 修复 (2026-10-07)**: 原实现有两个问题, 而且第二个让第一个彻底失效 ——
        **原实现的 ``pytest.raises(NadcOAuthError)`` 没有 ``match=``**, 而
        ``nadc_oauth.py`` 的端口绑定失败 (``:593``)、state 不匹配 (``:611``)、超时
        (``:613``) **抛的是同一个异常类型**。于是"CSRF 被拦"和"根本没跑起来"在断言
        上长得一模一样。
        **更要命的是它实际走的就是"根本没跑起来"那条路**: 原实现先用替身服务器占住
        ``port``, 再把这个同一端口传给 ``run_local_callback_flow``, 而后者第一件事
        就是 ``HTTPServer(("127.0.0.1", port), ...)`` ⇒ 端口被占 ⇒ 抛"无法绑定" ⇒
        用例照样绿。**CSRF 那道闸一行都没被执行过。** 删掉它, 51 条测试仍然全绿。
        现在的写法让生产代码自己起服务器, 用例再去敲它 —— 被测对象才是真正在跑。
        """
        # src.auth: NADC OAuth2.0 身份层 (仅 /jobs 需要)
        from src.auth import nadc_oauth  # 局部导入: 只有回环流两条要用

        # 先借一个内核分配的端口再立刻释放, 把号留给被测代码: 端口此刻是空的,
        # 所以 run_local_callback_flow 能真的绑定成功 —— 这是 CSRF 分支被执行的前提
        probe = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)  # 端口 0: 内核分配
        port = probe.server_address[1]                                                            # 取号
        probe.server_close()                                                                     # 立刻还回去 (close 后端口才可再绑)

        # 钉死 state 的生成值: 回调里带别的 state 就必然对不上 (CSRF 的攻击形态)
        with patch.object(nadc_oauth.secrets, "token_urlsafe", return_value="expected-state"):
            # 先把**真的** urlopen 存一份: 下面的探针要连本机回环端口, 不能被自己的
            # patch 拦掉 (拦掉就永远探不到"服务器起来了", 用例会假超时)。
            real_urlopen = urllib.request.urlopen
            # 第二道保险: 被测代码的任何**出网**请求当场炸。CSRF 闸一旦被摘掉, 它会
            # 拿着攻击者的 code 去真的换 token —— 那既是安全事故 (凭据外泄到测试进程),
            # 也是把用例变成一次真实外网往返 (实测负对照时它真的打到了 NADC 拿回 400)。
            # 这层 patch 让"闸被摘掉"表现为一个本地断言失败, 而不是一次真实鉴权请求。
            def _no_network(*a, **k):
                """回环流内任何出网请求都当场失败: CSRF 闸被摘掉时它就是第一个证据。"""
                raise AssertionError("CSRF 闸被摘掉后代码走到了出网点 (exchange_code/get_profile)")

            with patch("urllib.request.urlopen", side_effect=_no_network):
                outcome: dict[str, object] = {}                                            # 跨线程信箱: 线程内抛的异常带回主线程断言

                def _drive() -> None:
                    """在后台线程里跑回环流, 只把异常/结果收进 outcome。"""
                    try:
                        outcome["profile"] = nadc_oauth.run_local_callback_flow(
                            "cid", "sec", redirect_uri=f"http://127.0.0.1:{port}/callback",
                            port=port, open_browser=False, timeout=10)                          # 禁开浏览器: 无头环境不该拉真实浏览器
                    except Exception as exc:                                                    # noqa: BLE001 - 收进信箱由主线程断类型与消息
                        outcome["exc"] = exc

                worker = threading.Thread(target=_drive, daemon=True)                           # 守护线程: 断言完即回收
                worker.start()
                # 等回环服务器真的起来 (被测代码在子线程里绑端口, 主线程只能轮询端口)
                deadline = time.time() + 10                                                     # 与被测 timeout 同量级, 免得用例自己先超时
                while time.time() < deadline:
                    try:
                        real_urlopen(                                                         # 探针走真 urlopen: 本机回环不是出网
                            f"http://127.0.0.1:{port}/callback?code=attacker-code&state=WRONG",  # **错的 state** = 攻击形态
                            timeout=2)
                    except urllib.error.HTTPError:
                        break                                                                   # 连上了 (200, 故不是 HTTPError, 走这条属于防御性)
                    except Exception:
                        time.sleep(0.1)                                                          # 还没起来: 轮询
                        continue
                    else:
                        break                                                                   # 200: 服务器在服务, 回调已被它处理
                worker.join(timeout=15)                                                          # 收线程: 它要么被 CSRF 拒绝, 要么超时

        exc = outcome.get("exc")
        assert isinstance(exc, NadcOAuthError), f"回环流应因 CSRF 拒绝而抛错, 实得: {exc!r}"
        # match= 是这条用例的**核心**: 它把"CSRF 被拦"与"超时"/"端口被占"区分开。
        # 没有 match= 时, 这三条路径抛的都是 NadcOAuthError, 断言等于没写。
        assert "state mismatch" in str(exc), (
            f"必须命中 CSRF 分支 (state mismatch), 实得消息: {exc} —— "
            "若这里是超时或端口绑定失败, 说明 CSRF 那道闸根本没被执行到")
        assert "profile" not in outcome, "CSRF 拦截后绝不能还把 profile 当成功返回"

    def test_timeout_raises(self):
        """回环流等不到回调时必须超时抛错, 错误消息含中文"超时"。

        回归锚点: 用户中途关掉授权页是常态; 无超时会让人物永远挂在 accept 上。
        """
        # src.auth: NADC OAuth2.0 身份层 (仅 /jobs 需要)
        from src.auth import nadc_oauth

        with pytest.raises(NadcOAuthError, match="超时"):
            nadc_oauth.run_local_callback_flow(                                                   # 指向一个不会有人回调的端口, 制造"等不到"
                "cid", "sec", redirect_uri="http://127.0.0.1:1/callback",
                port=1, open_browser=False, timeout=1)                                         # 指向不会有人回调的端口, 用它制造"等不到"的超时


class TestLogoutUrl:
    """登出 URL 契约: 默认端点与带 WebServerURL 跳回参数两种形态。"""

    def test_logout_url(self):
        """登出 URL 契约: 默认端点 + 可选 WebServerURL 跳回参数。

        这两个形态是前端"退出登录"按钮直接拼的链接; 端点或参数名变了,
        用户点了退出却仍停留在已登出状态 (静默的功能失效)。
        """
        assert build_logout_url() == "https://oauth.china-vo.org/oauth/logout"  # 前端直接拼这个链接: 变了就是静默失效
        url = build_logout_url(web_server_url="https://app.example/")                               # 带跳回参数: 前端登出后要把用户送回应用
        assert "WebServerURL=https" in url                                                      # 参数名是前端契约: 拼错就是"点了退出却没退出"


class TestEnvContract:
    """环境变量名是运维脚本与文档的契约, 改名即破坏外部调用方。"""

    def test_env_names_stable(self):
        """环境变量名必须保持稳定 (``NADC_OAUTH_CLIENT_ID``/``_SECRET``)。

        这两个名字写进了部署文档与 CI secret 配置; 一旦在代码里改名,
        线上会以"凭据缺失"的形式失败, 而本地开发因为有自己的 env 完全无感 —
        属于最难排查的一类静默断裂。
        """
        assert ENV_CLIENT_ID == "NADC_OAUTH_CLIENT_ID"  # 名字进了部署文档与 CI secret: 改名即线上凭据缺失
        assert ENV_CLIENT_SECRET == "NADC_OAUTH_CLIENT_SECRET"
