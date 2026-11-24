"""scripts.best_crossmatch_pipeline — Coordinate cross-match against BEST.

能力边界: 批量交叉匹配管线 (crossmatch_with_gaia/with_ps1/batch)。边界: manifest 声明单点失败隔离; 逐点异常进 errors 不中断批次 (Q-17); 三个单点入口缺省复用模块级共享 client 防 session 泄漏 (Q-18 同形态, 裁决见下方注释块)。
白盒锚点: references/ALGORITHM-SPEC.md §2 (crossmatch_with_gaia 锚点)。
"""
from __future__ import annotations

# 标准库: 类型标注
from typing import Any, Optional

# 本地: client 层提供 REST 会话 (三个公开入口缺省复用模块级共享实例, A1)
from src.client import BestClient

# 本地: 交叉匹配领域逻辑 (逐点锥检索 + 匹配组装)
from src.crossmatch import BestCrossMatch

# 本地: 查询结果领域模型
from src.models import BestQueryResult

# A1 裁决 (docs/architecture/file-size-budget.md §6 A1): 三个入口必须共用同一个
# BestClient, 不得每次调用新建。"每次新建是刻意的 — 共享会让限流时钟跨调用串味,
# 也会让取消语义无法按调用边界生效"这一说法不成立, 逐条核对如下:
#   ① 限流时钟: BestClient.rate_limit 的契约是"全局最小请求间隔"
#      (src/client.py 构造 docstring 原文), 时钟跨调用正是设计意图; 且这三个
#      入口都是单次短请求、不暴露 rate_limit 参数 (用默认值), 共享只是兑现
#      契约。反过来每次新建才危险: _last_request_time 初始为 0, 新实例的首
#      个请求永不等候, 循环调用等于把限流整个绕过, 直连上游。
#   ② 取消语义: 取消只存在于 download_manager 的 job 作用域
#      (JobCancelledError 由 _check_cancelled 在页边界抛出); 这三个入口既没有
#      job_id 也没有取消回调, 调用链上不存在任何取消检查点 — "按调用边界
#      取消"在这里没有作用对象。登记在案的正确形态 batch_crossmatch (一批
#      一个 client) 同样让节流时钟跨请求共享, 与该反驳自相矛盾。
# 结论: 与 best_cone_search 的 Q-18 修法对齐 — 模块级惰性共享 client, 同时
# 开放 client 注入参数, 调用方需要自有会话/限流/认证时显式传入。
_SHARED_CLIENT: Optional[BestClient] = None  # 进程内单例: 节流时钟跨调用共享是契约, 不是副作用


def _shared_client() -> BestClient:
    """取模块级共享 BestClient (懒创建; 进程内复用同一 session, Q-18 同形态)。"""
    global _SHARED_CLIENT  # 模块级槽位: 惰性创建与复用都写这一处
    if _SHARED_CLIENT is None:  # 懒建: import 期不发请求, 未用到就不付建连代价
        _SHARED_CLIENT = BestClient()
    return _SHARED_CLIENT


def crossmatch_coords(
    ra_list: list[float], dec_list: list[float],
    catalog: str = "ps1", radius_arcsec: float = 3.0,
    client: Optional[BestClient] = None,
) -> BestQueryResult:
    """把坐标列表批量交叉匹配到 BEST 星表。

    Q-18/A1: 缺省 client 用模块级共享实例 (公开入口每次新建 BestClient 会
    泄漏 session); 调用方可用 ``client`` 注入自有会话。

    Args:
        ra_list: 赤经列表 (度, ICRS)。
        dec_list: 赤纬列表 (度, ICRS); 与 ra_list 等长。
        catalog: 目标星表 (默认 ps1)。
        radius_arcsec: 匹配半径 (角秒)。
        client: 可选调用方预配置的 client (注入后不用共享实例)。

    Returns:
        BestQueryResult (逐输入坐标的匹配结果)。
    """
    if client is None:  # 未注入才回落: 调用方给了自有会话就不碰共享实例
        # A1: 缺省走模块级共享 client (Q-18 同形态; 每次新建会泄漏 session)
        client = _shared_client()
    xm = BestCrossMatch(client)  # 交叉匹配对象只借 client 会话, 自己不持有连接
    # BestCrossMatch 内部对每个坐标发起一次锥检索 HTTP 请求
    return xm.crossmatch_coords(ra_list, dec_list, catalog, radius_arcsec)


def crossmatch_with_gaia(
    ra: float, dec: float, search_radius_arcsec: float = 5.0,  # 默认半径比单点口宽一档: Gaia 位置精度低于 Pan-STARRS
    client: Optional[BestClient] = None,
) -> Optional[dict[str, Any]]:
    """与 BEST 的 Gaia DR3 校准星表做单目标交叉匹配。

    Q-18/A1: 缺省 client 用模块级共享实例 (防 session 泄漏)。

    Args:
        ra: 赤经 (度, ICRS)。
        dec: 赤纬 (度, ICRS)。
        search_radius_arcsec: 搜索半径 (角秒)。
        client: 可选调用方预配置的 client (注入后不用共享实例)。

    Returns:
        最佳匹配源的 dict; 无匹配/查询失败时 None。
    """
    if client is None:  # 未注入才回落: 与另两个单点入口同一纪律
        # A1: gaia 单点入口同样缺省走共享 client (Q-18 同形态, 防 session 泄漏)
        client = _shared_client()
    # 对 gaia_dr3 星表发起单点锥检索 HTTP 请求 (max_records=1 取最近邻)
    result = client.cone_search(ra, dec, search_radius_arcsec, catalog="gaia_dr3", max_records=1)  # 单点检索只要最近邻: 取回上限设为 1 就够, 少取即少传
    if result.success and result.sources:  # 成功且非空才取首位; 任一不满足即视为无匹配
        return result.sources[0].to_dict()  # 单点契约: 返回最近邻 dict, 失败语义是 None
    return None


def crossmatch_with_ps1(
    ra: float, dec: float, search_radius_arcsec: float = 3.0,  # 默认半径同坐标匹配口: 两个入口的口径保持一致
    client: Optional[BestClient] = None,
) -> Optional[dict[str, Any]]:
    """与 BEST 的 Pan-STARRS (ps1) 星表做单目标交叉匹配。

    Q-18/A1: 缺省 client 用模块级共享实例 (防 session 泄漏)。

    Args:
        ra: 赤经 (度, ICRS)。
        dec: 赤纬 (度, ICRS)。
        search_radius_arcsec: 搜索半径 (角秒)。
        client: 可选调用方预配置的 client (注入后不用共享实例)。

    Returns:
        最佳匹配源的 dict; 无匹配/查询失败时 None。
    """
    if client is None:  # 未注入才回落: 共享实例的节流时钟跨调用共享是契约
        # A1: ps1 单点入口同样缺省走共享 client (Q-18 同形态, 防 session 泄漏)
        client = _shared_client()
    # 对 ps1 星表发起单点锥检索 HTTP 请求 (max_records=1 取最近邻)
    result = client.cone_search(ra, dec, search_radius_arcsec, catalog="ps1", max_records=1)  # 单点检索只要最近邻: 同样把上限压到 1
    if result.success and result.sources:  # 同 gaia 入口: 成功且非空才取首位
        return result.sources[0].to_dict()  # 单点契约: 返回最近邻 dict, 失败语义是 None
    return None


def batch_crossmatch(
    coords: list[tuple[float, float]] | list[list[float]],  # 坐标对支持元组与列表: 两种形态都常见, 不做形态偏好
    search_radius_arcsec: float = 5.0,  # 批级半径: 与单点入口同一单位角秒
    catalogs: tuple[str, ...] = ("gaia_dr3",),  # 依次尝试的星表: 逐表独立记成败, 不因一张表失败放弃整批
    rate_limit: float = 0.0,  # 不限速为缺省: 离线测试路径需要, 线上调用方应显式给间隔
) -> list[dict[str, Any]]:
    """批量交叉匹配: 逐坐标调用单目标匹配, 单点失败隔离不中断批次。

    Args:
        coords: (ra, dec) 度数对列表
        search_radius_arcsec: 搜索半径 (角秒)
        catalogs: 依次尝试的 BEST 校准星表
        rate_limit: 请求间隔 (秒); 0 = 不限速 (离线测试路径)

    Returns:
        List of {"input": [ra, dec], "matches": {...}, "misses": [...], "errors": [...]}。
        ``misses`` 只装查无此项的星表名, ``errors`` 只装 ``"星表: 异常"`` 文本 —
        两者分通道, 调用方不必靠字符串形态猜语义 (YZ-27)。
    """
    # A1 参照形态: batch_crossmatch 是"一批一个 client"的正确形态 — rate_limit
    # 是批级参数, 每批按调用方给定值新建, 节流时钟在一批内共享即设计意图。
    # 用上下文管理器: client 底下的 requests.Session 持有连接池, 批处理循环里
    # 每批一个 client, 不显式关闭就把句柄留到回收时机 —— 单次调用看不出问题,
    # 长跑批处理会一路累积。
    records: list[dict[str, Any]] = []  # 结果容器: 每个输入坐标占一条, 坏点也占位
    with BestClient(rate_limit=rate_limit) as client:  # 一批一个客户端: 限流是批级参数, 时钟在一批内共享
        for pair in coords:  # 单点隔离: 任何一点异常不中断整批
            try:
                ra, dec = float(pair[0]), float(pair[1])  # 强转 float: 字符串坐标也要能进匹配
            except (TypeError, ValueError):
                records.append({"input": list(pair), "matches": {}, "misses": [], "errors": ["invalid_coord"]})  # 坏点占位不丢槽位
                continue
            matches: dict[str, Any] = {}  # 匹配表: 星表名为键, 便于逐表核对命中情况
            misses: list[str] = []  # 逐星表累计查无此项, 成功则该表不出现在 misses
            errors: list[str] = []  # 逐星表累计异常, 与 misses 分开: 失败原因与查无此项混在同一无类型 list 就没法区分故障与空场
            for cat in catalogs:  # 逐表尝试: 一张表失败不影响其余表
                try:
                    # 逐星表发起锥检索 HTTP 请求 (max_records=1; 失败降级为 error)
                    result = client.cone_search(ra, dec, float(search_radius_arcsec),  # 逐表锥检索: 单点失败降级为一条错误记录而非中断
                                                catalog=cat, max_records=1)
                except Exception as exc:  # noqa: BLE001 — 最佳努力批处理
                    errors.append(f"{cat}: {exc}")  # 记异常原因: 调用方据此判断该重试哪张表
                    continue
                if result.success and result.sources:  # 成功且非空才算命中: 任一不满足都只是这一张表没匹配上
                    matches[cat] = result.sources[0].to_dict()
                else:
                    misses.append(cat)  # 无命中记表名: 查无此项与异常分开, 便于区分空场与故障
            records.append({"input": [ra, dec], "matches": matches, "misses": misses, "errors": errors})  # 四段结构: 输入坐标、命中表、未命中表、异常表, 缺一复核者就没法判读
    return records
