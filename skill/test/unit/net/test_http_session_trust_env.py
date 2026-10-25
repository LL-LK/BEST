# -*- coding: utf-8 -*-
"""出网会话的 ``trust_env`` 锁定 — C2 / AO2-trust_env 的判据级红测试。

被测命题: **本仓任何出网会话都不从进程环境变量取代理配置**。

为什么值得单独立件: 审计在本仓反复撞到同一个形态 —— 「防御函数存在 ≠ 防御被调用」。
``requests.Session.trust_env`` 默认是 ``True`` (含义: 从环境变量取代理 / ``.env`` /
CA bundle / netrc), 而修复前全仓 ``trust_env`` **零命中**, 即三个客户端都在吃默认值。
后果不是少个便利功能: 本仓自己会读 ``.env`` 注入 ``ASTRO_BEST_PASSWORD``, 于是
"能影响进程环境"就等于"能改写带着口令的出网路由"。

因此本件断的是**接上了**, 不是**函数存在**:
  - 三个生产构造点各自断言 ``trust_env is False`` (证明调用链真的走了硬化出口);
  - AST 全仓普查, 任何绕过 :func:`src.http_session.build_session` 的裸
    ``requests.Session()`` 构造即判红 (证明没有"第二个入口");
  - 阳性对照: 显式 ``trust_env=True`` 确实能开口子, 证明前两条不是"把参数写死成
    不可能满足"的那种假断言。
"""
from __future__ import annotations

import ast  # AST 普查: 文本 grep 会被注释与 docstring 里的同名提及骗过
import os  # 环境变量: 证明代理变量确实存在, 断言不是空转
import sys  # sys.path 锚定
from pathlib import Path  # 路径拼装

import pytest  # 断言与异常

SKILL_ROOT = Path(__file__).resolve().parents[3]  # 仓根: 本件在 test/unit/net/ 下三级
if str(SKILL_ROOT) not in sys.path:  # 幂等: 让本件能 import src.*
    sys.path.insert(0, str(SKILL_ROOT))

from src.auth.session import BestAuth  # noqa: E402  三个生产构造点
from src.client import BestClient  # noqa: E402
from src.http_session import (  # noqa: E402
    KNOWN_CALL_SITES,
    TrustEnvError,
    assert_hardened,
    build_session,
)
from src.tap.client import BestTapClient  # noqa: E402

SRC_DIR = SKILL_ROOT / "src"  # AST 普查范围: 只管本仓出网代码


class TestSessionFactoryLocksTrustEnv:
    """工厂本身: 默认不信任环境, 且显式请求时确实能开口子。"""

    def test_default_session_refuses_environment(self):
        """默认产物必须 ``trust_env=False``。"""
        session = build_session()
        assert_hardened(session)  # 承重断言: 复用生产用的同一个判据, 免得两处口径漂移
        assert session.trust_env is False

    def test_explicit_opt_in_is_honoured(self):
        """阳性对照: ``trust_env=True`` 必须真的生效 —— 否则前一条是"写死参数"的假断言。"""
        session = build_session(trust_env=True)
        assert session.trust_env is True, "显式开口子必须生效, 否则信任环境的逃生阀是假的"

    def test_opt_in_is_rejected_by_the_hardened_assertion(self):
        """开口子的会话不该通过承重断言 —— 证明这条断言真的有牙。"""
        with pytest.raises(TrustEnvError, match="trust_env"):
            assert_hardened(build_session(trust_env=True))


class TestProductionClientsAreHardened:
    """三个生产构造点: 会话确实没在吃环境变量 (证明"防御被调用")。

    刻意**构造真实对象**而不是只测工厂: 只测工厂证明不了客户端真的走了那个出口,
    而"客户端自己 new 了一个默认 Session"正是修复前的真实状态。
    """

    def test_best_client_session_is_hardened(self):
        """``BestClient`` 持身的会话必须硬化 (它带查询凭据)。

        断言**就地写**而不只是调 ``assert_hardened``: 本仓的 TestsAuditor 按 AST 数
        断言, 只认落在测试函数体内的 ``ast.Assert`` —— 断言包在 helper 里会被判成
        「零断言测试」(MAJOR, 且整层判败)。这正是该审计器要抓的形态: 看起来在测,
        AST 上却证明不了任何事。所以 helper 与就地断言**同时**保留: helper 是生产
        代码与测试共用的同一判据, 就地断言是让扫描器看得见的证据。
        """
        session = BestClient().session
        assert_hardened(session)  # 复用生产判据: 免得测试与产品两处口径漂移
        assert session.trust_env is False, f"BestClient 会话 trust_env={session.trust_env}"

    def test_best_auth_session_is_hardened(self):
        """``BestAuth`` 持身的会话必须硬化 (它带站点口令, 风险最高)。"""
        session = BestAuth().session
        assert_hardened(session)
        assert session.trust_env is False, f"BestAuth 会话 trust_env={session.trust_env}"

    def test_tap_client_session_is_hardened(self):
        """``BestTapClient`` 持身的会话必须硬化 (它带 access token)。"""
        session = BestTapClient().session
        assert_hardened(session)
        assert session.trust_env is False, f"BestTapClient 会话 trust_env={session.trust_env}"

    def test_every_known_call_site_is_actually_covered(self):
        """新增构造点时必须同步登记 —— 清单与真实调用点脱钩就等于没守住。"""
        imported = {"src.client.BestClient", "src.auth.session.BestAuth", "src.tap.client.BestTapClient"}
        assert set(KNOWN_CALL_SITES) == imported, (
            f"KNOWN_CALL_SITES 与本件实测覆盖的构造点不一致: "
            f"登记 {sorted(KNOWN_CALL_SITES)} vs 实测 {sorted(imported)}"
        )


class TestNoBypassPathInSrc:
    """AST 全仓普查: 不许有绕过硬化出口的裸 ``requests.Session()`` 构造。"""

    def test_no_raw_session_construction_in_src(self):
        """``src/`` 下不得出现 ``requests.Session()`` / ``Session()`` 的直接构造。

        判据写成 AST 而非 grep: ``src/ai_tools.py`` 等模块的 docstring 里**合法**地
        讨论过 ``requests.Session`` 的语义, grep 会把它们误报成构造点。
        """
        offenders: list[str] = []
        for path in sorted(SRC_DIR.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            rel = path.relative_to(SKILL_ROOT).as_posix()
            if rel == "src/http_session.py":
                continue  # 工厂自己当然要 new: 它就是唯一被允许的构造点
            for node in ast.walk(tree):
                # 匹配两种形态: requests.Session(...) 与裸 Session(...)
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute) or func.attr != "Session":
                    continue
                owner = func.value
                is_requests = isinstance(owner, ast.Name) and owner.id == "requests"
                is_bare = isinstance(owner, ast.Name) and owner.id == "Session"
                if not (is_requests or is_bare):
                    continue  # 别的东西的 .Session() (如 ast.Session) 不归本判据
                if is_bare and path.name == "http_session.py":
                    continue
                offenders.append(f"{rel}:{node.lineno}")
        assert not offenders, (
            f"绕过 src.http_session.build_session 的裸会话构造: {offenders} —— "
            f"新构造点必须走硬化出口 (KNOWN_CALL_SITES 里登记), 否则 trust_env 又回到默认 True"
        )


class TestProxyEnvWouldOtherwiseHaveWorked:
    """阳性对照: 证明被封的确实是一条**可用**通道, 而不是本来就不通。

    没有这一组, 上面几条都可能在"代理变量压根不影响 requests"的误判下空转。
    """

    def test_proxy_env_var_is_actually_settable(self, monkeypatch):
        """环境里放一个代理变量, 且默认会话不受影响 (因为 trust_env=False)。"""
        # 用 monkeypatch 真放一个代理变量: 证明这条通道**存在且可注入**, 而被封的是
        # 会话不去读它 —— 否则上面几条都可能在"代理变量压根无效"的误判下空转。
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")  # 9 = discard 端口, 永不真连
        hardened = build_session()  # 默认: 不吃环境
        assert hardened.trust_env is False, "硬化会话必须与环境无关"
        assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:9", "代理变量确实已注入本进程环境"
        opened = build_session(trust_env=True)  # 显式开口子: requests 会据此配 proxies
        assert opened.trust_env is not hardened.trust_env, "两种模式必须真的不同, 否则本件在空转"
