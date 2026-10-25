"""src.tap.response — 网关响应载体 (status/headers/body) 与 XML 响应构造。

职责: 定义"触达 socket 之前的中间表示" :class:`TapResponse` 与唯一的构造出口
:func:`xml_response`。本模块不含任何路由、存储或 HTTP 服务器逻辑 —— 全部职责
就是"把一次请求的结果表示成可离线断言的值对象"。

所属子系统: 位于 src/ 的 TAP 协议层最底层, 是 service 与 uws_service 两者的
公共下游。上游由 ``src/tap/service.py`` (HTTP 路由) 与 ``src/tap/uws_service.py``
(异步作业状态机) 消费; 下游不消费任何东西 (叶子模块)。

对外接口:
- ``TapResponse``: 一次网关响应的值载体; 外部可依赖的 seam —— 路由层的返回
  值类型就是它, 换成别的类型等于改了 TAP 层公开签名。
- ``xml_response()``: 把 ElementTree 根节点包成 200 响应; 外部可依赖的 seam ——
  VOSI/UWS 文档的序列化口径 (必须带 XML 声明) 由它单点决定。

依赖与数据流: 只依赖标准库 ``dataclasses`` 与 ``xml.etree.ElementTree``, 无 IO、
无网络、无配置读取。数据全在内存内: 调用方传入已构造好的 ET 根节点, 本模块
同步序列化成 bytes 交上层写 socket, 不跨进程、不落盘。

关键契约与不变量:
- ``media_type`` 默认自带 ``charset=utf-8``。改默认值会让非 ASCII 错误文档在
  客户端乱码, 也与 UWS 规范的一致性检查对不上。
- ``body`` 是 ``bytes`` 而非 ``str``: socket 写出的最终形态是字节, 转换点应收在
  ``TapRequestHandler`` 一处, 避免各路由各自 encode 产生分歧。
- ``xml_response`` 固定 200 且强制 ``xml_declaration=True``: VOSI 客户端按
  声明里的编码解析, 缺声明会在非 UTF-8 环境下解析失败。

陷阱与边界: 抽成本模块的直接动因是打破循环依赖 —— ``uws_service`` 要构造
:class:`TapResponse`, 而 ``service`` 要 import ``uws_service``; 载体若留在
``service``, 二者只能靠运行时惰性导入相连, 那种绕环在启动期不报错、只在特定
import 顺序下才炸, 极难排查。``service.py`` 保留了对本模块符号的 re-export,
是为兼容既有 ``from src.tap.service import TapResponse`` 导入路径; 动那个
re-export 等于打断外部调用方, 不属于注释范畴。另: ``ET.tostring`` 不做缩进
美化, 因为响应体要尽量小, 缩进会让每个作业轮询响应膨胀数倍。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree import ElementTree as ET  # nosec B405  (仅用于**生成**对外 XML, 不解析外部输入)


@dataclass
class TapResponse:
    """一次网关响应 (status/headers/body) — 触达 socket 之前的中间表示。

    路由逻辑全部返回它而不直接写 socket, 使分发可脱离端口单测;
    ``TapRequestHandler`` 只是其 socket 适配器。

    Attributes:
        status: HTTP 状态码。
        body: 响应体字节。
        media_type: Content-Type (含 charset)。
        headers: 附加响应头 (如 ``Location`` for UWS 303 重定向)。
    """

    status: int
    body: bytes = b""  # 字节而非 str: encode 转换点本应收在 TapRequestHandler 一处, 但 uws_service.py 的
        # 179/190/226 三处各自 encode —— 两处口径并存, 待收敛
    # 默认值必须自带 charset: VOSI 客户端按声明的编码解析响应, 缺声明或缺
    # charset 时非 ASCII 错误文档会在客户端侧乱码
    media_type: str = "text/plain; charset=utf-8"
    # default_factory 而非 {} 字面量: dataclass 的可变默认值必须逐实例独立,
    # 否则所有响应共享同一个 dict, 一次 Location 写入会污染后续全部响应
    headers: dict[str, str] = field(default_factory=dict)


def xml_response(root: ET.Element, media_type: str = "application/xml") -> TapResponse:
    """把 ElementTree 根节点序列化为 200 XML 响应 (VOSI/UWS 文档出口)。

    状态码固定 200 且强制输出 XML 声明: 本函数是"成功文档"的单点出口, 错误
    文档由各路由显式构造带状态的 TapResponse, 二者不会混淆。

    Args:
        root: ElementTree 根节点 (标签与命名空间合法性由调用方校验; 本函数不
            校验也不改写, 以免同一份文档在上游被改写两次)。
        media_type: 响应媒体类型; 传非 XML 类型会让客户端按错误类型解析。

    Returns:
        TapResponse: 状态 200、带 XML 声明的响应载体。
    """
    return TapResponse(
        status=200,  # 固定 200: 错误文档由各路由显式构造带状态的响应, 二者不混淆
        # encoding 与 xml_declaration 必须同时给: 只给 encoding 时 tostring
        # 静默返回 str 且不带声明, 声明与实际字节编码不一致必然解码错位
        body=ET.tostring(root, encoding="utf-8", xml_declaration=True),  # 强制带 XML 声明, VOSI 客户端靠它定编码
        media_type=media_type,
    )
