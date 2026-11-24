# -*- coding: utf-8 -*-
"""A4-01 守门: 显式凭据被拒不得静默降级为匿名 (fail-closed)。

复过的现: ``src/__main__.py`` 丢弃 ``BestAuth.login()`` 的返回值, 被拒分支
一条日志都不打 (``src/auth/session.py``), 于是"错口令"与"压根没给凭据"
跑出来的结果完全同形 —— 退出码 0、数据照常返回、用户无从分辨。同函数里
"有用户名无口令"反而有 stderr 告警, 这条更严重的路径却沉默 (不对称)。

修复口径 (三条都要有断言):
  1. 显式给了凭据却登不进去 → stderr 明确报错 + 非零退出码, 且**不发查询**;
  2. 降级只由显式开关 ``--allow-anonymous-fallback`` 打开, 降级时必须打
     stderr 说明, 客户端拿到的 auth 必须是 None (不是被拒的会话);
  3. 压根没给凭据 → 匿名是用户主动选择, 照常执行 (合法路径不许被误伤);
  4. 认证层的被拒分支必须留 ERROR 日志 (库层的"失败"不能是无声的).

全部离线: BestAuth/BestClient 都被替身接管, 不打真实站点。
"""
from __future__ import annotations

# 标准库: 日志捕获 (认证层留痕的观测点) / 命令行参数注入 (CLI 入口的唯一输入)
import logging
import sys

# 第三方: pytest (测试发现) — 夹具与 caplog 都靠它
import pytest

# 本地: CLI 入口 (被测分派层) 与 Django 会话认证器 (被测认证层)
from src.__main__ import main
from src.auth.session import BestAuth

AUTH_ENV = "ASTRO_BEST_PASSWORD"  # 口令环境变量名: 与 src/__main__.AUTH_PASSWORD_ENV 同源, 写死在此只为替身注入


class _FakeAuth:
    """BestAuth 替身: 只如实回报"这次登录有没有成功"。

    刻意不碰 BestAuth 自身的实现 — 被拒语义由 :class:`_RejectedSession` 单独
    覆盖, 这里只验证 CLI 分派层有没有接住返回值。
    """

    def __init__(self, ok: bool) -> None:
        """记录构造次数并预置登录结果 (ok=False 即"站点拒了这次凭据")。"""
        self.ok = ok                          # 登录结果: 替身直接给出, 不做网络
        self.calls: list[tuple[str, str]] = []  # 登录入参留档: 断言凭据确实走过登录

    def login(self, username: str, password: str) -> bool:
        """假登录: 记账后返回预置结果 (真实语义由 BestAuth 保证)。"""
        self.calls.append((username, password))  # 记账: 断言走的是"真的尝试了登录"这条路
        return self.ok


class _FakeClient:
    """BestClient 替身: 只接住 auth, 供断言降级后拿到的是不是 None。"""

    def __init__(self, auth=None, **kwargs) -> None:
        """把构造入参存到类级列表: 断言要看"客户端拿到的凭据是什么"。"""
        self.auth = auth                      # 客户端实际拿到的认证对象 (None 即纯匿名)
        _FakeClient.seen.append(auth)         # 类级留档: 替身不能带实例状态进断言

    seen: list = []                           # 每次构造收到的 auth (顺序即调用顺序)


@pytest.fixture
def fake_auth_and_client(monkeypatch):
    """接管 BestAuth/BestClient: 让 CLI 分派层完全离线可测。

    Returns:
        ``(构造记录, auth 记录)`` 两个列表的元组, 供用例断言"登录有没有被
        尝试"与"客户端拿到了什么"。
    """
    built: list[_FakeAuth] = []              # BestAuth 构造记录: 断"压根没走登录"
    _FakeClient.seen = []                    # 每次用例重置: 类级状态不许跨用例泄漏

    def make_auth(ok: bool = False):
        """BestAuth 替身工厂: 默认登录失败 (显式错口令这一最危险的形态)。"""
        def _factory() -> _FakeAuth:
            """构造并记账: 断言要看客户端是否曾尝试登录。"""
            auth = _FakeAuth(ok)             # 预置登录结果
            built.append(auth)                # 记账: 走了登录这条路
            return auth
        return _factory

    monkeypatch.setattr("src.__main__.BestAuth", make_auth())  # 认证替身: 默认被拒
    monkeypatch.setattr("src.__main__.BestClient", _FakeClient)  # 客户端替身: 绝不打真实站点
    return built, _FakeClient.seen


def _run(monkeypatch, argv: list[str]) -> int:
    """以给定 argv 跑一次 CLI 入口 (口令从 env 注入, 不走 getpass)。"""
    monkeypatch.setenv(AUTH_ENV, "definitely-wrong-password")  # 非交互注入错口令: 走 env 通道即显式给出凭据
    monkeypatch.setattr(sys, "argv", ["astro-best", *argv])      # argv 是入口的唯一输入
    return main()                                               # 返回值即进程退出码


class TestRejectedCredentialsAreFailClosed:
    """显式凭据被拒: 默认必须是非零退出, 不是一次匿名成功运行。"""

    def test_wrong_password_exits_nonzero_and_never_queries(self, monkeypatch, fake_auth_and_client, capsys):
        """错口令 + 错用户名 → 退出码非 0, 且一次查询都不该发出去。"""
        built, client_seen = fake_auth_and_client  # 取替身记录: 断言走的是"试过登录才判失败"这条路

        code = _run(monkeypatch, ["--auth-user", "someone", "catalogs"])  # catalogs 不发查询: 只验分派层判失败

        assert code != 0, "凭据被拒却报 0 —— 这次运行与纯匿名运行不可区分 (A4-01 修过的现)"
        assert built and built[0].calls == [("someone", "definitely-wrong-password")], "登录必须真被尝试过, 否则这条用例没验到东西"
        assert client_seen == [], "凭据失败后仍构造了客户端 —— 降级必须是调用方显式同意的事"
        err = capsys.readouterr().err  # 只取 stderr: stdout 要留给机器可读结果
        assert "Error" in err and "login failed" in err, f"stderr 必须明说登录失败, 实际: {err!r}"

    def test_explicit_fallback_switch_allows_anonymous_with_warning(self, monkeypatch, fake_auth_and_client, capsys):
        """显式开关才允许降级, 且降级必须打 stderr、客户端拿到 None。"""
        _built, client_seen = fake_auth_and_client  # 只关心客户端最终拿到了什么

        code = _run(monkeypatch, [                                        # 开关与用户名都在主解析器上 (子命令之前)
            "--auth-user", "someone", "--allow-anonymous-fallback", "catalogs",
        ])

        assert code == 0, "显式同意降级后照常执行: 匿名可查星表不因登录失败整体不可用"
        assert client_seen == [None], f"降级必须传 auth=None, 实际: {client_seen!r}"
        err = capsys.readouterr().err  # 降级说明必须落在 stderr: stdout 仍是机器可读结果
        assert "continuing anonymously" in err, f"降级必须留痕, 实际: {err!r}"


class TestLegitimateAnonymousPathsSurvive:
    """未提供凭据的匿名路径是用户主动选择, 不许被上面的 fail-closed 误伤。"""

    def test_no_credentials_runs_anonymously(self, monkeypatch, fake_auth_and_client, capsys):
        """压根没给 --auth-user → 不构造 BestAuth, 客户端拿 None, 退出码 0。"""
        built, client_seen = fake_auth_and_client  # 记录要用来断言"没给用户名就不构造认证器"
        monkeypatch.setattr(sys, "argv", ["astro-best", "catalogs"])  # 只给子命令, 不给任何认证选项

        code = main()  # env 里即便有口令也不该自动登录: 没给用户名就不是登录请求

        assert code == 0, "没给凭据的匿名查询必须照常成功: 那是主动选择, 不是失败"
        assert built == [], "没给用户名就不该构造 BestAuth"
        assert client_seen == [None], f"匿名路径的客户端必须拿 None, 实际: {client_seen!r}"
        assert "login failed" not in capsys.readouterr().err, "匿名路径不该被误报成登录失败"

    def test_username_without_password_warns_and_continues(self, monkeypatch, fake_auth_and_client, capsys):
        """给了用户名却拿不到口令: 保留 stderr 告警 + 匿名继续 (references FB-2 契约)。"""
        built, client_seen = fake_auth_and_client  # 记录要用来断言"拿不到口令就不尝试登录"
        monkeypatch.delenv(AUTH_ENV, raising=False)  # env 无口令
        monkeypatch.setattr("src.__main__.sys.stdin", _FakeStdin(isatty=False))  # 非交互: 不得弹 getpass 提示
        monkeypatch.setattr(sys, "argv", ["astro-best", "--auth-user", "someone", "catalogs"])

        code = main()  # 半截凭据路径的唯一出口: 返回值即退出码

        assert code == 0, "半截凭据按匿名继续: 缺口令不等于登录失败 (只告警)"
        assert built == [], "拿不到口令就不该尝试登录"
        assert "no password" in capsys.readouterr().err, "缺口令必须告警, 不许无声降级"
        assert client_seen == [None], "缺口令路径同样传 auth=None"


class TestSessionRejectionLeavesATrail:
    """认证层自身: 被拒分支必须留 ERROR 日志, 不能只回一个 False。"""

    def test_rejected_login_logs_error(self, caplog):
        """登录页停留 = 被拒: 返回 False 且留下 ERROR 级记录。"""
        auth = BestAuth()  # 真实认证层: 只把网络替掉, 判据仍走真代码
        auth.session = _RejectedSession()  # 换掉真实 session: 全离线, 登录页原地不动

        with caplog.at_level(logging.ERROR, logger="src.auth.session"):
            ok = auth.login("someone", "definitely-wrong-password")  # 单次尝试, 不重试

        assert ok is False, "最终 URL 仍在 login 页即判失败 (成功/失败都可能回 200)"
        assert auth.authenticated is False, "被拒后认证态必须是假, 且不留旧身份"
        errors = [rec for rec in caplog.records if rec.levelno >= logging.ERROR]  # 只看 ERROR 级: 被拒不该只是提示
        assert errors, "被拒分支一条日志都不打 —— 调用方无从分辨'被拒'与'没试过'"
        assert "rejected" in errors[0].getMessage().lower(), "日志要说清是凭据被拒: " + errors[0].getMessage()


class _FakeStdin:
    """stdin 替身: 只回答 isatty, 用于钉住 getpass 分支。"""

    def __init__(self, isatty: bool) -> None:
        """预置 isatty 结果: True 走交互提示, False 走管道路径。"""
        self._isatty = isatty  # 决定 _resolve_password 走 getpass 还是管道分支

    def isatty(self) -> bool:
        """返回预置值: 决定 _resolve_password 是否弹隐形口令提示。"""
        return self._isatty


class _RejectedSession:
    """requests.Session 替身: 登录后仍停在 login 页 (站点拒了这次凭据)。"""

    headers: dict = {}  # 类级 headers: _extract_csrf 会往里写 X-CSRFToken

    def get(self, url: str, **kwargs):
        """GET 登录页: 回带 csrf_token 的 HTML, 让 POST 有机会发出去。"""
        return _Resp(url, 'csrf_token="tok-abc"')  # 有 token 才走到 POST: 无 token 时 403 是另一条失败路径

    def post(self, url: str, **kwargs):
        """POST 凭据: 站点拒登后把 URL 留在 login 页 (线上判定口径)。"""
        return _Resp(f"{url}?next=/", "csrf_token=\"tok-abc\"")  # URL 仍含 login → 被拒


class _Resp:
    """最小回包替身: 只需 url 与 text 供 login() 判定。"""

    def __init__(self, url: str, text: str) -> None:
        """记录最终 URL 与响应体: login() 只看这两样。"""
        self.url = url    # 认证判据就看它: 仍含 login 即失败
        self.text = text  # csrf 解析源
