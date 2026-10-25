"""scripts.best_cone_search — BEST cone search via form-based REST API.

能力边界: 公开锥形检索入口 (scripts 命名空间)。边界: 入口接线入参校验 (Q-51); 默认复用模块级共享 client 防 session 泄漏 (Q-18); 业务委派 src.client。
白盒锚点: references/ALGORITHM-SPEC.md §2 (best_cone_search 锚点)。
"""
from __future__ import annotations

# 标准库: 可选类型标注 (client 参数可空, 走共享实例回退)
from typing import Optional

# 本地三件: client 层提供 BEST form-based REST 会话与锥检索 HTTP 调用;
# 查询结果领域模型 (sources/success 等字段); 校验逻辑全在 guards, 本文件不复制。
# 逐条说明写在这个 import 块上方而不是每行行尾: 块内行尾注释会被 isort 当成
# 块的一部分而拒绝格式化, 触发 ruff I001。
# Q-51 入口防线: 负 RA/0 半径不在本文件直传服务端 (validate_coordinate /
#   validate_search_radius 是唯一校验点); Q-18: client 必须是下面那个模块级
#   共享实例, 公开函数每次新建 BestClient 会泄漏 session。
from src.client import BestClient
from src.models import BestQueryResult
from src.scripts.guards import validate_coordinate, validate_search_radius

# Q-18: 模块级共享 client (公开函数每次新建 BestClient 会泄漏 session);
# 惰性创建, 调用方仍可注入自有 client。
_SHARED_CLIENT: Optional[BestClient] = None  # 进程内单例缓存: None 表示尚未建过


def _shared_client() -> BestClient:
    """取模块级共享 BestClient (懒创建; 进程内复用同一 session)。"""
    global _SHARED_CLIENT                                                                  # 共享客户端是模块级: 复用连接与限流器, 免得每次调用重连
    if _SHARED_CLIENT is None:  # 首次调用才建: import 期不触网
        _SHARED_CLIENT = BestClient()  # 带限流/重试/超时默认值的生产客户端
    return _SHARED_CLIENT


def cone_search(
    ra: float, dec: float, radius_arcsec: float = 60.0,
    catalog: str = "ps1", band: Optional[str] = None,
    max_records: int = 1000, client: Optional[BestClient] = None,
) -> BestQueryResult:
    """对 BEST 数据库执行锥形检索 (公开入口)。

    Q-51: 入口调用 validate_coordinate/validate_search_radius (负 RA/0 半径/
    超限半径不再直传服务端)。
    Q-18: 缺省 client 用模块级共享实例 (防 session 泄漏)。

    Args:
        ra: 赤经 (度, ICRS)。
        dec: 赤纬 (度, ICRS)。
        radius_arcsec: 检索半径 (角秒)。
        catalog: 目标星表 (ps1, std, stripe82, gaia_dr3 等)。
        band: 可选波段过滤。
        max_records: 最大返回记录数。
        client: 可选调用方预配置的 client (注入后不用共享实例)。

    Returns:
        BestQueryResult (sources 为 BestSource 领域对象列表)。

    Raises:
        ValueError: 坐标越界或半径非正/超限 (入口防线, 不发请求)。
    """
    ra, dec = validate_coordinate(ra, dec)  # 入口即拒: 越界坐标不发请求, 零线网成本
    radius_arcsec = validate_search_radius(radius_arcsec)  # 半径同样入口校验 (正数且不超上限)
    if client is None:                                                                              # 没有共享实例才新建
        client = _shared_client()  # 缺省走模块级共享实例, 避免每次调用泄漏 session
    # 委派 src.client 发起 BEST 锥检索 HTTP 请求 (form-based REST)
    return client.cone_search(ra, dec, radius_arcsec, catalog=catalog, band=band, max_records=max_records)  # 业务全部下沉 client 层
