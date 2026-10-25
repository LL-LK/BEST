"""src.tap.client — 本地/远程 BEST TAP 服务的客户端。

能力边界: BestTapClient 选择并访问本地 TAP 网关或远程 TAP 服务 (pyvo 可选
依赖, 惰性导入); NADC access_token 换本地网关 API key (端点由 urljoin 推导,
不用定长切片); search/download 走 TAPService。边界: TAP URL 强校验 (仅绝对
http(s), 拒凭据/query/fragment); pyvo 缺失时显式报错而非静默降级。
白盒锚点: references/ALGORITHM-SPEC.md §6 (TAP 适配层锚点)。

历史来源: pybest 打包产物 (git 6f00efeb^〔本仓历史已无此对象〕〔本仓历史已无此对象〕) ``pybest/tap/client.py`` (git 6f00efeb^〔本仓历史已无此对象〕), 迁入
src/tap/。让 pyvo / astroquery / TOPCAT 可直连本网关 (ISSUE-LIST 第 4 步)。

面向本地与远程 BEST TAP 服务的 pyvo 客户端封装 (pyvo 为可选依赖)。
"""
from __future__ import annotations

import os  # 标准库: 读取 BEST_TAP_URL / BEST_LOCAL_TAP_URL 环境变量
from pathlib import Path  # 标准库: 下载目标路径解析与建目录
from typing import Any, Callable  # 标准库: 服务工厂的可调用类型标注
from urllib.parse import urljoin, urlparse  # 标准库: TAP URL 强校验拆解 + 端点拼接

# 第三方: requests 会话 (连接复用 + Bearer 头注入); 本包唯一 HTTP 客户端依赖
# "本包" 指 src/tap: 实测本包只有本行一处 requests, 无 urllib.request/urlopen。
# src/auth/nadc_oauth.py 的 OAuth 走 urllib 是另一处的**有意**零第三方设计,
# 不经本包, 故不受"本包唯一"约束 (也别为迎合注释去改它)。
import requests


def _validated_tap_url(value: str, label: str = "TAP URL") -> str:
    """强校验 TAP URL: 仅绝对 http(s)、无凭据、无 query、无 fragment。

    Raises:
        ValueError: scheme 非 http(s)、缺 netloc、内嵌用户名/密码、带 query
            或 fragment — 任何一项都拒绝, 防止把 token 泄进 URL 或指向非预期
            端点。返回去掉末尾斜杠的规范化 URL。

    边界: query/fragment 判的是**非空** (urlparse 对裸 ``?``/``#`` 返回空串,
    为假值, 故 ``http://h/tap?`` 这类会放行)。空 query/fragment 不承载任何
    凭据, 且 :func:`_gateway_api_url` 走 urljoin 时会把它整段丢掉, 因此不构成
    泄漏面; 这里是"非空即拒", 不是"出现即拒"。
    """
    # 先 strip 再解析: 尾部空白会进 netloc 之外的字段, 绕过 scheme/netloc 校验
    parsed = urlparse(str(value).strip())                                                        # 先去空白再解析: 尾部空白会绕过方案与主机校验
    # 六项全否才放行: 凭据/query/fragment 任一存在都会让 token 泄进 URL 或把
    # 请求指向非预期端点 (代理日志与浏览器历史都会留痕), 因此一律拒绝而非修补
    if (                                                                                          # 六项条件同时成立才放行: 任一不满足都在此拒
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc                                                                        # 缺主机即拒: 相对地址不是可用端点
        or parsed.username is not None                                                       # 内嵌用户名即拒: 凭据会随 URL 落进代理日志与历史
        or parsed.password is not None                                                            # 内嵌口令即拒: 同上, 且更易被误当无害参数
        or parsed.query                                                                            # 带查询串即拒: 令牌不该出现在会留痕的位置 (裸 "?" 的空串为假, 不触发)
        or parsed.fragment                                                                      # 带片段即拒: 片段不进请求, 却会指向非预期端点 (裸 "#" 同上)
    ):
        raise ValueError(f"{label} must be an absolute HTTP(S) URL without credentials, query, or fragment")
    # 去掉末尾斜杠: 后续拼接一律经 urljoin 给绝对路径 (见 _gateway_api_url),
    # 留着斜杠只会被 urljoin 归一掉, 但显式剥掉更利于人读这份 base_url
    return str(value).strip().rstrip("/")


def _gateway_api_url(base_url: str, path: str) -> str:
    """从 TAP 端点推导网关自身的 API 端点 (``path`` 须以 ``/`` 开头)。

    查询端点与 API 端点共享同一 host 与端口, 区别只在路径前缀: TAP 挂在
    ``/tap`` 下, 交换 API 挂在站点根的 ``/api/v1/...``。因此这里用**以斜杠
    开头的绝对路径**做 urljoin, 由它替换 base_url 的整条路径。

    刻意不用 ``base_url[:-4]`` 那种定长切片: 切片假定 base_url 恰好以
    ``/tap`` 四字符结尾, 一旦调用方给的是完整 sync 端点
    (``.../tap/sync``) 就只切掉 ``sync``, 拼出 ``.../tap//api/v1/...``
    这个双斜杠端点 —— NADC 令牌因此发到非预期路径, 而失败只回一句泛化的
    RuntimeError, 现场极难看出是端点拼错了。urljoin 不依赖后缀长度, 也不会
    产生双斜杠。
    """
    return urljoin(base_url, path)  # 绝对路径替换整条路径: base_url 带不带子路径都得到同一个网关根


class BestTapClient:
    """选择并访问本地 BEST TAP 网关或远程 TAP 服务 (mode=auto/local/remote)。"""

    def __init__(
        self,                                                                                       # 实例: 端点与令牌都挂在会话上
        *,                                                                                    # 关键字参数: 后面几项都是可选配置, 位置传参易错位
        mode: str = "auto",
        tap_url: str | None = None,                                                                 # 远程端点可空: 缺省读环境变量
        local_url: str | None = None,                                                           # 本地端点可空: 缺省读环境变量, 再缺省回环地址
        access_token: str | None = None,                                                       # 令牌可空: 归一为空串, 后续真值判定不必处理空值
        service_factory: Callable[..., Any] | None = None,                                     # 服务工厂可空: 测试注入点, 缺省惰性导入可选依赖
    ) -> None:
        """构造客户端并建立 pyvo TAPService。

        Args:
            mode: ``auto`` 时按是否存在 ``BEST_TAP_URL`` 在 remote/local 间选择。
            tap_url: 远程 TAP 端点 (缺省读 ``BEST_TAP_URL``)。
            local_url: 本地网关端点 (缺省读 ``BEST_LOCAL_TAP_URL``, 兜底
                ``http://127.0.0.1:8000/tap``)。
            access_token: 可选 Bearer token, 直接装进会话头。
            service_factory: 测试注入点; 缺省时惰性导入 pyvo 的 ``TAPService``。

        Raises:
            ValueError: mode 非法、remote 模式缺 URL, 或 URL 未过强校验。
        """
        requested_mode = mode.strip().lower()  # 归一化后再进白名单: 大小写/空格不算非法 mode
        # 白名单而非 any(): 拼错的 mode 必须显式失败, 不能悄悄退化成 auto
        if requested_mode not in {"auto", "local", "remote"}:
            raise ValueError("TAP mode must be auto, local, or remote")
        remote_url = tap_url or os.environ.get("BEST_TAP_URL", "")  # 形参优先于环境变量
        # 本地端点有兜底值: 本地网关默认监听 8000, 让"起网关 + 跑脚本"无需
        # 先导出任何环境变量
        local_url = local_url or os.environ.get(                                               # 本地端点有兜底值: 起网关加跑脚本不必先导环境变量
            "BEST_LOCAL_TAP_URL", "http://127.0.0.1:8000/tap"
        )
        if requested_mode == "auto":
            # auto 的判据是"有没有配置远程端点", 而不是"远程是否可达" ——
            # 探测连通性会把构造客户端变成一个阻塞网络的动作
            self.mode = "remote" if remote_url else "local"
        else:
            self.mode = requested_mode                                                              # 显式模式原样落属性: 白名单已在上面判过
        if self.mode == "remote":
            if not remote_url:                                                            # 远程模式缺 URL 即拒: 静默换端点会让查询打到另一套数据
                # 显式 remote 却无 URL 是配置错误, 不退化成 local: 静默换端点
                # 会让查询打到另一套数据上, 且调用方毫无察觉
                raise ValueError("Remote TAP mode requires BEST_TAP_URL or tap_url")
            self.base_url = _validated_tap_url(remote_url)                                         # 远程端点过强校验: 凭据与查询串都不许出现
        else:
            self.base_url = _validated_tap_url(local_url, "Local TAP URL")

        # 显式持有一个 Session 而非用模块级 requests: 连接池复用 + 令牌头
        # 在整轮查询内保持一致, 避免每次请求重新握手
        self.session = requests.Session()                                                       # 自持会话: 连接池复用, 令牌头在整轮查询内一致
        self._access_token = access_token or ""  # 归一为空串: 后续真值判定不必再处理 None
        if self._access_token:                                                                      # 有令牌才装头: 匿名查询不携带多余凭证
            self.session.headers["Authorization"] = f"Bearer {self._access_token}"  # 装进会话头, 换 token 即覆盖
        if service_factory is None:                                                               # 未注入才导入可选依赖: 导入期不强求第三方库
            # 延迟导入 pyvo (零依赖原则): pyvo 是可选依赖, 模块导入期不强求;
            # 未安装时在此处显式 ImportError 失败, 绝不静默降级成不可用客户端
            from pyvo.dal import TAPService
            service_factory = TAPService                                                    # 工厂缺省取可选依赖: 未安装时在此显式失败, 不静默降级
        self._service = service_factory(self.base_url, session=self.session)                     # 用注入的工厂建服务: 替身与真实现走同一构造点

    def __repr__(self) -> str:
        """调试表示: 只暴露模式/端点/是否带凭证, 绝不含 token 本体。"""
        return f"BestTapClient(mode={self.mode!r}, base_url={self.base_url!r}, authenticated={bool(self._access_token)})"

    def set_access_token(self, access_token: str) -> None:
        """把 Bearer token 装进会话头, 供后续 search/download 使用。

        Raises:
            ValueError: token 为空字符串 — 拒绝安装空凭证。
        """
        if not access_token:                                                                        # 空令牌即拒: 不安装空凭证
            raise ValueError("access_token cannot be empty")
        self._access_token = access_token                                                           # 令牌落实例: 与会话头保持同一份
        self.session.headers["Authorization"] = f"Bearer {access_token}"  # 整体替换而非追加, 旧 token 不残留

    def exchange_nadc_token(self, access_token: str) -> str:
        """用 NADC access_token 换本地网关 API key (仅 local 模式可用)。

        协议阶段: POST 本地网关的 NADC token 交换端点, 上游凭据只在这一跳
        换成网关自己的 API key, 不流向 BEST 站点。任何网络/HTTP/JSON 失败都
        收敛为 RuntimeError, 不泄露原始响应体。

        Raises:
            ValueError: 客户端处于 remote 模式 (交换端点只存在于本地网关)。
            RuntimeError: 交换请求失败或网关未返回 api_key。
        """
        if self.mode != "local":
            # 交换端点只存在于本地网关, remote 模式下无此路径 —— 早失败优于
            # 跑完整轮 HTTPS 才拿到 404
            raise ValueError("NADC token exchange is available only in local gateway mode")
        # 由 TAP 端点推导网关自身 API 路径: 两种端点共享同一 host 与端口,
        # 区别只在路径前缀, 拼错前缀的 404 现场很难一眼看出
        endpoint = _gateway_api_url(self.base_url, "/api/v1/auth/nadc/token")  # urljoin 而非定长切片: 切片只认恰好以 /tap 结尾的 base_url
        try:
            response = self.session.post(                                                         # 按网关自身路径提交: 与查询端点只差路径前缀
                endpoint,                                                                         # 凭据只在这一跳交换: 不流向 BEST 站点
                json={"access_token": access_token},
                # 连接 5s / 读取 30s: 交换是一次小请求, 但对端可能正忙
                timeout=(5.0, 30.0),                                                            # 连接与读取分开: 交换是小请求, 但对端可能正忙
            )
            response.raise_for_status()                                                             # 状态码先判: 错误页不是交换结果
            api_key = response.json().get("api_key", "")  # 缺键取空串: 交给下面的空值判定统一收口
        except Exception as exc:
            # 任何失败都收敛为 RuntimeError 且不携带原始响应体: 响应体里可能
            # 含上游令牌, 拼进消息就会进日志
            raise RuntimeError("Local gateway NADC token exchange failed") from exc
        # 空 api_key 单独判: 网关返回 200 但没换到 key 时, 让调用方拿到
        # None 会在更远的地方炸成难以定位的错
        if not api_key:                                                                          # 空密钥单独判: 返回二百但没换到密钥要在此暴露
            raise RuntimeError("Local gateway did not return an API key")
        return str(api_key)  # 转 str: 网关返回非标类型时也不让调用方拿到裸值

    def search(self, query: str, *, maxrec: int | None = None):
        """经 pyvo 执行 ADQL 查询并返回 astropy Table。

        Args:
            query: ADQL 文本 (由服务端白名单解析, 客户端原样透传)。
            maxrec: 可选 MAXREC; 为 None 时不带该参数, 由服务端默认配额决定。

        Returns:
            pyvo/astropy 结果表 (``to_table()`` 之后)。
        """
        # maxrec=None 时**不传**该键: pyvo 对 maxrec=0 与"未传"语义不同,
        # 传 0 会被服务端当作"不要任何行"
        kwargs = {"maxrec": int(maxrec)} if maxrec is not None else {}
        return self._service.search(query, **kwargs).to_table()

    def download(
        self,                                                                                       # 实例: 落盘与查询走同一服务对象
        query: str,                                                                              # 查询文本: 原样透传, 解析在服务端白名单里做
        output: str | os.PathLike[str],                                                             # 目标路径: 波纹号会展开并解析成绝对路径
        *,                                                                                         # 关键字参数: 输出格式与行数上限都是可选项
        output_format: str = "votable",
        maxrec: int | None = None,                                                              # 行数上限可空: 不传该键与服务端默认配额语义不同
    ) -> str:
        """查询并原子落盘 (先写 ``.tmp`` 再 replace), 返回最终路径。

        Args:
            query: ADQL 文本。
            output: 目标文件路径 (``~`` 会展开并 resolve)。
            output_format: ``votable`` / ``csv`` / ``fits`` 之一。
            maxrec: 可选 MAXREC。

        Raises:
            ValueError: output_format 不在白名单内。

        Returns:
            str: 最终文件的绝对路径。
        """
        table = self.search(query, maxrec=maxrec)                                                   # 先查后写: 没有结果就不该产生空文件
        fmt = output_format.strip().lower()                                                         # 格式名归一: 大小写与空白在此收口
        # 白名单映射: astropy 写 csv 要 "ascii.csv" 而非 "csv", 少这一步
        # 会写出一个 VOTable 文本却顶着 .csv 后缀
        formats = {"votable": "votable", "csv": "ascii.csv", "fits": "fits"}
        if fmt not in formats:                                                                      # 白名单外即拒: 不静默回落成某一种格式
            raise ValueError("output_format must be votable, csv, or fits")
        target = Path(output).expanduser().resolve()                                                # 目标路径展开并解析: 落盘前落成绝对形态
        # 先建目录再写: 下载目标常指向尚未创建的输出目录
        target.parent.mkdir(parents=True, exist_ok=True)                                         # 父目录顺手建: 目标目录不存在时直接开写会失败
        # 原子落盘: 先写 .tmp 再 replace, 保证下游读到的永远是完整文件,
        # 不会撞上"写了一半就被轮询读到"的窗口
        temporary = target.with_suffix(target.suffix + ".tmp")
        table.write(str(temporary), format=formats[fmt], overwrite=True)                     # 先写临时文件: 目标文件此时还没被动过, 读者不受影响
        temporary.replace(target)                                                                # 原子替换: 读者只会看到完整旧文件或完整新文件
        return str(target)

    def close(self) -> None:
        """关闭底层 requests 会话 (释放连接池)。"""
        self.session.close()                                                                   # 显式关会话: 反复构造客户端时把句柄留给回收会耗尽
