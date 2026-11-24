"""src.auth.session — BEST 站点 Django 会话: 登录 / CSRF / 会话材料移交。

能力边界: BestAuth (Django session + CSRF 双重校验) 是 BEST 数据面 form 登录的唯一
实现, 与 src.auth.nadc_oauth (NADC 通行证 OAuth2.0) 构成**双轨制** — 本模块管数据
查询的 Django 会话 cookie, OAuth 层管身份 token, 互不替代 (BEST 数据查询只认
Django 会话)。边界: 凭据只从参数/env 流入, 代码内零字面量; 不做查询/下载/匹配。

拆分背景 (docs/architecture/file-size-budget.md §3.2): BestAuth 原与 BestClient
共处 src.client — 共处的理由是"认证态与客户端态是同一份 Django 会话",
BestClient.__init__ 要把 BestAuth 的 cookie 与 CSRF 头搬进自己的 session。落地拆分
后这条接线改为**显式移交**: BestClient.__init__ 只消费 export_session() 返回的会话
材料字典, 不再跨模块读取 BestAuth 的会话属性; src.client 保留
``from src.client import BestAuth`` 的 re-export, 既有 import 路径不受影响。

白盒锚点: references/ALGORITHM-SPEC.md §1/§2; contracts/io-contract.md。

【权威学术来源锚定】
  - NADC 中国虚拟天文台 (China-VO) BEST 数据库 REST API 规范 (2023): 登录态走
    Django session + CSRF 中间件 (GET 登录页取 csrf_token → POST 凭据), 公式定位:
    接口规范全文（§查询会话/codes）。规范引用（无 DOI）:
    https://nadc.china-vo.org/data/best 官方文档, 关联数据集 DOI 见
    docs/plans/doi_truth_registry.json —— 该文件与 docs/plans/ 目录在本仓
    均不存在, 此处只作历史注记, 不要当成可查的关联登记册。
  - 开源依赖: requests (Apache-2.0)。
Rule 9 状态: [VERIFIED_ALGO]（标准基准算法; 物理可解释输出, 无伪概率打分）。
"""
from __future__ import annotations

# 标准库: 日志 / csrf 正则 / 可选类型标注
import logging
import re
from typing import Optional

# 第三方: Django 会话载体 (服务端 cookie 与连接池都长在 requests.Session 上)
import requests

# 本地: 端点常量与单请求超时 (权威协议层单一事实源, 与 src.client 共享)
from src.protocol import BEST_BASE_URL, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)  # 模块级 logger: 登录/检查点类消息不带类名前缀


class BestAuth:
    """BEST 数据库认证处理器: Django session + CSRF token 双重校验。

    契约: 登录成功后 ``self.session`` 持有服务端 cookie, 可被多个
    ``BestClient`` 共享 (复制 cookie 与 CSRF 头); 登录失败不抛异常, 只把
    ``authenticated`` 置 False — 匿名可查的星表不应因登录失败而整体不可用。
    """

    def __init__(self, timeout: int = REQUEST_TIMEOUT) -> None:
        """构造未认证状态: 空 session、空 CSRF、未登录标志、无用户名。

        Args:
            timeout: 登录两个请求点的单请求超时 (秒)。缺省即协议层
                ``REQUEST_TIMEOUT``, 故未显式配置时行为与该常量逐字节一致;
                显式收窄即可让「单请求封顶」这条运维意图**也**覆盖认证路径
                (此前本类不收该参数, 登录页 GET 与登录 POST 恒用 120s,
                调用方把 ``BestClient(timeout=7)`` 调快也管不到这里)。

        Note:
            ``timeout`` 与 ``BestClient.request_timeout`` 是**两个独立旋钮**,
            各自在自己的构造点配置 (``BestClient`` 拿到的 ``BestAuth`` 实例
            是登录**之后**才移交进来的, 客户端无从回写认证侧的超时)。缺省
            同取 ``REQUEST_TIMEOUT``, 故两侧行为一致; 认证侧另给一个值不
            会波及查询侧。
        """
        self.session = requests.Session()  # 自持 session: cookie 与连接池随对象生死, 供 BestClient 共享
        self.csrf_token: Optional[str] = None  # 未取到即 None, 不用空串冒充"已取到"
        self._authenticated = False  # 构造即未认证: 匿名可查的星表不该因登录失败整体不可用
        self._username: Optional[str] = None  # 仅成功登录后写入, 不回显到日志之外的任何出口
        self.timeout = timeout  # 实例级单请求超时: 登录两个请求点经 request_timeout 统一取用

    @property
    def request_timeout(self) -> int:
        """本认证器实际生效的单请求超时 (秒): 登录两个出网请求点的唯一取值口。

        与 :attr:`src.client.BestClient.request_timeout` 同名同形 (刻意):
        「哪个超时生效」在两侧都只有一个取值口, 新增请求点只准取它, 不准
        再写协议层常量 (A2-02 同一条纪律的认证侧落地)。
        """
        return self.timeout  # 单一取值口: 缺省即 REQUEST_TIMEOUT, 未配置时行为不变

    @property
    def authenticated(self) -> bool:
        """当前 session 是否已认证 (property)。"""
        return self._authenticated

    def login(self, username: str, password: str) -> bool:
        """Django session 登录: 先取登录页拿 CSRF, 再 POST 凭据; 成功返回 True。

        契约: 凭据只从参数/env 流入, 代码内零字面量; 失败语义是"返回 False"
        而非抛异常 — 匿名可查的星表不应因登录失败而整体不可用, 是否降级由
        调用方决定。但失败**必须留 ERROR 日志** (见被拒分支): 静默的 False
        与"从未尝试登录"同形, 调用方会据此无声降级 (A4-01 fail-closed)。
        认证判定不看状态码 (站点登录成功/失败都可能回 200), 只看
        最终 URL 是否还停在 login 页。

        Args:
            username: BEST 站点用户名
            password: BEST 站点密码

        Returns:
            True 表示会话已认证 (``self._authenticated`` 同步更新)
        """
        login_url = f"{BEST_BASE_URL}/user/login"  # 端点取协议层常量: 登录页路径不在本模块私建第二份
        # 登录协议整体裹在网络异常保护里: docstring 声明的契约是「失败返回 False」,
        # 而网络抖动/超时是 requests.RequestException —— 不兜住就会把「登录失败」
        # 变成「调用方拿到一个异常」, 匿名可查星表因此整体不可用。
        try:
            # 登录协议第 1 步 (GET): Django 把 csrf_token 写在登录页里, 必须先取到
            # 才能 POST; 取页失败会在下一步 POST 的异常里暴露, 不在此处吞掉
            resp = self.session.get(login_url, timeout=self.request_timeout)  # 第一步取页只为拿 CSRF: 没有它提交凭据必被中间件拒; 超时取实例口径, 缺省即协议层常量
            self._extract_csrf(resp.text)  # 解析失败不抛: 让后续提交以 403 暴露真正的失败点
            # 登录协议第 2 步 (POST): 凭据 + csrf_token; Referer 头是 Django CSRF
            # 中间件校验项, next 指向 base_url 让服务端登录后重定向回站内而非外站
            resp = self.session.post(  # 第二步提交凭据: 会话 cookie 由此建立
                login_url,  # 同一个登录页地址: 站点按同一路由收发
                data={"username": username, "password": password, "csrf_token": self.csrf_token, "next": BEST_BASE_URL},  # 表单带上 CSRF 与回跳地址: 缺任一项都会被站点拒
                headers={"Referer": login_url},  # Referer 是 CSRF 中间件的校验项: 少了直接 403
                timeout=self.request_timeout,  # 超时取实例口径 (同 request_timeout 属性): 本类 __init__ 收 timeout, 故调用方配的值在这里**真的生效**; 缺省即 REQUEST_TIMEOUT, 未配置时逐字节不变。与 BestClient.request_timeout 是两个独立旋钮, 各自在自己的构造点配
            )
            # 登录后页面可能轮换 CSRF, 再取一次保持后续写请求可用
            self._extract_csrf(resp.text)  # 登录后令牌可能轮换: 再取一次保证后续写请求可用
        except requests.RequestException as e:
            # 降级即「未认证」, 与站点拒登同一出口: 调用方只判 authenticated 即可,
            # 不必为断网单开一条分支。用户名不留痕 (只成功时才写)。
            logger.error("Login request failed (network): %s", e)
            self._authenticated = False
            self._username = None
            return False
        # 认证判定: 登录成功会被重定向离 login 页; URL 仍含 "login" 即失败
        self._authenticated = "login" not in resp.url.lower()  # 只看最终 URL: 成功/失败都可能回 200
        if self._authenticated:  # 成功分支才记用户名: 失败时不该留下身份痕迹
            self._username = username  # 仅存于内存: 不回显到日志之外的任何出口
            logger.info("Logged in as %s", username)  # 惰性 %s 占位: 未登录分支不拼串
        else:
            self._username = None  # 失败即清身份: 复用同一 session 时不留上次痕迹
            # A4-01 (fail-closed): 被拒分支必须留痕。只返回 False 而不打日志时,
            # 「站点拒了这次凭据」与「调用方压根没尝试登录」在结果上完全同形 ——
            # 匿名回退因此静默发生, 且与一次纯匿名运行不可区分。
            logger.error(  # 错误级而非警告: 显式给凭据却登不进去是失败, 不是提示
                "Login rejected for %s: BEST kept the session on the login page "
                "(username or password incorrect); no retry is attempted and the "
                "caller decides whether to fall back to anonymous",
                username,  # 惰性 %s 占位: 成功分支不拼串, 失败分支不预拼
            )
        return self._authenticated

    def _extract_csrf(self, html: str) -> None:
        """从页面 HTML 提取 ``csrf_token="..."`` 并写入 session 的 X-CSRFToken 头。

        无匹配时静默保持原值: 站点改版导致取不到 token 时, 让后续 POST 以
        403 暴露真实失败点, 而不是在解析处抛异常掩盖"到底哪一步坏了"。
        """
        # 页面源码里 csrf_token 以字符串字面量出现; 取不到就沿用上一次的值
        m = re.search(r"csrf_token\s*=\s*\"([^\"]+)\"", html)  # 只认字符串字面量形态: 站点改版时宁可取不到也不误取
        if m:  # 无匹配就静默沿用旧值: 在解析处抛错会掩盖真正的失败点
            self.csrf_token = m.group(1)  # group(1) 是 token 本体, 不含引号
            self.session.headers.update({"X-CSRFToken": self.csrf_token})  # 同步进请求头, 后续写请求才带得上

    def export_session(self) -> dict:
        """导出 Django 会话材料 (cookie/CSRF/headers), 供 BestClient 显式移交。

        取代拆分前 "BestClient 直接读 ``auth.session.cookies`` / ``auth.csrf_token``"
        的跨模块私有读取: 会话材料经一个显式契约交出, 认证态的内部表示
        (``_authenticated``/``csrf_token``/``session``) 之后怎么改都不影响客户端。

        返回 dict, 四个键:
            authenticated: 当前是否已登录 (等价 ``self.authenticated``)
            cookies: ``requests`` cookie jar — **活引用** (与 ``self.session``
                同一对象, 非副本), 与拆分前的读取语义一致
            csrf_token: 当前 CSRF token; 未取到时为 None
            headers: 会话请求头 — **活引用** (``self.session.headers`` 本身,
                含 ``X-CSRFToken``), 调用方只应读取, 不透过它改写认证会话

        契约: 纯读取, 无网络 I/O、不改变任何状态, 可反复调用。调用方
        (:class:`src.client.BestClient` 的 ``__init__``) 只在 ``authenticated``
        为 True 时应用 cookie 与 ``X-CSRFToken`` 头, 且**不整体套用 headers:
        那会用 requests 的默认请求头覆盖客户端自己声明的 UA/Accept。
        """
        return {
            "authenticated": self._authenticated,  # 移交四键之一: 调用方据此决定要不要套用会话
            "cookies": self.session.cookies,  # 活引用而非副本: 与拆分前的读取语义一致
            "csrf_token": self.csrf_token,  # 未取到时为空值: 调用方不该把空串当成已取到
            "headers": self.session.headers,  # 活引用: 调用方只读, 透过去改会污染认证会话
        }

    def close(self) -> None:
        """释放 Django 会话占用的连接池 (幂等; 复用时无需调用)。

        ``BestAuth`` 自持一个 ``requests.Session`` (含 cookie 与连接池)。
        长生命周期进程 (MCP server、批处理脚本) 反复构造/丢弃认证对象时,
        不关闭会把 socket 留给 GC 回收时机, 表现为 "Too many open files"。
        """
        if hasattr(self, "session"):  # 幂等: 未构造完成就 close 不应炸
            self.session.close()  # 显式关池: 反复构造认证对象时把句柄留给回收会耗尽

    def __enter__(self) -> "BestAuth":
        """with 语法入口: ``with BestAuth() as auth:`` 退出时自动 close。"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """with 语法出口: 关闭会话, 异常继续向外传播 (不吞异常)。"""
        self.close()  # 出口只关会话: 刻意不吞异常, 查询失败要原样冒泡
        return
