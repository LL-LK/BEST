"""src.tap.service — 基于标准库 http.server 的零依赖 IVOA TAP 网关。

能力边界: 把 src.tap 的解析/执行/序列化/UWS 存储暴露为标准 TAP HTTP 面:
GET|POST /tap/sync (doQuery), POST /tap/async (UWS 建单), /tap/async/{id}
(作业 XML/删除), /tap/async/{id}/phase (RUN/ABORT), /tap/async/{id}/results[/result]
(结果清单/结果文件, 支持 Range), 以及 VOSI /tap/availability 与 /tap/capabilities
与 TAP_SCHEMA /tap/tables。Bearer 校验失败一律 401, 严禁降级匿名 (历史回归
test_tap_query_rejects_invalid_bearer 钉死); MAXREC 按匿名/认证配额钳制。
边界: 只用标准库 http.server (不引 FastAPI/starlette — environment.yaml 无此
依赖); 执行走线程池 (jobs.py), 同步查询直接调用 executor; 入参大小/长度上限
由常量与 env 控制 (BEST_TAP_MAX_BODY_BYTES / BEST_TAP_MAX_QUERY_CHARS);
非 UTF-8 请求体转 400 错误文档, 不让解码异常冒到 socket 层把连接关成零响应。
白盒锚点: references/ALGORITHM-SPEC.md §6 (TAP 适配层锚点)。

历史来源: 路由语义逐条对应 pybest 打包产物 (git 6f00efeb^〔本仓历史已无此对象〕〔本仓历史已无此对象〕) ``pybest/tap/router.py`` +
``pybest/services/server.py`` 的 TAP 部分 (git 6f00efeb^〔本仓历史已无此对象〕); 传输层按本 skill
零重依赖原则用 stdlib 重写。IVOA TAP 1.1: ivo://ivoa.net/std/TAP; UWS:
ivo://ivoa.net/xml/UWS/v1.0 (规范引用, 无 DOI)。

基于标准库的零依赖 IVOA TAP 网关。
"""
from __future__ import annotations

import os  # 标准库: 读取配额/上限环境变量
import re  # 标准库: Range 头与作业路由匹配
from http.server import BaseHTTPRequestHandler, HTTPServer  # 标准库: HTTP 服务器骨架 (零框架)
from typing import Any, Callable, Optional  # 标准库: 类型标注
from urllib.parse import parse_qsl, urlparse  # 标准库: query/表单解析与路径拆解

# ElementTree 仅用于生成对外 XML, 绝不解析外部输入 (注入面为零)
from xml.etree import ElementTree as ET  # nosec B405

# 本地导入: 权威列名键集与星表展示名 — TAP_SCHEMA 与兜底列清单的数据源 (跨协议层能力边界)
from src.protocol import CATALOG_ALIASES, CATALOG_COLUMNS, CATALOG_DISPLAY

# 本地导入: ADQL 解析入口与错误类型 (跨解析能力边界)
from src.tap.adql import ADQLError, parse_adql

# 本地导入: 执行层与执行错误类型 (跨执行能力边界)
from src.tap.executor import TapExecutionError, TapExecutor

# 本地导入: 序列化层 — FORMAT 归一/结果序列化/VOTable 错误文档/截断头常量 (跨序列化能力边界)
from src.tap.formats import (  # 截断信号的头名与取值也归序列化层: 同步面与异步面据此同口径
    OVERFLOW_HEADER,
    OVERFLOW_VALUE,
    normalize_format,
    serialize_result,
    votable_error,
)

# 本地导入: UWS 作业存储类型 (建单装配用; 作业生命周期实现在 uws_service, 跨作业能力边界)
from src.tap.jobs import TapJobStore

# 本地导入: 响应载体 (触达 socket 之前的中间表示; 抽到独立模块以打破与
# uws_service 的循环依赖)。此处 re-export 保留既有
# ``from src.tap.service import TapResponse`` 一类调用路径。
from src.tap.response import TapResponse, xml_response

# UWS 作业生命周期已抽到 src.tap.uws_service; 此处导入保留既有
# ``from src.tap.service import TapUWSMixin`` 一类调用路径
from src.tap.uws_service import TapUWSMixin

DEFAULT_MAX_BODY_BYTES = 1048576     # 请求体大小上限 (env BEST_TAP_MAX_BODY_BYTES 覆盖): 防大表单打爆内存
DEFAULT_MAX_QUERY_CHARS = 100000     # QUERY 长度上限 (env BEST_TAP_MAX_QUERY_CHARS 覆盖): 防超长文本进解析器
DEFAULT_ANON_MAXREC = 1000           # 匿名 MAXREC 配额 (env BEST_TAP_ANON_MAXREC 覆盖): 未认证调用方的行数钳制
DEFAULT_AUTH_MAXREC = 50000          # 认证 MAXREC 配额 (env BEST_TAP_AUTH_MAXREC 覆盖): Bearer 通过后的行数钳制


def _xml_response(root: ET.Element, media_type: str = "application/xml") -> TapResponse:
    """把 ElementTree 根节点序列化为 200 XML 响应 (VOSI/UWS 文档出口)。

    实现委托 ``src.tap.response.xml_response``; 保留本名是为了不破坏
    ``service._xml_response`` 这个既有调用点。
    """
    return xml_response(root, media_type)  # 薄转发: XML 声明与编码规则不在本模块复写


def _tap_error(message: str, status_code: int = 400) -> TapResponse:
    """TAP 软错误: 以 VOTable 错误文档承载消息 (默认 400, 配额类传 429)。"""
    return TapResponse(
        status=status_code,  # 状态码由调用点定: 参数错 400 / 超限 413 / 配额 429
        body=votable_error(message),  # 消息由 ElementTree 负责 XML 转义
        media_type="application/x-votable+xml",  # DALI 要求错误也走结果文档形态
    )


def _env_int(name: str, default: int) -> int:
    """读整数环境变量; 缺失/空白/非法值一律回退默认 (不因配置打崩网关)。"""
    try:
        return int(os.environ.get(name, "").strip() or default)  # 纯空白串等价于未设置
    except ValueError:
        return default  # 配置写错不该让网关起不来: 回默认并继续服务


class TapGateway(TapUWSMixin):
    """把 TAP 请求分发到执行器/作业存储 (自身不碰 socket)。

    每个公开方法都返回 :class:`TapResponse`, 因此路由逻辑可在不绑定端口的
    情况下单测; :class:`TapRequestHandler` 是围绕 :meth:`handle` 的薄 socket
    适配层。
    """

    def __init__(
        self,                                                                                      # 实例: 网关只做路由与配额, 不自己发请求
        executor: TapExecutor,                                                                      # 执行器: 同步查询与作业线程共用同一份
        *,                                                                                    # 关键字参数: 后面几项都是可选配额, 位置传参易错位
        job_store: Optional[TapJobStore] = None,                                                 # 作业存储可空: 未配置时异步路由一律回 503
        anonymous_maxrec: Optional[int] = None,                                                # 匿名行数上限: 缺省读环境变量, 再缺省用模块常量
        authenticated_maxrec: Optional[int] = None,                                             # 认证行数上限: 认证侧走独立配额, 不与匿名共用
        max_query_chars: Optional[int] = None,                                                   # 查询串长度上限: 缺省读环境变量, 下限被钳住
        max_body_bytes: Optional[int] = None,                                                      # 请求体上限: 缺省读环境变量, 下限被钳住
        token_validator: Optional[Callable[[str], bool]] = None,                                  # 令牌校验回调可空: 未配置时任何令牌都判无效
    ) -> None:
        """装配网关: 注入执行器/作业存储与各项配额上限。

        Args:
            executor: 同步查询与作业线程共用的执行器。
            job_store: UWS 存储; 为 None 时 async 路由返回 503 (未配置)。
            anonymous_maxrec: 匿名 MAXREC 上限 (缺省读 ``BEST_TAP_ANON_MAXREC``)。
            authenticated_maxrec: 认证 MAXREC 上限 (缺省读 ``BEST_TAP_AUTH_MAXREC``)。
            max_query_chars: QUERY 长度上限 (缺省读 ``BEST_TAP_MAX_QUERY_CHARS``,
                下限钳到 1024)。
            max_body_bytes: 请求体上限 (缺省读 ``BEST_TAP_MAX_BODY_BYTES``,
                下限钳到 1024)。
            token_validator: Bearer token 校验回调; 为 None 时任何 token 都
                判无效 (401), 绝不因此放行匿名。
        """
        self.executor = executor  # 同步查询与作业线程共用同一执行器 (线程池在此)
        self.job_store = job_store  # None 即未配置 UWS: async 路由一律回 503
        self.anonymous_maxrec = int(  # 显式入参优先, 否则读 env, 再否则用模块常量
            anonymous_maxrec                                                                       # 显式入参优先: 没给才读环境变量与模块常量
            if anonymous_maxrec is not None                                                        # 三者取首个非空: 避免环境变量被默认值覆盖
            else _env_int("BEST_TAP_ANON_MAXREC", DEFAULT_ANON_MAXREC)
        )
        self.authenticated_maxrec = int(  # 同上口径, 但走认证侧的独立配额
            authenticated_maxrec                                                                  # 认证侧同口径: 但配额值独立, 不与匿名共享
            if authenticated_maxrec is not None                                                     # 三者取首个非空: 同上
            else _env_int("BEST_TAP_AUTH_MAXREC", DEFAULT_AUTH_MAXREC)
        )
        self.max_query_chars = max(  # 下限钳到 1024: 0/负数会让所有查询被拒
            1024,                                                                           # 下限 1024 写死: 零或负的长度上限会让所有查询被拒
            int(max_query_chars if max_query_chars is not None                                      # 入参为真才用入参: 否则读环境变量
                else _env_int("BEST_TAP_MAX_QUERY_CHARS", DEFAULT_MAX_QUERY_CHARS)),
        )
        self.max_body_bytes = max(  # 同上钳位理由: 请求体上限为 0 等于网关全拒
            1024,                                                                              # 下限 1024 写死: 请求体上限为零等于网关全拒
            int(max_body_bytes if max_body_bytes is not None                                        # 入参为真才用入参: 同上
                else _env_int("BEST_TAP_MAX_BODY_BYTES", DEFAULT_MAX_BODY_BYTES)),
        )
        self.token_validator = token_validator  # None 时任何 token 都判无效 (401), 不放行匿名

    # -- 认证 ---------------------------------------------------------------

    def _authenticate(self, headers: dict[str, str]) -> tuple[bool, Optional[TapResponse]]:
        """解析 Authorization 头, 返回 (是否认证, 错误响应)。

        Bearer token 存在但非法是硬 401 — 绝不静默降级到匿名配额 (回归
        test_tap_query_rejects_invalid_bearer 钉死: 降级会让限流形同虚设)。
        头缺失视为匿名; 头格式不符 (非 ``Bearer <token>``) 同样是 401。
        """
        header = headers.get("Authorization") or headers.get("authorization") or ""  # 大小写两种拼法都收
        if not header.strip():                                                                    # 无头即匿名: 由配额侧钳制, 不在此直接拒绝
            return False, None  # 无头 = 匿名, 由配额侧钳制而非直接拒绝
        match = re.fullmatch(r"Bearer\s+(\S+)", header.strip(), flags=re.IGNORECASE)  # 整体匹配, 不吃尾随内容
        if not match:                                                                       # 格式不符即 401: 静默降级到匿名配额会让限流形同虚设
            return False, TapResponse(status=401, body=b"Malformed Authorization header",
                                      media_type="text/plain; charset=utf-8")  # 格式错同样 401, 不降级
        token = match.group(1)  # 正则只捕获 token 本体, 不含 "Bearer " 前缀
        validator = self.token_validator  # 取出回调: 未配置时下面的校验必然失败
        if validator is None or not validator(token):                                            # 校验器缺失或判否都拒: 绝不因未配置而放行匿名
            return False, TapResponse(status=401, body=b"Invalid bearer token",
                                      media_type="text/plain; charset=utf-8")  # 非法 token 硬拒绝, 不落匿名配额
        return True, None  # (通过, 无错误响应) —— 后续路由据此选配额

    # -- 路由分发 ------------------------------------------------------------

    def handle(
        self,                                                                                       # 实例: 网关对象
        method: str,                                                                   # 请求方法: 参与路由, 同一路由的 GET 与 POST 语义相同
        path: str,                                                                              # 完整请求路径: 允许任意前缀, 便于挂在反代后面
        *,                                                                                          # 关键字参数: 入参面一律写全名
        params: dict[str, str],                                                                   # 已大写归一的参数: 大小写不敏感由归一层负责
        headers: dict[str, str],                                                                    # 请求头: 认证判定要读它
        body: bytes = b"",                                                                         # 请求体: 只在 POST 路径被解析成表单
        client_host: str = "unknown",
    ) -> TapResponse:
        """分发一个请求; ``path`` 是完整请求路径 (允许任意前缀)。

        TAP 参数名大小写不敏感 (DALI): 键统一大写归一, 使 socket 适配器与
        直接调用方行为一致。路径若不以 ``/tap`` 开头会补上, 兼容把网关挂在
        子路径/反代后面的部署。
        """
        params = {str(key).upper(): value for key, value in params.items()}                       # 参数键统一大写: 规范要求参数名大小写不敏感
        route = urlparse(path).path                                                                 # 只取路径段: 查询串已在入参侧解析过一次
        if not route.startswith("/tap"):
            route = "/tap" + route if route.startswith("/") else "/tap/" + route
        tail = route[len("/tap"):] or "/"

        # 认证先行: 任何路由 (含 VOSI) 都先过 Bearer 校验, 失败即 401 返回
        authenticated, auth_error = self._authenticate(headers)                                  # 认证先行: 任何路由含服务信息类都要先过这一关
        if auth_error is not None:                                                                  # 有错误响应即返回: 不进任何业务路由
            return auth_error

        if method == "GET" and tail == "/availability":
            return self._availability()
        if method == "GET" and tail == "/capabilities":
            return self._capabilities(headers)
        if method == "GET" and tail == "/tables":
            return self._tables()
        if method in ("GET", "POST") and tail == "/sync":
            return self._sync(method, params, authenticated)
        if tail == "/async" or tail == "/async/":
            if method == "POST":
                return self._create_async_job(params, authenticated, client_host)
            return TapResponse(status=405, body=b"POST required", media_type="text/plain")

        job_match = re.fullmatch(r"/async/([A-Za-z0-9_-]+)(/phase|/results|/results/result)?", tail)
        if job_match:                                                                          # 作业路径匹配: 白名单字符集, 免得路径被当任意串
            job_id, action = job_match.group(1), job_match.group(2) or ""
            return self._async_action(
                method, job_id, action, params, client_host,                                        # 方法与参数整份下传: 动作语义由作业层判
                authenticated=authenticated, headers=headers,                                    # 认证位与请求头同传: 配额与鉴权都在作业层要用
            )
        return TapResponse(status=404, body=b"Not Found", media_type="text/plain")

    # -- VOSI / TAP_SCHEMA ---------------------------------------------------

    def _availability(self) -> TapResponse:
        """VOSI availability: 网关常报可用 (可用性由上游 BEST 决定, 不在此探活)。"""
        root = ET.Element("{http://www.ivoa.net/xml/VOSIAvailability/v1.0}availability")
        ET.SubElement(root, "available").text = "true"
        ET.SubElement(root, "note").text = "astro-best TAP gateway is available"
        return _xml_response(root)

    def _capabilities(self, headers: dict[str, str]) -> TapResponse:
        """VOSI capabilities: 声明 TAP 标准 ID 与 sync/async 两个 accessURL。

        base URL 优先取请求 Host 头, scheme 由 ``X-Forwarded-Proto`` 推断
        (反代终结 TLS 时 clients 才能拿到 https 入口); 两者都缺时退回本机
        回环地址, 保证文档始终可生成。
        """
        host = headers.get("Host") or headers.get("host") or "127.0.0.1"
        scheme = "https" if headers.get("X-Forwarded-Proto") == "https" else "http"
        base = f"{scheme}://{host}".rstrip("/")
        root = ET.Element("{http://www.ivoa.net/xml/VOSICapabilities/v1.0}capabilities")
        capability = ET.SubElement(root, "capability", {"standardID": "ivo://ivoa.net/std/TAP"})
        for kind in ("sync", "async"):
            interface = ET.SubElement(capability, "interface", {"role": "std", "version": "1.1"})
            ET.SubElement(interface, "accessURL", {"use": "full"}).text = f"{base}/tap/{kind}"
        return _xml_response(root)

    def _tables(self) -> TapResponse:
        """TAP_SCHEMA tables: 按权威键集枚举 best 模式下全部星表与列。"""
        root = ET.Element("{http://www.ivoa.net/xml/VODataService/v1.1}tableset")
        schema = ET.SubElement(root, "schema")
        ET.SubElement(schema, "name").text = "best"
        ET.SubElement(schema, "description").text = "BEst STar database"
        for catalog, label in CATALOG_DISPLAY.items():                                           # 逐星表枚举: 表清单来自注册表, 不额外发请求
            table = ET.SubElement(schema, "table", {"type": "table"})
            ET.SubElement(table, "name").text = f"best.{catalog}"
            ET.SubElement(table, "description").text = label
            for column_name in CATALOG_COLUMNS.get(                                                # 逐表取列: catalog 来自 CATALOG_DISPLAY, 已是规范 id
                    CATALOG_ALIASES.get(catalog, catalog), ()):                                     # 防御性归一: DISPLAY 与别名键集不相交, 当前恒为恒等映射
                column = ET.SubElement(table, "column")
                ET.SubElement(column, "name").text = column_name
                data_type = ET.SubElement(column, "dataType", {"arraysize": "*"})
                data_type.text = "char"
        return _xml_response(root)

    # -- 同步查询 ----------------------------------------------------------

    def _check_common_query_params(self, params: dict[str, str]) -> tuple[str, str, TapResponse | None]:
        """校验 REQUEST/LANG/QUERY/FORMAT, 返回 (query, format, 错误响应)。

        sync 与 async 建单共用同一套校验; 任一项不满足即返回 VOTable 错误
        文档 (软错误, 不抛异常), 由调用方直接作为 HTTP 响应。
        """
        request_name = params.get("REQUEST", "doQuery")
        if request_name.lower() != "doquery":
            return "", "", _tap_error("REQUEST must be doQuery")
        if params.get("LANG", "ADQL").upper() != "ADQL":
            return "", "", _tap_error("Only LANG=ADQL is supported")
        query = params.get("QUERY", "").strip()
        if not query:                                                                         # 查询串为空即拒: TAP 规范要求 QUERY 必填
            return "", "", _tap_error("QUERY is required")
        if len(query) > self.max_query_chars:                                                    # 超长即拒: 长度上限在此生效, 不等解析器兜底
            return "", "", _tap_error("QUERY is too long")
        try:
            output_format = normalize_format(params.get("FORMAT"))
        except ValueError as exc:
            return "", "", _tap_error(str(exc))
        return query, output_format, None

    def _maxrec(self, params: dict[str, str], authenticated: bool) -> tuple[int, TapResponse | None]:
        """解析 MAXREC 并按认证状态钳到配额上限 (取 min, 不放大请求值)。

        Returns:
            tuple[int, TapResponse | None]: (生效 MAXREC, 错误响应);
                MAXREC 非整数/负数时错误响应非 None 且第一项为 0。
        """
        try:
            maxrec = int(params.get("MAXREC", "1000"))
        except ValueError:
            return 0, _tap_error("MAXREC must be an integer")
        if maxrec < 0:                                                                             # 负数即拒: 负上限会让后端按倒数第几行解释
            return 0, _tap_error("MAXREC must be non-negative")
        quota = self.authenticated_maxrec if authenticated else self.anonymous_maxrec             # 按认证状态选配额: 匿名与认证是两条独立上限
        return min(maxrec, quota), None

    def _sync(self, method: str, params: dict[str, str], authenticated: bool) -> TapResponse:
        """同步 doQuery: 校验 → 解析 → 执行 (带溢出探测) → 序列化 → 200。

        ``method`` 参与路由但 GET/POST 语义相同 (DALI 允许表单或 query 串);
        截断时附 ``X-TAP-Overflow: true`` 响应头, 并始终带
        Content-Disposition 便于客户端按扩展名存盘。
        """
        query, output_format, error = self._check_common_query_params(params)                   # 先校验公共参数: 解析之前就把明显非法的请求挡掉
        if error is not None:                                                                       # 有错误文档即返回: 软错误不抛异常
            return error
        maxrec, error = self._maxrec(params, authenticated)                                       # 再定生效行数上限: 与查询参数校验同一优先级
        if error is not None:                                                                     # 有错误文档即返回: 配额类失败同样回错误文档
            return error
        try:
            plan = parse_adql(query)                                                                # 解析查询串: 越界子集在此抛错
            rows, overflow = self.executor.execute_with_overflow(plan, max_rows=maxrec)             # 带溢出探测执行: 多取一行判断是否被截断
            result = serialize_result(                                                              # 序列化结果: 格式由公共参数校验决定
                rows,                                                                              # 行与格式按位传: 与序列化实现签名逐位对齐
                output_format,
                columns=plan.columns or CATALOG_COLUMNS.get(                                      # 无投影则用登记列: 查询串没写列时回落到全列
                    CATALOG_ALIASES.get(plan.catalog, plan.catalog), ()),                           # 防御性归一: plan.catalog 已过 adql 白名单, 恒为规范 id
                overflow=overflow,                                                                  # 溢出位: 有则让调用方知道结果被截断
            )
        except (ADQLError, TapExecutionError, ValueError, UnicodeError) as exc:
            # 软错误: 解析/执行/参数类失败全部转 VOTable 错误文档, 不泄露堆栈
            return _tap_error(str(exc))
        headers = {"Content-Disposition": f'attachment; filename="tap-result{result.extension}"'}
        if overflow:                                                                                # 有溢出才加头: 干净结果不挂截断提示
            headers[OVERFLOW_HEADER] = OVERFLOW_VALUE  # 头名取共享常量: 异步结果面挂的是同一个, 两面同口径
        return TapResponse(status=200, body=result.body, media_type=result.media_type, headers=headers)


class TapRequestHandler(BaseHTTPRequestHandler):
    """Socket 适配器: 解析 HTTP 请求, 委托给 :class:`TapGateway`。

    只做协议层事务 (读请求行/头/体, 写状态行/响应头/响应体), 不含任何路由
    或业务逻辑; 业务决策全部来自 gateway.handle 返回的 :class:`TapResponse`。
    """

    server: "TapHTTPServer"
    protocol_version = "HTTP/1.1"

    def _dispatch(self, method: str) -> None:
        """把一个 HTTP 方法的事务完整跑一遍 (读入参 → 委托网关 → 写响应)。"""
        parsed = urlparse(self.path)                                                               # 拆出路径与查询串: 参数从查询串这一侧解析
        params = {key.upper(): value for key, value in parse_qsl(parsed.query, keep_blank_values=True)}  # 查询串键大写归一: 与网关层同一口径
        body = b""                                                                                  # 体初始化为空: 只有 POST 才会被填
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)  # 缺失按 0 处理, 不让坏头炸解析
            gateway = self.server.gateway                                                      # 网关取自服务器: 处理器只做协议事务, 业务在网关
            if length > gateway.max_body_bytes:                                               # 按声明长度先拒: 读之前就拦, 不把超大表单读进内存
                # 请求体超限: 在读之前就按 413 拒掉, 避免把超大表单读进内存
                self._send(_tap_error("TAP request body is too large", 413))
                return
            body = self.rfile.read(length) if length else b""                                     # 按声明长度读: 零长度不读, 免得阻塞在读上
            if len(body) > gateway.max_body_bytes:                                                  # 再按实际字节拒: 声明长度未必等于实际字节
                # Content-Length 二次防线: 实际字节仍可能超限。唯一真能走到这里的
                # 是声明长度 < 实际字节的情形 —— 实测 (回环真跑) 只有
                # ``Content-Length: -1`` 会让 rfile.read(-1) 读到 EOF 而超出上限
                # (如上限 1MB、真体 3MB -> 本分支发 413)。正数声明下 read(n) 至多
                # 返回 n 字节, 故这层在正数路径上是冗余的, 但负数哨兵合法可达,
                # 删掉它等于给 ``-1`` 开一个读满全连接的口子。
                self._send(_tap_error("TAP request body is too large", 413))
                return
            try:
                # 表单体必须是 UTF-8: 非法字节序列在 strict 下抛 UnicodeDecodeError,
                # 那个异常会一路冒到 socketserver 的 handle_error —— 连接被直接关掉,
                # 客户端拿到零 HTTP 响应 (连状态码都没有), 排障时与"服务崩了"同形。
                # 这里显式转 400: 非 UTF-8 体就是参数非法, 与本模块"软错误不抛
                # 异常, 转错误文档"的契约一致 (同 _sync 的 ADQLError 分支)。
                form_text = body.decode("utf-8", "strict")
            except UnicodeDecodeError:
                # 400 而非 500: 请求本身不合法, 不是网关自己坏了; 错误文档沿用
                # VOTable 形态, 与其余 4xx 一致, 客户端的解析分支不必再开一个
                self._send(_tap_error("TAP request body is not valid UTF-8"))
                return
            params.update(  # 表单键大写归一: 与查询串参数同一套键名口径
                {key.upper(): value for key, value in parse_qsl(form_text, keep_blank_values=True)}
            )
        headers = {key: value for key, value in self.headers.items()}                               # 请求头原样拷贝: 认证判定要读它们
        response = self.server.gateway.handle(                                                      # 整笔交给网关: 处理器不含任何业务决策
            method,                                                                                 # 方法按位传: 网关按方法分流路由
            self.path,                                                                              # 路径原样传: 前缀兼容由网关负责
            params=params,                                                                        # 参数表传入: 已大写归一, 网关不再重复处理
            headers=headers,                                                                        # 请求头传入: 认证在网关侧完成
            body=body,                                                                              # 体传入: 作业动作可能要用
            client_host=self.client_address[0] if self.client_address else "unknown",
        )
        self._send(response)

    def _send(self, response: TapResponse) -> None:
        """把 TapResponse 写回 socket (状态行 → 响应头 → 响应体)。"""
        self.send_response(response.status)                                                        # 先写状态行: 响应先落状态码, 再落头与体
        self.send_header("Content-Type", response.media_type)
        self.send_header("Content-Length", str(len(response.body)))
        for key, value in response.headers.items():                                          # 逐个头字段回写: 网关附加的溢出头与下载名都靠这条出去
            self.send_header(key, value)                                                            # 头值原样写: 不在协议层改写网关的决定
        self.end_headers()                                                                        # 头写完才写体: 顺序反了客户端会读到残缺响应
        if self.command != "HEAD":
            self.wfile.write(response.body)                                                        # HEAD 不写体: 头要写, 体按协议不发

    def do_GET(self) -> None:  # noqa: N802 - 方法名由 stdlib 处理契约决定
        """处理 GET: 委托给网关 (含 VOSI/sync/作业查询)。"""
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802 (同上: stdlib 处理契约)
        """处理 POST: 委托给网关 (请求体按 application/x-www-form-urlencoded 解析)。"""
        self._dispatch("POST")

    def do_DELETE(self) -> None:  # noqa: N802 (同上: stdlib 处理契约)
        """处理 DELETE: 委托给网关 (UWS 删作业)。"""
        self._dispatch("DELETE")

    def log_message(self, _format: str, *args: Any) -> None:
        """静音 stdlib 请求日志 (日志归属由调用方决定)。"""
        return  # 静音: 网关日志由调用方决定


class TapHTTPServer(HTTPServer):
    """承载 :class:`TapGateway` 实例的 http.server (socket 生命周期归调用方)。"""

    def __init__(self, server_address: tuple[str, int], gateway: TapGateway) -> None:
        """把网关实例装进 http.server, 但不启动监听。

        Args:
            server_address: ``(host, port)`` 绑定地址 (调用方决定回环或对外)。
            gateway: 请求分发器; 每个请求处理器通过 ``self.server.gateway`` 取它。

        Note:
            构造即 bind+listen (``HTTPServer.__init__`` 的行为), 但 ``serve_forever``
            由调用方显式调用 — 这样测试可以在不起线程的情况下构造后直接关。
        """
        self.gateway = gateway                                                                    # 网关挂到服务器上: 每个处理器经它取业务能力
        super().__init__(server_address, TapRequestHandler)                                      # 基类负责绑定监听: 启动循环仍由调用方显式触发


def build_gateway(
    best_client: Any = None,                                                                   # 上游客户端可空: 缺省惰性导入, 路由测试可传替身
    *,                                                                                             # 关键字参数: 存储路径与结果目录必须写全名
    db_path: str = "",
    output_dir: str = "",
    token_validator: Optional[Callable[[str], bool]] = None,                                     # 令牌校验回调: 透传给网关, 网关是唯一鉴权处
) -> TapGateway:
    """组装网关; 只有同时给出 db_path+output_dir 才启用 async 存储。

    ``best_client`` 缺省时惰性导入 :class:`src.client.BestClient`: 把上游客户端
    依赖压到真正要建网关的时刻, 使只测路由的调用方不必拉起 BEST 客户端。
    """
    if best_client is None:                                                                    # 缺省才导入上游客户端: 导入期不绑定上游依赖与凭据
        # 延迟导入 BEST 客户端: 避免导入期就绑定上游依赖/凭据, 纯路由测试可传替身。
        # 客户端类名锁定为 BestClient (两阶段异步 REST): src 下没有 pybest 的单类 Best。
        from src.client import BestClient
        best_client = BestClient()                                                               # 建客户端: 唯一的生产客户端, 两阶段异步会话
    executor = TapExecutor(best_client)                                                             # 执行器包住客户端: 执行层自己不发请求
    job_store = (                                                                                 # 存储条件构造: 只有两项路径都给了才启用异步
        TapJobStore(                                                                                # 存储构造: 队列落在这两个路径上
            db_path,                                                                                # 数据库路径: 作业状态持久化位置
            output_dir,                                                                             # 结果目录: 作业产物落盘位置
            executor,                                                                            # 执行器同传: 作业线程与同步查询共用一份执行器
            anonymous_concurrency=_env_int("BEST_TAP_ANON_CONCURRENCY", 1),
            authenticated_concurrency=_env_int("BEST_TAP_AUTH_CONCURRENCY", 3),
            anonymous_pending=_env_int("BEST_TAP_ANON_PENDING", 5),
            authenticated_pending=_env_int("BEST_TAP_AUTH_PENDING", 20),
        )
        if db_path and output_dir                                                                  # 两条件缺一不可: 少一个路径就无法启用异步
        else None                                                                                 # 否则不建存储: 网关据此对异步路由回 503
    )
    return TapGateway(executor, job_store=job_store, token_validator=token_validator)


def serve(
    host: str = "127.0.0.1",
    port: int = 8000,                                                                             # 绑定地址缺省回环: 对外监听要调用方显式指定
    *,                                                                                              # 关键字参数: 后面几项都是可选配置
    best_client: Any = None,                                                                        # 上游客户端可空: 透传给网关组装
    db_path: str = "",
    output_dir: str = "",
    token_validator: Optional[Callable[[str], bool]] = None,                                       # 令牌校验回调: 透传, 鉴权仍只在网关一处
) -> TapHTTPServer:
    """创建 (不启动) TAP HTTP 服务器; 生命周期由调用方掌握。"""
    gateway = build_gateway(                                                                        # 网关在此组装: 生命周期由调用方掌握
        best_client, db_path=db_path, output_dir=output_dir, token_validator=token_validator        # 配置整份透传: 组装逻辑不在本层重复一遍
    )
    return TapHTTPServer((host, port), gateway)


def main(argv: Optional[list[str]] = None) -> int:
    """``python -m src.tap.service [--host --port --db --out]`` 入口。

    ``--db``/``--out`` 同时给出即启用 UWS async; serve_forever 前绑定端口,
    KeyboardInterrupt 后统一 server_close 释放监听 socket。
    """
    # 惰性导入: 只有走 CLI 入口才需要 argparse (被 import 时不付这份成本)
    import argparse

    parser = argparse.ArgumentParser(description="astro-best IVOA TAP gateway (stdlib)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default="", help="UWS sqlite path (enables async)")
    parser.add_argument("--out", default="", help="UWS result dir (enables async)")
    args = parser.parse_args(argv)                                                              # 参数已解析: 后续一律按名字取值, 不用再读位置
    server = serve(args.host, args.port, db_path=args.db, output_dir=args.out)                     # 建服务器但不启动: 启动循环由入口显式控制
    print(f"astro-best TAP gateway on http://{args.host}:{args.port}/tap")
    try:
        server.serve_forever()                                                                      # 阻塞在服务循环: 收到中断信号才返回
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()                                                                  # 退出即关监听套接字: 端口不该被进程退出后残留占用
        # P2-11: job store 持有工作线程池, close() 必须有调用点, 否则句柄随
        # 进程悬挂; 数据库连接已是即开即关, 线程池仍须显式收
        store = getattr(server.gateway, "job_store", None)                                          # 存储可能未配置: 未启用异步时这里是空值
        if store is not None:                                                                   # 有存储才收: 线程池须显式关闭, 句柄不随进程走
            store.close()                                                                        # 关线程池: P2-11 的收口点, 少这一行作业线程随进程悬挂
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
