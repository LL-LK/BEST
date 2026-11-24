# -*- coding: utf-8 -*-
"""src.client_resolve — BestClient 的天体名解析面 (抽离件, budget §3.2 阶段 3)。

能力边界: ``/nss/solve`` 端点 (CDS Sesame 代理) 的**唯一实现** —— 入口空判、
URL 编码、软错误体判定、200 + 失败标记判定、协议层回包解析, 五步合起来
就是"把一个天体名变成 ICRS 坐标或一条显式失败"。抽离缘由: client.py 实测
557 净行仍超 400 预算, 而本面与两阶段查询协议**完全正交** —— 它不建 sqlid
会话、不分页、不解析 CSV, 失败语义也是另一套 (NameResolveError / Soft404Error,
不是 BestQueryResult 信封), 因此按 §3.9 原则 1「只抽与主链正交的关注点」摘出。

契约 (与阶段 1/2 同款):
  - 原地委派壳: ``BestClient.resolve_name`` 保留同名同签名 (测试对实例方法的
    patch 依然生效 —— file-size-budget §3.2 实测该性质);
  - self 依赖面只有 ``session`` / ``base_url`` / ``_rate_limit_wait`` /
    ``request_timeout``, 全部经 client 参数穿透, 无隐藏耦合;
  - 失败语义逐条不变: 空名 → NameResolveError; 网络失败 → NameResolveError
    (不泄漏 requests 类型); 路由软错误体 → Soft404Error; 回包不可解析 →
    NameResolveError; HTTP 200 + Sesame 失败标记 → NameResolveError (附
    remark)。五种失败**互不同形**, 绝不折叠成"查无此源"的空结果。

白盒锚点: src/client.py (公开 seam 委派壳与其余查询面) / src/protocol.py
(端点常量、软错误判定、回包解析的权威层 —— 本模块只编排不复制)。
"""
from __future__ import annotations

# 标准库: 目标名含空格与加号, 不编码会被解析成另一个天体
from urllib.parse import quote

# 第三方: requests 会话 (网络异常类型判定 —— 失败要归一为 NameResolveError)
import requests

# 本地: 名称解析结果载体, 与协议层权威件 (端点路径/软错误判定/回包解析/
# 失败标记判定)。解析规则只在协议层有一份, 本模块不持第二份。
from src.models import ResolvedName
from src.protocol import (
    NSS_SOLVE_PATH,  # 名称解析端点路径: 代理 Sesame, 与星表查询同源不同路由
    NameResolveError,  # 名称解析失败异常: 网络失败与不可解析都归一到这里
    Soft404Error,  # 路由级软失败异常: 与业务性空结果严格分开
    is_name_resolve_failure,  # 判 Sesame 的失败标记: 200 回包不等于解析成功
    is_soft_error,  # 判 200 携带的软错误体: 状态码白名单看不见它
    parse_name_resolve,  # 解析回包成结构体: 哨兵值判定归协议层一处
    soft_error_detail,  # 从软错误体取可读 detail: 取不到时调用方要自己兜底
)


def resolve_name(client, name: str) -> ResolvedName:
    """通过 ``/nss/solve`` 把天体名解析为 ICRS 坐标 (CDS Sesame 代理)。

    该端点代理 CDS Sesame, 失败时在 HTTP 200 Body 内返回
    ``ra=dec=-1000`` 哨兵值, 因此软错误与哨兵值都要显式检查 ——
    agent 说"查 M31 的标准星"时不再需要自己先找坐标, 也不会把错误
    坐标当成结果收下。

    Args:
        client: 客户端实例: 会话、站点根与限流时钟都在它身上
        name: Sesame 可识别的天体名 (如 ``"M31"``)

    Returns:
        ResolvedName (``remark`` 是 Sesame 的外部内容, 不自动抓取 — S-3)

    Raises:
        NameResolveError: 名称无法解析 (哨兵值或不可解析回包)
        Soft404Error: 路由本身返回软错误 Body
    """
    obj = str(name or "").strip()  # 去空白后再判空: 纯空格名是调用方笔误, 不是合法天体
    if not obj:                    # 入口即拒: 下游不必各自处理空 obj 的回包形态
        raise NameResolveError("an object name is required")
    # 走同一把限流: 解析服务与星表查询共用会话, 只限星表会被解析
    # 请求绕过, 两者打的是同一个上游。
    client._rate_limit_wait()  # 解析端点与星表查询同上游, 必须共用同一把限流
    # quote: 目标名可含空格与 + 号 (M31 命名), 不编码会被 Sesame
    # 当成参数分隔而解析成另一个天体。
    url = f"{client.base_url}/{NSS_SOLVE_PATH}?obj={quote(obj)}"  # 端点常量取自协议层: 路径变更只改一处
    try:
        # Sesame 代理 GET: 名称 URL 编码后作 obj 参数; 网络失败归为
        # NameResolveError (调用方只需捕一种异常), 不泄漏 requests 细节
        resp = client.session.get(url, timeout=client.request_timeout)  # 超时取实例口径: 显式配置才生效, 缺省即 REQUEST_TIMEOUT
        resp.raise_for_status()                                # 状态码先判: 5xx 时 resp.text 是错误页, 不是解析回包
    except requests.RequestException as exc:
        raise NameResolveError(f"solve request for {obj!r} failed: {exc}") from exc  # 网络失败归一为一种异常: 调用方只捕一种, 不泄漏 requests 类型
    if is_soft_error(resp.text):                                                     # 200 也可能是软错误体: 路由不存在时状态码照样是 200
        raise Soft404Error(soft_error_detail(resp.text) or "soft error", url)
    try:
        payload = parse_name_resolve(resp.text)  # 解析只在协议层一份, 哨兵值与失败标记都归它判
    except ValueError as exc:
        raise NameResolveError(f"unparseable solve response for {obj!r}: {exc}") from exc  # 回包不可解析是失败不是空结果, 静默会把两种语义混同
    # HTTP 200 不代表解析成功: Sesame 对查无此名返回 200 + 失败标记,
    # 不显式判这一层就会把"没找到"当成"找到空结果"返回给用户。
    if is_name_resolve_failure(payload):  # 查无此名回 200 加失败标记, 漏判就当成了空的正常结果
        raise NameResolveError(
            f"could not resolve {obj!r}", remark=str(payload.get("remark") or "")  # remark 是 Sesame 的外部内容, 只透传显示, 不自动抓取展开
        )
    return ResolvedName.from_payload(obj, payload)  # 回填原始目标名: 下游不必再从入参猜搜的是谁
