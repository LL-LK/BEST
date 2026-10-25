# -*- coding: utf-8 -*-
"""src.http_session — 本仓构造 :class:`requests.Session` 的**唯一**出口。

职责边界: 只做"把一个默认配置的 ``requests.Session`` 变成**本仓认可**的会话"这一件事,
即锁定 ``trust_env=False``。连接池、重试、超时、认证头、限流一概不管 —— 那些分别归
``src.client`` / ``src.auth.session`` / ``src.tap.client`` 各自配置, 在这里统一一份
就等于把三处不同的连接需求压成一种。

为什么需要这个模块 (2026-10-07 安全修复, 审计编号 C2 / AO2-trust_env):
``requests`` 的 ``Session.trust_env`` 默认为 ``True``, 含义是"从**进程环境变量**里
取代理、``.env`` 凭据、CA bundle 与 netrc"。实测当时全仓 ``trust_env`` **零命中**,
即三个客户端都在吃这个默认值。后果是: 任何能影响进程环境的通道 —— 包括 ``.env``
(本仓自己会读它注入 ``ASTRO_BEST_PASSWORD``) —— 都能通过 ``HTTPS_PROXY`` 把
**全部出网流量**改道, 包括带着站点口令的那部分。这不是"少了个便利功能", 是
凭据的传输路径可被环境变量改写。

``trust_env=False`` 关掉的是整条"环境变量参与会话配置"的通道, 代价是**确实需要**
走代理的用户不再被自动照顾。刻意不自动读 ``HTTPS_PROXY``: 能被环境注入的量,
就不该再叠加一层到凭据的路由决定。真要连代理, 走 :func:`build_session` 的
``trust_env=True`` 显式开口子 —— 那是一个**要写进代码**的决定, 而不是环境一变就生效。

对外接口: :func:`build_session` 造一个会话; :func:`assert_hardened` 给判据级测试断言
用 (证明"防御存在"之外, "防御被调用" —— 见审计 §5.5 的「防御存在 ≠ 防御被调用」)。

依赖: 只用 ``requests``。不 import 被检查的业务代码, 不依赖 ``ROOT`` 定位。
"""
from __future__ import annotations

# 第三方: 会话构造本体 (本仓唯一的 HTTP 依赖)
import requests

# 本仓默认不信任进程环境的代理设置 —— 见模块 docstring「为什么需要这个模块」。
DEFAULT_TRUST_ENV = False  # False = 显式不信任; True 只应由调用方在代码里明确要求

# 已在生产路径上被核对过的构造点: 少一个就说明有客户端绕过了这个出口。
# 列在这里而不是靠 grep 兜底, 是因为 grep 只能证伪"曾经存在过", 证伪不了"新加的"。
KNOWN_CALL_SITES = (
    "src.client.BestClient",
    "src.auth.session.BestAuth",
    "src.tap.client.BestTapClient",
)


class TrustEnvError(RuntimeError):
    """会话仍在信任进程环境时抛出 (见 :func:`assert_hardened`)。"""


def build_session(*, trust_env: bool = DEFAULT_TRUST_ENV) -> requests.Session:
    """造一个**硬化过**的 :class:`requests.Session`。

    Args:
        trust_env: 是否让会话从进程环境变量取代理 / ``.env`` / CA bundle。默认
            :data:`DEFAULT_TRUST_ENV` (False)。传 True 是一句**写在代码里**的显式决定,
            与"环境一变就生效"有本质区别。

    Returns:
        已设好 ``trust_env`` 的会话; 调用方继续配置自己的重试/超时/头。
    """
    session = requests.Session()
    # 唯一实质动作: 关掉环境参与。注意不是 Session(trust_env=...) —— requests 的
    # Session.__init__ 不吃 kwargs, 只有属性可设, 写成构造参数会 TypeError。
    session.trust_env = trust_env
    return session


def assert_hardened(session: requests.Session) -> None:
    """断言会话确实没在吃环境变量 (判据级测试的承重断言)。

    为什么单独给一个函数: 审计里反复出现的形态是"防御函数存在、看着像修过,
    但**调用链上没人调**"。只测 ``build_session`` 证明不了三个客户端真的走了它;
    测这个断言, 等于要求每个生产构造点都留下证据。

    刻意用 ``raise`` 而不是 ``assert``: ``assert`` 在 ``python -O`` 下会被整条剥掉,
    那就等于给"生产环境不做这项检查"留了个默认口子; 而这条检查的价值恰恰在于
    它**永远**有效。

    Args:
        session: 待检查的会话。

    Raises:
        TrustEnvError: ``trust_env`` 仍为 True (即防御没被接上)。
    """
    if session.trust_env is not False:  # 显式比较 False 而非 falsy: None 也要判红
        raise TrustEnvError(
            f"会话仍在信任进程环境 (trust_env={session.trust_env}): "
            f"HTTPS_PROXY 等环境变量可改写出网路由, 进而带走凭据"
        )
