"""src.auth — NADC 通行证 OAuth2.0 身份层 (Phase 6)。

能力边界: 以 Authorization Code 模式对接 https://oauth.china-vo.org (NADC 用户通行证),
获取 access_token 与用户 profile (umtId/ldap_id/name/email...), 供 provenance 血缘头
与审计使用。**双轨制**: 本层只做身份; BEST 数据查询的 form 登录
(BEST_API_USER/PASS) 保持既有行为不变 (本 skill 是 BEST 数据源主理方, 不委派自身数据面)。

协议 (NADC 官方规范, 2025-01-13):
  1. GET  /oauth/authorize?response_type=code&client_id&redirect_uri&scope=profile&state
     -> 用户登录授权后回调 redirect_uri?code=...&state=...
  2. POST /oauth/token (grant_type=authorization_code&code&redirect_uri&client_id&
     client_secret&scope=profile) -> {"access_token": "...", "expires_in": 3600}
  3. GET  /api/profile (Authorization: Bearer <token>) -> {"code":200,"data":{"user":{...}}}
  4. GET  /oauth/logout?WebServerURL=... (登出)

凭据纪律 (安全面 9): client_id/client_secret 只读环境变量
(NADC_OAUTH_CLIENT_ID / NADC_OAUTH_CLIENT_SECRET); token 落用户级缓存
(~/.astro-best/nadc_token.json, 0600); 代码零凭据字面量。

token 静态保护 (2026-09-30, auth §5.6): POSIX 权限位在 Windows 上退化
(chmod 只兑现只读标志, st_mode 恒 0o666), 0600 纪律在本机等于无保护 —
同机其他用户可原样读走 Bearer 凭据。故缓存文件按平台门禁加静态保护:
Windows 走 DPAPI (crypt32!CryptProtectData, CURRENT_USER 范围, 密文只有
同一 Windows 账号能解), POSIX 维持 0600; 文件格式版本化 (v2 信封),
v1 裸 JSON 旧缓存兼容读取、下次 save 自动升级。保护不可用不阻断鉴权:
告警后回退明文 (可用性优先, 风险留痕)。

token 过期恢复 (2026-09-30, auth §5.5): NADC 官方不签发 refresh_token,
token 典型 3600 s 过期, 过期后唯一合法续期是重走 Authorization Code 流
(浏览器交互)。``ensure_access_token`` 把"检测过期 → 恢复 → 落缓存 →
返回新 token"收敛成一个调用点: 调用方有交互通道就注入 reauth 回调, 没有
就接 :class:`TokenExpiredError` (消息带恢复命令) — 长跑任务不会再把过期
令牌当有效身份静默用下去。
"""
from __future__ import annotations

# 标准库: JSON 解析/日志/环境变量取凭据/随机 state/时间与过期/os 级文件权限
# 标准库: base64 (v2 信封的密文编码) / contextlib.suppress — 静默 IO/浏览器
# 打开失败的表达 (SIM105) / json (token 缓存序列化) / logging / os (权限位) /
# secrets (state 随机源) / sys (平台门禁: win32 才走 DPAPI) / time (过期判定)
import base64
import contextlib
import json
import logging
import os
import secrets
import sys
import time

# 标准库: urllib 三件套 — OAuth 全部 HTTP 调用 (零第三方依赖)
import urllib.error
import urllib.parse
import urllib.request

# 标准库: profile/记录的数据类形态
from dataclasses import dataclass

# 标准库: 用户级 token 缓存路径 (~/.astro-best/nadc_token.json)
from pathlib import Path

# 标准库: 类型标注 (Callable 供 ensure_access_token 的 reauth 回调协议)
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)                                                            # 模块级 logger: 授权流程的消息只从这里出

# NADC OAuth 协议端点与默认值 (权威来源: NADC 官方通行证规范; 消费方:
# 本模块各 flow 与 src.auth 门面再导出; client_secret 只走环境变量, 零字面量)
OAUTH_BASE_URL = "https://oauth.china-vo.org"  # 唯一基址: 端点全由它 + 路径常量拼成 (S310 豁免依据)
AUTHORIZE_PATH = "/oauth/authorize"                                                             # 授权端点路径: 纯拼 URL 的第一步, 不触网
TOKEN_PATH = "/oauth/token"  # noqa: S105 (路径常量, 非口令)
PROFILE_PATH = "/api/profile"  # 协议第 3 步: 用 Bearer 换用户档案
LOGOUT_PATH = "/oauth/logout"                                                                       # 登出端点路径: 换账号时用, 同样不触网
SCOPE = "profile"  # 只申请 profile: 身份层不碰任何数据权限
REQUEST_TIMEOUT = 30  # 秒; 令牌交换是短交互, 不给无界等待

ENV_CLIENT_ID = "NADC_OAUTH_CLIENT_ID"  # 凭据只从环境变量取: 代码内零凭据字面量
ENV_CLIENT_SECRET = "NADC_OAUTH_CLIENT_SECRET"  # noqa: S105 (env 名, 非口令)
ENV_REDIRECT_URI = "NADC_OAUTH_REDIRECT_URI"  # 允许本地/容器各自指定回调地址
DEFAULT_LOOPBACK_PORT = 8765  # 回环监听端口: 刻意避开 8080/3000 等常见占用
DEFAULT_TOKEN_CACHE = Path.home() / ".astro-best" / "nadc_token.json"  # 用户级缓存: 不进项目目录, 不随仓库流转


@dataclass
class OAuthProfile:
    """NADC 用户 profile (umtId 为平台内唯一身份标识)。"""

    umt_id: str = ""                              # 平台内唯一身份标识: 审计血缘头与作业归属都引它
    union_id: str = ""                            # 跨通行证联合 id: NADC 不保证每账号都有
    ldap_id: str = ""                             # LDAP 账号: 仅部分用户绑定
    name: str = ""
    email: str = ""                               # 只作展示与审计, 从不参与鉴权
    phone: str = ""
    confirmed: Optional[bool] = None              # 三态: None = 服务端没给该字段, 不等于 False
    locked: Optional[bool] = None                 # 账号封禁判据: 审计侧据此拒绝该身份
    avatar_url: str = ""

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "OAuthProfile":
        """从 /api/profile 响应构造 OAuthProfile (取 data.user 段, 缺省空串)。"""
        # 解析协议第 3 步响应: data.user 段; 任何字段缺失都给空串, 不抛
        user = (payload or {}).get("data", {}).get("user", {}) or {}  # 两级兜空: 业务失败响应根本没有 data.user
        return cls(
            umt_id=str(user.get("umtId", "") or ""),  # 线上是驼峰 umtId, 与其余字段的蛇形拼写不一致
            union_id=str(user.get("unionId", "") or ""),
            ldap_id=str(user.get("ldap_id", "") or ""),
            name=str(user.get("name", "") or ""),
            email=str(user.get("email", "") or ""),
            phone=str(user.get("phone", "") or ""),
            confirmed=user.get("confirmed"),  # 布尔不强转 str: 保住 None 与 False 的区别
            locked=user.get("locked"),
            avatar_url=str(user.get("avatar_url", "") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """OAuthProfile -> dict (NADC 原始字段名, 供信封/审计消费)。"""
        return {  # 输出沿用 NADC 原始字段名: 审计侧不必再维护一层映射表
            "umtId": self.umt_id, "unionId": self.union_id, "ldap_id": self.ldap_id,
            "name": self.name, "email": self.email, "phone": self.phone,
            "confirmed": self.confirmed, "locked": self.locked,
            "avatar_url": self.avatar_url,
        }


class NadcOAuthError(RuntimeError):
    """NADC OAuth 协议错误 (显式失败, 不静默降级)。"""


class TokenExpiredError(NadcOAuthError):
    """token 缺失/已过期且无恢复手段 (NADC 无 refresh_token, 只能重走授权流)。

    与 NadcOAuthError 分开的含义: 这个异常说的是"需要人重新授权一次"
    (消息里带确切实测命令), 调用方按"需要交互"处理 — 批处理/CI 捕获后
    退出并提示命令, 而不是把过期令牌当有效身份继续用。
    """


def build_authorize_url(
    client_id: str,                                                                               # 客户端标识: 必填, 缺了授权服务器不会受理
    redirect_uri: str,                                                                            # 回调地址: 须在后台白名单内, 否则回调被拒
    state: Optional[str] = None,                                                                    # 防跨站状态值可空: 不给就没有往返校验
    base_url: str = OAUTH_BASE_URL,                                                                 # 基址: 缺省取授权服务器常量
) -> tuple[str, str]:
    """构造授权 URL; 返回 (url, state) (state 缺省时生成随机串, 防 CSRF)。"""
    if not client_id:                                                                            # 空标识即拒: 显式失败优于发一次注定被拒的请求
        raise NadcOAuthError("client_id 缺失 (env NADC_OAUTH_CLIENT_ID)")  # 缺凭据即失败: 不造出必然被拒的 URL
    # state 随机串: 回调时比对, 防 CSRF (缺省由本函数生成, 调用方也可显式传入)
    state = state or secrets.token_urlsafe(16)  # 16 字节熵足够; 显式传入时沿用调用方的 state
    params = {  # 协议第 1 步的查询参数集合, 统一 form-urlencoded
        "response_type": "code",  # 授权码模式: NADC 只签发一次性 code, 不签发隐式 token
        "client_id": client_id,
        "redirect_uri": redirect_uri,  # 必须与换 token 时逐字一致, 否则服务端拒绝
        "scope": SCOPE,
        "state": state,
    }
    return f"{base_url}{AUTHORIZE_PATH}?{urllib.parse.urlencode(params)}", state  # 一并回传 state: 回调校验要用


def exchange_code(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    base_url: str = OAUTH_BASE_URL,
    timeout: int = REQUEST_TIMEOUT,
) -> dict[str, Any]:
    """用 authorization code 交换 access_token (返回 {access_token, expires_in, ...})。"""
    if not (client_id and client_secret):                                                     # 两个凭据必须成对: 缺一半就发不出请求, 不如早失败
        raise NadcOAuthError("client_id/client_secret 缺失 (env NADC_OAUTH_CLIENT_ID/SECRET)")  # 缺 secret 明确失败: 不用空串硬换
    body = urllib.parse.urlencode({  # form 编码: /oauth/token 只收 x-www-form-urlencoded
        "grant_type": "authorization_code",  # 授权码模式是 NADC 唯一支持的流程
        "code": code,                       # 一次性授权码: 换过即失效, 重试须重新授权
        "redirect_uri": redirect_uri,       # 与 authorize 阶段逐字相同, 否则服务端判不匹配
        "client_id": client_id,
        "client_secret": client_secret,     # 只从环境变量来, 不落盘不写日志
        "scope": SCOPE,
    }).encode("utf-8")
    # 协议第 2 步: POST /oauth/token, form 编码 body 携带授权码换 access_token
    # S310 误报: URL 由 https 的 OAUTH_BASE_URL 常量 + 路径常量拼成 (scheme
    # 不可变), 不是外部可控输入
    request = urllib.request.Request(  # noqa: S310
        f"{base_url}{TOKEN_PATH}", data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"})
    try:
        # HTTP 调用点: 令牌交换 (显式失败抛 NadcOAuthError, 不静默降级)
        # S310 误报: request 的 URL 由 https 常量拼成 (见上方 Request 构造)
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))  # 先按 utf-8 解码: 响应体是 JSON 文本不是裸字节流
    except urllib.error.HTTPError as exc:
        # 服务端 4xx/5xx: 带响应体前 200 字节, 便于定位是 code 过期还是凭据错
        raise NadcOAuthError(f"token 交换 HTTP {exc.code}: {exc.read()[:200]!r}") from exc  # 截 200 字节: 不把整页 HTML 灌进日志
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        # 网络层/超时/响应非 JSON: 统一包装成协议错误, 调用方按同一异常处理
        raise NadcOAuthError(f"token 交换失败: {exc!r}") from exc  # 归口成一种异常: 调用方不必区分网络与解码
    if not payload.get("access_token"):
        raise NadcOAuthError(f"token 响应缺 access_token: {sorted(payload)}")  # 只列键名: 响应值可能含凭据, 不进消息
    return payload  # 原样返回: expires_in 等归一化交给 TokenStore.save


def get_profile(
    access_token: str,
    base_url: str = OAUTH_BASE_URL,
    timeout: int = REQUEST_TIMEOUT,
) -> OAuthProfile:
    """用 access_token 取用户 profile (Bearer 认证; 注意 Bearer 与 token 间必须有空格)。"""
    if not access_token:                                                                          # 没有有效令牌直接返回: 过期与缺失在这里同形
        raise NadcOAuthError("access_token 缺失")  # 空 token 发出去必然 401, 不如本地就拒
    # S310 误报: URL 由 https 的 OAUTH_BASE_URL 常量 + 路径常量拼成 (scheme
    # 不可变), 不是外部可控输入
    request = urllib.request.Request(  # noqa: S310
        f"{base_url}{PROFILE_PATH}", method="GET",  # 端点固定由常量拼成, 不接受外部输入
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"})  # Bearer 与 token 之间的空格不能省
    try:
        # HTTP 调用点: Bearer 认证取 profile (协议第 3 步; 显式失败不降级)
        # S310 误报: request 的 URL 由 https 常量拼成 (见上方 Request 构造)
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise NadcOAuthError(f"profile HTTP {exc.code}: {exc.read()[:200]!r}") from exc  # 同上截断: 401 体通常带诊断说明
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise NadcOAuthError(f"profile 获取失败: {exc!r}") from exc  # 与令牌交换同构的失败语义
    if payload.get("code") != 200:  # 该端点用 HTTP 200 承载业务错误码, 只看状态码会漏判
        raise NadcOAuthError(f"profile 业务码非 200: {payload.get('code')}")  # 业务码进消息: 可区分未认证与无权限
    return OAuthProfile.from_api(payload)  # 归一化在模型层做, 本层只管传输与失败语义


def build_logout_url(base_url: str = OAUTH_BASE_URL, web_server_url: str = "") -> str:
    """构造通行证登出 URL (成功登出后重定向回应用地址)。"""
    params = {"WebServerURL": web_server_url} if web_server_url else {}  # 留空则不带参数: 登出后不回跳
    query = f"?{urllib.parse.urlencode(params)}" if params else ""  # 无参数时不留裸问号
    return f"{base_url}{LOGOUT_PATH}{query}"  # 只造 URL 不发请求: 发不发由调用方按交互能力决定


# ---- token 缓存静态保护 (平台门禁) -----------------------------------------

# v2 信封: {"v": 2, "protection": "dpapi"|"none", "data_b64": <密文/明文 base64>}
# v1 (2026-09-30 前) 是裸 token JSON — load 按"无 v 键"识别并兼容读取,
# 下次 save 全量重写即自动升级, 不做迁移脚本 (缓存文件, 丢了重授权即可)。
TOKEN_FILE_VERSION = 2  # v2 = 带 protection 键的信封; v1 裸 JSON 由 load 兼容
PROTECTION_DPAPI = "dpapi"   # Windows: crypt32 DPAPI, CURRENT_USER 范围
PROTECTION_NONE = "none"     # POSIX (0600 真实生效) 或 DPAPI 不可用的回退


def _dpapi_available() -> bool:
    """当前进程能否调 crypt32 (仅 win32; POSIX/无 ctypes 一律 False)。

    探测本身也包在 try 里: 极端裁剪的 Python 构建可能没有 ctypes, 那时
    按"不可用"走回退路径, 不让探测把导入期打崩。
    """
    if sys.platform != "win32":
        return False                           # DPAPI 是 Windows 专有: POSIX 直接走 0600 明文路径
    try:
        # 延迟导入 ctypes: POSIX 进程完全不碰它 (导入成本与攻击面都只留在
        # 真正需要 DPAPI 的 Windows 上)
        import ctypes

        return hasattr(ctypes, "windll")       # windll 是 ctypes 的 Windows 扩展, 缺它即不可用
    except Exception:  # noqa: BLE001 - 探测失败按不可用, 由回退路径接管
        return False


def _dpapi_crypt(data: bytes, encrypt: bool) -> bytes:
    """DPAPI 加解密 (crypt32 CryptProtectData/CryptUnprotectData, 禁弹窗)。

    Args:
        data: 明文 (encrypt=True) 或密文 (encrypt=False)
        encrypt: True 加密 / False 解密

    Returns:
        密文或明文 (bytes)

    Raises:
        NadcOAuthError: Win32 调用失败 (带 GetLastError 信息)

    Note:
        CURRENT_USER 范围 (不传可选熵/提示体): 密文只有同一 Windows 用户
        账号下的进程能解 — 文件被同机其他用户拷走、或整机外带都解不出。
        这不防"同账号下的恶意进程" (那已等于本机失守), 防的是凭据文件
        离开本账号边界后被复用, 正是 auth §5.6 记录的多人机器风险。
    """
    # 本地: 令牌存储与错误类型 (OAuth 身份层的协作者)
    import ctypes  # 函数内导入: 导入期就绪, 但只在真正加解密时才付 ctypes 的成本

    CRYPTPROTECT_UI_FORBIDDEN = 0x1  # 禁弹 UI: 服务端/无头场景不能有模态框

    class _DataBlob(ctypes.Structure):
        """Win32 DATA_BLOB (cbData + 指向字节缓冲的指针)。"""

        _fields_ = [("cbData", ctypes.c_ulong),   # 长度字段必须在前: Win32 按声明顺序解释内存布局
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    # 输入缓冲必须活到 Win32 调用返回: from_buffer_copy 给一份独立拷贝,
    # 比 ctypes.c_char_p(data) (临时对象可能被回收) 安全
    raw = (ctypes.c_char * len(data)).from_buffer_copy(data)  # 独立拷贝: 临时对象可能在调用返回前被回收
    blob_in = _DataBlob(len(data), ctypes.cast(raw, ctypes.POINTER(ctypes.c_char)))  # cast 而非直传: 指针字段要求精确类型
    blob_out = _DataBlob()  # 空壳: 输出缓冲由 Win32 分配, 事后必须 LocalFree
    func_name = "CryptProtectData" if encrypt else "CryptUnprotectData"  # 两者 ctypes 签名相同, 调用与错误处理可共用
    func = getattr(ctypes.windll.crypt32, func_name)  # 按名取: 免去为每个 API 写 argtypes/restype 签名
    # 指针参数一律 byref/POINTER 传入 (不设 argtypes 也不会被截断成 32 位)
    ok = func(ctypes.byref(blob_in), None, None, None, None,  # 四个 None = 熵/提示体/保留参数, 保持 CURRENT_USER 默认范围
              CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:                                                                                 # 响应非 200 即失败: 授权服务器的软错也算失败
        raise NadcOAuthError(f"{func_name} 失败: {ctypes.WinError()}")  # 布尔返回无信息量, 真实原因在系统错误码里
    try:
        # 输出缓冲由 Win32 分配 (LocalAlloc), 必须 string_at 拷出后 LocalFree
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)  # 按 cbData 拷出: 密文可含 0x00, 不能按 NUL 截断
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(blob_out.pbData,  # Win32 分配的内存不释放就是句柄泄漏
                                                     ctypes.c_void_p))


def _protect_record(record: dict[str, Any]) -> dict[str, Any]:
    """token 记录 -> v2 落盘信封 (按平台选静态保护; 保护失败回退明文+告警)。

    可用性优先于保密性: DPAPI 调用失败 (极端: crypt32 被安全软件拦) 时
    不阻断登录/保存, 回退明文并留 warning — "登不进去"比"文件宽松"更糟,
    但风险必须留痕, 不允许静默降级。
    """
    plaintext = json.dumps(record, ensure_ascii=False).encode("utf-8")  # ensure_ascii=False: 档案字段含中文, 转义只增体积
    if _dpapi_available():  # 只有 Windows 且 ctypes 可用才走加密分支
        try:
            blob = _dpapi_crypt(plaintext, encrypt=True)  # 失败由下面 except 接管, 不在此处静默降级
            return {"v": TOKEN_FILE_VERSION, "protection": PROTECTION_DPAPI,  # v/protection 是 load 侧的判别键
                    "data_b64": base64.b64encode(blob).decode("ascii")}  # base64 便于 JSON 承载二进制密文
        except Exception as exc:  # noqa: BLE001 - 保护失败回落, 告警留痕
            logger.warning("DPAPI 加密失败, token 缓存回退明文: %s", exc)  # 告警而非静默: 降级必须留痕
    return {"v": TOKEN_FILE_VERSION, "protection": PROTECTION_NONE,  # POSIX 常态, 也是 DPAPI 失败的回退形态
            "data_b64": base64.b64encode(plaintext).decode("ascii")}


def _unprotect_record(envelope: dict[str, Any]) -> Optional[dict[str, Any]]:
    """v2 落盘信封 -> token 记录; 解不动返回 None (按无缓存处理, 不抛)。

    解密失败 (换账号读别人的缓存/密文损坏) 不抛异常: 调用方的语义是
    "没有可用 token 就重新授权", 抛异常反而把正常路径变成崩溃。
    """
    try:
        blob = base64.b64decode(envelope.get("data_b64", ""), validate=False)  # 容忍换行/空白: 解不动由后面的 JSON 判据兜
    except (ValueError, TypeError):
        return None                              # 编码坏了即按无缓存处理: 调用方语义是"重新授权"
    if envelope.get("protection") == PROTECTION_DPAPI:  # 只有标了 dpapi 的信封才进解密分支
        try:
            plaintext = _dpapi_crypt(blob, encrypt=False)  # 解不开在下面 except 转成 None, 不外抛
        except Exception as exc:  # noqa: BLE001 - 见 docstring: 按无缓存处理
            logger.warning("DPAPI 解密失败 (换账号/换机或缓存损坏): %s", exc)  # 换 Windows 账号就读不动: 告警点明成因
            return None
    else:
        plaintext = blob  # none 保护即明文: base64 只是传输编码, 不提供任何机密性
    try:
        record = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None                              # 坏文件不等于崩溃: 语义是"没有缓存, 请重新授权"
    return record if isinstance(record, dict) else None  # 非 dict (裸列表等) 也判无缓存: load 侧只认 dict


class TokenStore:
    """access_token 用户级缓存 (v2 信封, 0600 + 平台静态保护, 过期重取)。

    纪律: 只存 token 与过期时间; client_secret 永不落盘; 文件权限 0600
    (每次 save 后显式 chmod 收敛, 见 save 的 A3 说明); 落盘内容过静态
    保护 (Windows DPAPI 密文 / POSIX 明文, 见 :func:`_protect_record`) —
    0600 在 Windows 上不生效, 保密责任在那一侧由 DPAPI 承担。
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        """构造 token 缓存存取器。

        Args:
            path: 缓存文件路径; 传 None 时用默认用户级路径
                (``~/.astro-best/nadc_token.json``)。

        Note:
            只记录路径, 不在构造时读盘 — 读取走 ``load()`` 并允许失败,
            构造期抛错会让"没有 token"这种正常状态无法表达。
        """
        self.path = Path(path) if path else DEFAULT_TOKEN_CACHE  # 构造期不读盘: "没有 token" 是正常态, 不该在此抛

    def load(self) -> Optional[dict[str, Any]]:
        """读取 token 缓存; 缺失/损坏/缺 access_token 返回 None (不抛)。

        兼容两代文件格式: v2 静态保护信封 (有 ``v`` 键, 密文/明文都在
        ``data_b64``) 与 v1 裸 token JSON (无 ``v`` 键, 2026-09-30 前的
        缓存) — 旧文件照常可读, 下次 ``save`` 全量重写即自动升级为 v2。
        """
        if not self.path.is_file():                                                            # 缓存文件不存在时走重新授权: 不拿半截文件当令牌用
            return None                          # 首次登录前文件不存在是常态, 按无缓存返回
        try:
            # IO 点: 读用户级缓存; 损坏不当致命 — 视为无 token, 走重新授权
            data = json.loads(self.path.read_text(encoding="utf-8"))  # 显式 utf-8: 文件含中文档案字段
        except (OSError, json.JSONDecodeError):
            return None                          # 读失败与内容损坏同判: 语义都是"没有可用缓存"
        if isinstance(data, dict) and data.get("v") == TOKEN_FILE_VERSION:  # v1 裸 JSON 无 v 键, 直接当明文记录
            data = _unprotect_record(data)      # 解保护后可能变 None, 下面 isinstance 一并兜住
        if not isinstance(data, dict) or not data.get("access_token"):
            return None                          # 结构完好但无 token 也算无缓存: load 只保证"有可用 token"
        return data

    def is_expired(self, skew_seconds: int = 60) -> bool:
        """token 是否过期 (提前 skew_seconds 秒判过期, 留网络余量); 无缓存视为过期。"""
        data = self.load()                      # 判据统一落在 load 的 None 上: 无缓存即过期
        if not data:                                                                     # 空响应体视为未授权: 站点返 200+空体是常见的会话失效形态
            return True
        expires_at = float(data.get("expires_at", 0) or 0)  # 缺字段退 0 → 必然过期, 不给"未知"留后门
        return time.time() + skew_seconds >= expires_at  # 提前判: 留出一次请求的网络往返余量

    def save(self, token_payload: dict[str, Any]) -> dict[str, Any]:
        """保存 token 到用户级缓存 (v2 信封 + 平台静态保护 + 0600 权限)。

        落盘内容不是裸 token JSON: 记录经 :func:`_protect_record` 包成
        v2 信封 (Windows DPAPI 密文 / POSIX 明文, 两者都过 base64),
        使"文件被拷走"不等于"凭据可复用" — POSIX 0600 在 Windows 上不生效
        (chmod 只兑现只读标志), 保密责任改由 DPAPI 承担, 见模块 docstring。

        A3: 除 ``os.open(..., 0o600)`` 外, 保存后显式
        ``os.chmod(path, 0o600)`` — open 的 mode 只对本次新建的文件
        生效, 已存在文件的权限位原样保留 (旧文件可能因宽松 umask 或备份
        还原停留在 0644)。本方法每次都全量重写文件内容, 因此"保存后
        chmod"即足以保证终态收敛, 不需要先 unlink 再建 (那会引入"删
        成功但重建失败"的丢令牌窗口)。

        Args:
            token_payload: 令牌端点响应 (至少含 access_token; expires_in
                缺省按 3600 s)

        Returns:
            落盘的明文记录 (obtained_at/expires_at 已补齐), 与旧版返回同形
        """
        expires_in = int(token_payload.get("expires_in", 3600) or 3600)  # 缺省 3600s: NADC 规范里的典型寿命
        record = {  # 只存 token 与时间戳: client_secret 永不落盘
            "access_token": token_payload["access_token"],
            "token_type": str(token_payload.get("token_type", "Bearer")),
            "expires_in": expires_in,
            "obtained_at": time.time(),       # 取得时刻: 排查"从什么时候开始失效"用
            "expires_at": time.time() + expires_in,  # 落绝对时刻而非 TTL: 跨进程读缓存不必知道何时存的
        }
        envelope = _protect_record(record)     # 落盘前先包 v2 信封: 明文记录永不直接进文件
        self.path.parent.mkdir(parents=True, exist_ok=True)  # 幂等建目录: 首次登录时目录还不存在
        # IO 点: os.open + 0600 — 仅属主可读写 (POSIX 真实生效; Windows 上
        # 权限位语义退化, 保密由 DPAPI 承担 — mode 只对新建生效, 已存在
        # 文件的宽松权限位由下方保存后 chmod 收敛 (A3))
        fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # O_TRUNC 全量重写: 不留旧信封残余字节
        with os.fdopen(fd, "w", encoding="utf-8") as fh:  # fdopen 接管 fd: 退出即 flush+close, 不漏描述符
            json.dump(envelope, fh, ensure_ascii=False, indent=2)  # indent 便于人工排查缓存文件
        # A3: 保存后显式 chmod 收敛权限位 — os.open 的 mode 不修正已存在文件
        # 的既有权限 (0644 旧文件会原样保留); 每次 save 全量重写内容, 保存后
        # chmod 即足以保证终态 0600 (先 unlink 再建反而多一个丢令牌窗口)
        os.chmod(str(self.path), 0o600)        # 终态收敛点: 旧文件残留的 0644 在此被改回
        return record                           # 返回明文记录而非信封: 调用方靠 expires_at 判寿命

    def clear(self) -> None:
        """清除本地 token 缓存 (登出用; 文件不存在时静默)。"""
        if self.path.is_file():                # 不存在即视为已清除: 登出可安全重复调用
            # IO 点: 删除缓存文件 (登出语义; 删不掉也静默, 不阻断登出流程)
            # SIM105: contextlib.suppress 表达"静默删除"比 try-except-pass 直白
            with contextlib.suppress(OSError):  # 删不掉不阻断登出: 残留风险留给告警与后续覆盖写
                self.path.unlink()              # 单文件删除: 无目录递归, 不会误伤同目录其它内容

    def valid_token(self) -> Optional[str]:
        """返回未过期的 access_token; 过期/缺失返回 None。

        SA-P3-6: 一次 load 后本地判定过期 — 走 ``self.load()`` +
        ``self.is_expired()`` 会把缓存文件读两遍 (is_expired 内部又 load
        一次), 认证热路径上白付双倍 IO; 语义不变。
        """
        data = self.load()                      # 一次读盘: 不转调 is_expired, 免得热路径上双倍 IO
        if not data:                                                                       # 同 401: 空 body 与空 body 一样不可当成功
            return None
        expires_at = float(data.get("expires_at", 0) or 0)  # 与 is_expired 同一判据, 不留两套过期语义
        if time.time() + 60 >= expires_at:  # 60s 余量: 与 is_expired 的默认 skew 一致
            return None
        return str(data["access_token"])       # 转字符串: 上层只当 Bearer 凭据用, 不需要类型信息


def ensure_access_token(
    store: Optional[TokenStore] = None,
    reauth: Optional[Callable[[], Any]] = None,
) -> str:
    """返回可用的 access_token; 过期/缺失时经 ``reauth`` 恢复, 否则抛错。

    长跑任务 (>3600 s, token 典型寿命) 的身份恢复单点: NADC 官方不签发
    refresh_token, 过期后唯一合法的续期方式是重走 Authorization Code 流
    (浏览器交互)。本函数把"检测过期 → 恢复 → 落缓存 → 返回新 token"收敛
    成一个调用点, 调用方按自身交互能力二选一:

    - 有交互通道 (GUI/agent 能问用户): 传 ``reauth`` (典型是
      ``lambda: run_manual_paste_flow(...)`` 或 ``run_local_callback_flow``
      的薄包装), 过期时自动重走授权, 新 token 落缓存后返回;
    - 无交互通道 (批处理/CI 无头进程): 不传, 过期即抛
      :class:`TokenExpiredError` — 消息带恢复命令, 由运维按命令重登。
      **不静默返回过期令牌**: 那会让"身份块悄悄变空/请求 401"晚一个
      任务周期才暴露。

    Args:
        store: 可注入的 TokenStore (测试替身); 缺省默认用户级缓存
        reauth: 可选的可调用, 返回新 token 载荷 (dict, 含 access_token)
            或裸 token 字符串; 它抛的异常原样上抛 (不吞 — 恢复失败要
            让调用方看见真实原因)

    Returns:
        可用的 access_token (未过期)

    Raises:
        TokenExpiredError: 无有效 token 且未提供 reauth, 或 reauth 之后
            token 仍不可用 (极端: 服务端回 0 秒寿命)
        NadcOAuthError: reauth 返回的载荷不含 access_token
    """
    store = store or TokenStore()             # 可注入替身: 测试不必碰用户级缓存文件
    token = store.valid_token()               # 先看缓存: 未过期就不必打扰用户重新授权
    if token:                                                                              # 已有令牌就不必再走授权: 这是 status 子命令的短路
        return token
    if reauth is None:                        # 无交互通道: 抛而非静默续用过期令牌
        raise TokenExpiredError(              # 消息带实测恢复命令: 运维照着做即可
            "NADC access_token 缺失或已过期 (NADC 无 refresh_token, 不能静默续期); "
            "恢复命令: python ops/astro_best_cli.py oauth login "
            "(无头环境: oauth url 自行浏览器授权, 或 oauth paste <回调URL或code>)"
        )
    payload = reauth()                        # 恢复回调: 它抛的异常原样上抛, 不在本层吞
    # reauth 允许返回裸 token 字符串 (调用方只拿得到 token 时), 统一成载荷
    # 再走 save — 过期时间由 save 按 expires_in 缺省 3600 补齐
    if isinstance(payload, str):                                                            # 载荷可能是 str 也可能已是 dict: 两种形态都收
        payload = {"access_token": payload}   # 包成载荷: save 统一按 dict 读 expires_in
    if not isinstance(payload, dict) or not payload.get("access_token"):  # 回调返回垃圾也要显式失败
        raise NadcOAuthError(
            f"reauth 未返回可用 token 载荷: {type(payload).__name__}")  # 只报类型名: 不把载荷内容写进异常
    store.save(payload)                       # 先落盘: 后续调用直接命中缓存, 不必再走一次 reauth
    token = store.valid_token()               # 落盘后回读校验: 极端情况 (寿命 0) 存进去也未必可用
    if not token:                                                                                  # 拿不到令牌即失败, 不用 None 糊过去
        raise TokenExpiredError("reauth 之后 token 仍判定不可用 (寿命为 0 或时钟异常)")  # 不返回刚存的: 宁可失败也不给无效身份
    return token


def run_local_callback_flow(
    client_id: str,
    client_secret: str,
    redirect_uri: str = f"http://127.0.0.1:{DEFAULT_LOOPBACK_PORT}/callback",
    port: int = DEFAULT_LOOPBACK_PORT,
    open_browser: bool = True,
    timeout: int = 300,
) -> OAuthProfile:
    """本地回环授权流: 起临时 HTTP 端口收 code -> 换 token -> 取 profile。

    失败/超时/端口占用时抛 NadcOAuthError (调用方可降级为手动粘贴流程)。
    """
    # 函数内延迟导入: 只有真正跑本地回环流才拉起 HTTP 服务与浏览器 —
    # 无头 CLI/服务端场景不依赖这两个模块, 也加快 import。
    import threading
    import webbrowser
    from http.server import BaseHTTPRequestHandler, HTTPServer

    state_expected = secrets.token_urlsafe(16)  # 本流自持 state: 发起与回调同进程同闭包, 无需外部保存
    result: dict[str, Any] = {}               # 跨线程信箱: handler 线程写, 主线程轮询读

    class _Handler(BaseHTTPRequestHandler):
        """回环回调服务器: 只服务一次 OAuth redirect, 收到 code 即关机。

        安全约束:
          - 只绑 127.0.0.1 (不回环监听外部接口);
          - 校验 ``state`` 防 CSRF (回调方必须与发起方是同一会话);
          - 收到 code 后即停止收取; 服务器本体由主线程的 ``finally`` 关闭,
            而 ``exchange_code`` + ``get_profile`` 两次往返在关闭**之前**
            完成 —— 即端口在这段时间仍开着, 驻留时长受本流 ``timeout`` 约束。
        """
        def log_message(self, *args: Any) -> None:  # 静音
            """静音 HTTP 服务日志 (回环服务器不写 access log)。"""
            return

        def do_GET(self) -> None:  # noqa: N802
            """授权回调处理: 校验 state (防 CSRF) 并收取 authorization code。"""
            # 解析 redirect_uri?code=...&state=... 回调 (协议第 1 步的落地)
            parsed = urllib.parse.urlparse(self.path)  # 回调路径形如 /callback?code=...&state=...
            params = urllib.parse.parse_qs(parsed.query)  # parse_qs 总是给列表, 取 [0] 是本协议的约定
            got_state = (params.get("state") or [""])[0]  # 缺失时取空串: 必然不匹配, 自然落到 CSRF 分支
            code = (params.get("code") or [""])[0]        # 同样兜空: 缺 code 时走 error 分支而非 KeyError
            if got_state != state_expected:               # state 不匹配即拒绝: 这是防 CSRF 的唯一一道闸
                # state 不匹配 = 疑似 CSRF, 拒绝收取 code
                result["error"] = "state mismatch (possible CSRF)"  # 不回显攻击者的 state: 不给探测者反馈
            elif not code:
                result["error"] = params.get("error", ["missing code"])[0]  # 透传服务端的 OAuth error 参数
            else:
                result["code"] = code                     # 唯一成功出口: 主线程据此跳出轮询
            self.send_response(200)                       # 固定回 200: 浏览器不必关心, 免得用户看到错误页
            self.send_header("Content-Type", "text/html; charset=utf-8")  # 显式 charset: 页面含中文, 靠默认编码会乱码
            self.end_headers()
            self.wfile.write("<html><body>授权完成, 可关闭本页。</body></html>".encode("utf-8"))  # 提示关页: 端口随即关闭

    url, _ = build_authorize_url(client_id, redirect_uri, state=state_expected)  # 复用本流 state, 不另生成一份
    # 本地回环服务器: 只绑 127.0.0.1, 收授权回调, 不对外暴露
    try:
        server = HTTPServer(("127.0.0.1", port), _Handler)  # 只绑回环地址: 与防火墙策略无关
    except OSError as exc:  # 端口被占/被拒是本流的**预期**失败, 不是编程错误 ——
        # 原样冒泡 PermissionError 会让 CLI 那条 "except NadcOAuthError -> 提示改用
        # 手动粘贴" 的退路失效 (CLI 的注释点名的正是"回环被占"), 用户只拿到 traceback。
        raise NadcOAuthError(
            f"无法在 127.0.0.1:{port} 绑定本地回环端口 ({exc}); "
            f"可改用手动粘贴流程: oauth paste <回调URL或code>"
        ) from exc
    server.timeout = timeout                         # serve_forever 轮询间隔上限, 与下面的 deadline 双保险
    thread = threading.Thread(target=server.serve_forever, daemon=True)  # daemon: 主线程退出时不吊住进程
    thread.start()
    try:
        if open_browser:                             # 无头环境传 False, 由调用方自行访问 URL
            # 打开系统浏览器到授权 URL (无头环境打不开时静默, 用户可手动访问)
            # SIM105: suppress 表达"打不开就静默"
            with contextlib.suppress(Exception):
                webbrowser.open(url)                 # 打不开也无所谓: 同一 URL 用户可手动访问
        deadline = time.time() + timeout             # 绝对截止时刻: 授权可能要人手动操作, 不能只靠服务端
        # 轮询等待回调 (授权码由 _Handler 收进 result; 超时即失败)
        while "code" not in result and "error" not in result and time.time() < deadline:  # 三条件缺一不可
            time.sleep(0.2)                          # 0.2s 间隔: 兼顾响应速度与空转开销
        if "error" in result:
            raise NadcOAuthError(f"授权回调失败: {result['error']}")  # 显式失败, 由调用方降级到手动粘贴流
        if "code" not in result:
            raise NadcOAuthError(f"授权超时 ({timeout}s); 请改用手动粘贴流程")  # 消息给出可执行的下一步
        # 协议第 2 步: code 换 token (HTTP POST /oauth/token)
        token = exchange_code(result["code"], client_id, client_secret, redirect_uri)  # 与手动流同一步骤
        # token 落 0600 用户级缓存, 后续请求免重复授权
        TokenStore().save(token)                     # 立即落盘: 下面取 profile 失败也不必重新授权
        # 协议第 3 步: Bearer 取 profile, 作为本流的返回结果
        return get_profile(token["access_token"])     # 失败也照样走 finally 关掉临时服务器
    finally:
        server.shutdown()                            # 无论成败都关: 长期驻留的临时端口就是攻击面
        server.server_close()                        # 显式关套接字: shutdown 只停 serve_forever 循环


def run_manual_paste_flow(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    callback_input: str,
) -> OAuthProfile:
    """手动粘贴流: 调用方提供回调 URL 或裸 code, 完成 token 交换与 profile 获取。

    兜底通道: 本地回环流失败 (端口占用/无头环境/超时) 时, 用户把浏览器
    地址栏里的回调 URL 或裸 code 贴进来, 走同样的第 2/3 步协议。
    """
    raw = (callback_input or "").strip()      # 去空白: 用户多半连地址栏内容一起贴进来
    if not raw:                                                                                  # 空响应不建缓存: 空文件会在下次被当成有效状态
        raise NadcOAuthError("回调输入为空")   # 空输入是调用方漏参, 明确失败好过解析出空 code
    if "code=" in raw:                        # 用户贴的是整条回调 URL
        # 整条回调 URL: 只取 query 里的 code, 其余参数忽略
        parsed = urllib.parse.urlparse(raw)  # 只有 URL 形态才需要拆 query
        code = (urllib.parse.parse_qs(parsed.query).get("code") or [""])[0]  # 本流程不校验 state: 人工粘贴无从比对
    else:
        code = raw                             # 裸 code 形态: 原样使用
    if not code:                                                                                 # 空授权码不继续: 手工粘贴空串是最常见的误操作
        raise NadcOAuthError("无法从输入解析 authorization code")  # 不拿 state 顶替: 那必然换不到 token
    # 协议第 2/3 步: 与回环流完全一致的换 token + 取 profile + 落缓存
    token = exchange_code(code, client_id, client_secret, redirect_uri)  # 同一入口: 两条路行为必须一致
    TokenStore().save(token)                  # 落缓存: 之后所有请求免重复授权
    return get_profile(token["access_token"])  # 与回环流同形返回, 调用方无需分支
