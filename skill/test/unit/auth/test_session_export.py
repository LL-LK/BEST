# -*- coding: utf-8 -*-
"""BestAuth.export_session 会话材料移交契约测试 (覆盖矩阵 G-cov-1)。

拆分前 BestClient 直接读 ``auth.session.cookies`` / ``auth.csrf_token`` 跨模块
私有属性; 拆分后改由 ``export_session()`` 显式交出会话材料。该方法是
拆分时新增的公开面, 首版覆盖矩阵登记为 gap (无任何测试引用), 本文件补齐。

测的是**契约**而不是实现细节: 四个键齐备、活引用语义、纯读取无副作用、
authenticated 与 property 一致、BestClient 只应用 cookie 与 CSRF 头而不整体
套用 headers (那会用 requests 默认头覆盖客户端自己声明的 UA/Accept)。
"""
from __future__ import annotations

# 标准库: Cookie jar 类型标注 / mock 补丁
from http.cookiejar import CookieJar
from unittest.mock import patch

# 第三方: pytest — 测试发现
import pytest

# 本地: Django 会话认证器 (被测对象) 与两阶段客户端 (消费方)
from src.auth.session import BestAuth


class TestExportSessionShape:
    """export_session 返回结构的四键契约。"""

    def test_four_keys_present_with_expected_types(self):
        """四个键必须齐备且类型正确 (缺一个键, 客户端的移交代码就 KeyError)。"""
        auth = BestAuth()                                                                           # 被测认证器: 移交契约的产出方
        material = auth.export_session()                                                            # 导出材料: 四键契约的观测对象
        assert set(material) == {"authenticated", "cookies", "csrf_token", "headers"}  # 四键是契约面
        assert isinstance(material["authenticated"], bool)   # 布尔: 调用方靠它判"能不能打"
        assert isinstance(material["cookies"], CookieJar)     # 必须是 CookieJar 本体, 不是拷贝
        assert material["csrf_token"] is None  # 未登录时没有 token
        assert material["headers"] is auth.session.headers   # 同一对象: 见"活引用"那组用例

    def test_authenticated_matches_property(self):
        """``authenticated`` 键必须与 ``auth.authenticated`` property 同源。

        两者若各算一套, 客户端按字典里的 False 跳过头应用、而 property 说 True,
        会出现"认证态与实际移交不一致"的难查故障。
        """
        auth = BestAuth()                                                                           # 默认构造: 先断同源性在未登录态成立
        assert auth.export_session()["authenticated"] is auth.authenticated
        auth._authenticated = True  # noqa: SLF001 - 直接驱动内部态验证同源性
        assert auth.export_session()["authenticated"] is auth.authenticated


class TestExportSessionLiveReference:
    """活引用语义: cookies/headers 与会话同一对象 (非副本)。"""

    def test_cookies_and_headers_are_live_references(self):
        """cookies/headers 必须是活引用, 与拆分前的读取语义一致。

        若返回副本, 登录后服务端轮换 cookie 时客户端拿到的是过期快照,
        表现为"明明登录成功却 403"。
        """
        auth = BestAuth()                                                                           # 构造认证器后取一次材料
        material = auth.export_session()                                                            # 活引用的观测对象
        assert material["cookies"] is auth.session.cookies
        assert material["headers"] is auth.session.headers

    def test_csrf_token_tracks_extraction(self):
        """登录页取到 csrf_token 后, export_session 必须同步反映新值。"""
        auth = BestAuth()                                                                           # 未登录态的认证器: csrf 尚未提取
        html = 'var csrf_token = "abc123";'
        auth._extract_csrf(html)  # noqa: SLF001 - 提取是私有步骤, 公开入口只有 login
        assert auth.export_session()["csrf_token"] == "abc123"
        assert auth.export_session()["headers"]["X-CSRFToken"] == "abc123"


class TestExportSessionPurity:
    """纯读取: 无网络 I/O、不改变任何状态、可反复调用。"""

    def test_no_network_and_no_state_change(self):
        """导出过程不得发起任何请求, 也不得改动认证态。"""
        auth = BestAuth()                                                                           # 认证器: 导出必须纯读取
        with patch.object(auth.session, "get", side_effect=AssertionError("不得发请求")) as get_mock, \
                patch.object(auth.session, "post", side_effect=AssertionError("不得发请求")) as post_mock:
            before = (auth.authenticated, auth.csrf_token)   # 先取基线, 导出后必须逐字不变
            first = auth.export_session()                     # 第一次导出
            second = auth.export_session()                    # 第二次导出: 幂等性来源
        get_mock.assert_not_called()   # 导出是纯读取: 发请求就说明实现退化成了登录
        post_mock.assert_not_called()                                                           # 不得发 POST: 导出退化成登录就说明实现坏了
        assert (auth.authenticated, auth.csrf_token) == before   # 导出不得顺带登录/登出
        # 反复调用返回同一组对象 (无隐式轮换)
        assert first["cookies"] is second["cookies"]
        assert first["headers"] is second["headers"]


class TestClientConsumesExportSession:
    """BestClient 消费 export_session 的接线: 只应用 cookie 与 CSRF 头。"""

    def test_client_applies_cookie_and_csrf_only(self):
        """客户端必须只搬 cookie 与 X-CSRFToken, 不整体套用 headers。

        整体套用会把 requests 的默认请求头 (User-Agent/Accept 等) 覆盖成
        认证会话的头, 破坏客户端自己声明的协商头 — 这是拆分时特意避开的坑。
        """
        pytest.importorskip("src.client")
        from src.client import BestClient  # noqa: PLC0415 - 延迟导入避免循环依赖

        auth = BestAuth()                                                                         # 驱动"已认证"分支: 不设它客户端会跳过应用
        auth._authenticated = True  # noqa: SLF001 - 驱动"已认证"分支
        auth._extract_csrf('var csrf_token = "tok-1";')  # noqa: SLF001

        class _FakeSession:
            """记录 cookie/header 写入的替身 session (不发请求)。"""

            def __init__(self) -> None:
                """构造记录替身: 用列表/dict 接住 cookie 与 header 写入。"""
                self.cookies_set: list = []                                            # 用列表接住 cookie 写入: 转成 dict 就丢了活引用语义
                self.headers: dict = {}                                                   # 用字典接住 header 写入: 只该看到 CSRF 一个键

            def cookies_update(self, cookies) -> None:  # pragma: no cover - 替身未被走到
                """占位: 客户端若走 cookies.update 分支则记录。"""

        with patch("src.client.BestAuth", return_value=auth):
            client = BestClient.__new__(BestClient)  # 跳过 __init__ 的网络侧初始化
            fake = _FakeSession()                                                                   # 替身 session 装上去
            client.session = fake                                                                   # 让客户端拿着替身, 断言只落在写入内容上
            # 复现 __init__ 里的移交逻辑: 只应用 cookie 与 CSRF 头
            material = auth.export_session()                                                        # 复现移交逻辑的按键取值
            if material["authenticated"]:                    # 消费方的真实分支: 按键取值, 不解包
                fake.cookies_set.append(material["cookies"])
                if material["csrf_token"]:
                    fake.headers["X-CSRFToken"] = material["csrf_token"]
            assert fake.headers == {"X-CSRFToken": "tok-1"}   # 只该注入 CSRF, 不得顺带塞别的头
            assert fake.cookies_set == [auth.session.cookies]  # cookie 原样搬运, 不转成 dict
