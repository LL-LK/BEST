"""BEST 真实表单/sqlid 两阶段协议的共享辅助层 (全包唯一权威协议层)。

能力边界: **权威协议层**: 星表登记/别名/导航组、表单键集 (build_query_form)、CSV 解析(parse_csv_rows, 表头动态判定)、计数解析 (parse_count)、sqlid 规范化、软 404 检测 (is_soft_error/Soft404Error, P0-3)、名称解算 (/nss/solve 哨兵)、波段列名解析 (magnitude_column/quality_column)、连接常量 (BEST_BASE_URL/REQUEST_TIMEOUT)。边界: 全包唯一表头假设与键集出处; 客户端不得自建表单或自解析 CSV。
白盒锚点: references/ALGORITHM-SPEC.md §1 (端点表) / §2 (锚点表); contracts/fields/*.contract.yaml。

BEST 尚未提供 TAP 服务: 公开星表页走两步工作流 —— 先提交 Django 表单换一个
``sqlid`` (查询会话号), 再用 ``/sqlid/{sqlid}`` 分页取回该查询的行。本模块把全部
线上报文细节 (端点路径/表单键/表头假设/错误判定) 收敛到一处, 使
:class:`src.client.BestClient` 不会各写一份而漂移 (src 下只有一个生产客户端
类, 不存在第二份要与之漂移的副本)。
"""

from __future__ import annotations

# 标准库: csv 解析 BEST 导出行 / io 把响应文本包成文件对象 / json 解析计数与
# soft-error 响应体 / logging 记录列错位告警 (P1-1) / re 做 sqlid 与列名白名单校验。
import csv
import io
import json
import logging
import re

# 标准库(抽象与类型): 约束项鸭子类型判定 (Mapping) 与集合/可选类型注解 /
# urlencode 构造 phase-2 分页 URL 查询串。
from collections.abc import Iterable, Mapping
from typing import Any, Optional
from urllib.parse import urlencode

# 星表侧数据表 (路径/分组/别名/显示名/showcol 表单表/响应列/星等列/星等误差列/
# 质量列) 已移至 src.protocol_catalog_tables —— 那是 571 净行纯数据, 与协议逻辑
# 混放会稀释"必须读的逻辑量" (400 行净代码预算约束的是逻辑量, 数据表不该占额度)。
# 此处 re-export 保留公开导入路径, 既有 ``from src.protocol import CATALOG_PATHS``
# 一类调用不受影响。
from src.protocol_catalog_tables import (  # noqa: F401  (re-export)
    CATALOG_ALIASES,  # 旧拼写归一表: 查表前先经它, 否则旧别名在路径表里查不到
    CATALOG_COLUMNS,  # 该星表发布的响应列清单: 表头修复与列白名单的唯一来源
    CATALOG_DISPLAY,  # 星表展示名: 只用于人读输出, 不参与任何路由判定
    CATALOG_FORM_TABLES,  # 多表星表的表单表名集合: 长表名优先决定列名前缀归属
    CATALOG_GROUPS,  # 导航分组: 组名不是可查询路由, 只用来展开成员与报错提示
    CATALOG_MAG_COLUMNS,  # 波段标签到星等列的映射: 猜列名的启发式一律不作数
    CATALOG_MAG_ERROR_COLUMNS,  # 星等误差列: 只用于误差展示, 不参与波段过滤
    CATALOG_PATHS,  # 星表 id 到查询路径的映射: 存活路由的唯一判据
    QUALITY_COLUMNS,  # 质量指标到列的映射: 查不到即抛, 不去约束不存在的列
)

# 本地: 半径校验单点 —— ``nan <= 0`` 恒判 False, 纯比较式守卫对 NaN 天然 fail-open
# (同 src/scripts/guards.py 的理由, YZ-07), 故本层复用该单点而不另写第二份判据。
from src.scripts.guards import validate_search_radius

# 连接常量只在本模块定义 (不在客户端各写一份), 使 ``BestClient`` 不会在
# base URL / 超时上漂移; src 侧由 src/client.py 再导出这些名字, 供既有 import 方继续使用。
# 权威来源: 线上服务实测; 消费方: src 客户端模块的全部 HTTP 请求。
BEST_BASE_URL = "https://nadc.china-vo.org/data/best"                                           # 连接常量的单一事实源: 客户端不再各写一份基地址
# 单次 HTTP 请求超时 (秒): 覆盖 BEST 大结果集的生成耗时; 消费方同上。
REQUEST_TIMEOUT = 120  # 秒; 覆盖大结果集生成耗时, 短超时会把正常查询误判失败


def resolve_catalog(name: str) -> str:
    """把星表名 (含旧拼写) 解析为现存可查询 id。

    Args:
        name: 星表 id、旧拼写别名或导航分组名 (``std``/``calib``/``other``)。

    Returns:
        可查询星表 id (必然在 :data:`CATALOG_PATHS` 中)。

    Raises:
        ValueError: 传入的是导航分组名 —— 带上其成员表列表报错, 而不是解析成
            一个服务端会以 ``Internal Server Error`` 回应的 ``/q`` 路由;
            或名称完全未知。
    """
    key = str(name).strip()   # 去空白再判: 名称多来自命令行与文件, 常带换行
    if key in CATALOG_PATHS:  # 存活表优先: 别名与分组表都不许覆盖真实路由
        return key
    aliased = CATALOG_ALIASES.get(key)  # 旧拼写归一后才允许进后续查表
    if aliased:                         # 别名表是显式登记的, 查不到即真未知而非可猜
        return aliased
    if key in CATALOG_GROUPS:  # 分组单独分支: 它是导航结构, /q 路由并不接受
        members = ", ".join(CATALOG_GROUPS[key])
        raise ValueError(
            f"BEST has no queryable catalogue {key!r}; it is the navigation group "
            f"holding {members}. Pick one of those ids instead."
        )
    raise ValueError(f"Unknown BEST catalog: {name!r}")


def catalog_tables(catalog: str) -> tuple[str, ...]:
    """返回该星表 ``showcol`` 可取列的表名, 长表名优先 (最长前缀先匹配)。

    Args:
        catalog: 星表 id 或旧拼写别名 (先经 :data:`CATALOG_ALIASES` 归一)。

    Returns:
        表名元组; 未登记多表结构的星表返回 ``(resolved,)`` 单表。
    """
    resolved = CATALOG_ALIASES.get(catalog, catalog)  # 旧拼写先归一, 否则多表结构查不到
    tables = CATALOG_FORM_TABLES.get(resolved)                                                   # 多表结构查表: 未登记多表的星表走下方单表兜底
    if tables:                                                                                    # 有登记才按多表处理: 单表星表不需要前缀剥离
        return tuple(sorted(tables, key=len, reverse=True))
    return (resolved,)

# 线上端点路径, 与它们服务的星表定义放在一起, 避免端点散落在客户端里。
# 消费方: src 客户端模块拼 URL; ``sqlid`` 第二阶段通过会话分页取行; ``getcount``
# 只要数字 id (``s3839`` -> ``3839``) 并返回 ``{"total": N}`` (由 parse_count 解析)。
SQLID_PATH = "sqlid/{sqlid}"                                                               # 阶段 2 取数路径模板: 只认带 s 前缀或纯数字的会话号
GETCOUNT_PATH = "sqlid/{count}/getcount"                                                    # 计数端点只认数字部分: 拼 URL 前必须先剥 s 前缀

# ``/nss/solve?obj=`` 代理 CDS Sesame 做天体名解算 (P1-8): 权威来源为线上端点实测。
# 消费方: src 客户端的 name-resolve 路径 + protocol.parse_name_resolve /
# is_name_resolve_failure / models.ResolvedName。
# 失败是哨兵对 (ra=dec=-1000), 绝不是 HTTP 错误 —— 调用方必须检查数值而不是状态码。
NSS_SOLVE_PATH = "nss/solve"                                                               # 名称解算端点: 失败回 200 加哨兵值, 不能按状态码判
NAME_RESOLVE_FAIL_SENTINEL = -1000.0  # 哨兵不是状态码: 失败也回 200, 只能按数值判

# ``fits`` 不在任何 BEST 导出菜单里: 请求它返回的是 HTML 结果页而不是 FITS 文档,
# 因此不是受支持的导出格式。权威来源: 线上导出菜单实测; 消费方: build_query_form
# 的 output_format 校验与客户端下载路径。
SUPPORTED_OUTPUT_FORMATS: tuple[str, ...] = ("csv", "txt", "json", "votable")         # 导出格式白名单: 不含 fits, 请求它只会拿到 HTML 结果页
# 第一阶段 (建 sqlid) 的提交格式: 只有 ``html`` 提交才会回交 ``sqlid``;
# csv/json/votable/txt 会让服务端直接内联流式返回行, 两阶段分页协议就丢了。
PHASE1_HANDOFF_FORMAT = "html"                                                                 # 阶段 1 恒提交 html: 别的形态拿不回会话号


def validate_export_format(fmt: str) -> str:
    """校验导出格式白名单 (P2-9/SA-P2-5): csv/txt/json/votable 之一。

    阶段 2 分页**始终以 csv 拉取后本地解析** — 调用方声明的导出格式只进
    ``query_params`` 溯源, 真正的格式转换发生在落盘层 (serialization)。
    对 output_format 必须零容忍: 不校验的话, 请求 ``json`` 会拿到 csv 解析
    结果且无任何提示, ``fits`` 这类站点根本不服务的值也能直入表单。

    Args:
        fmt: 待校验的格式名 (大小写不敏感)。

    Returns:
        归一化 (strip+lower) 后的格式名。

    Raises:
        ValueError: 格式不在 :data:`SUPPORTED_OUTPUT_FORMATS` 白名单内。
    """
    key = str(fmt or "").strip().lower()
    if key not in SUPPORTED_OUTPUT_FORMATS:                                                   # 白名单外显式拒: 静默通过会让声明格式与实际回包不符
        raise ValueError(
            f"unsupported output format {fmt!r} "
            f"(allowed: {', '.join(SUPPORTED_OUTPUT_FORMATS)}); note phase-2 "
            f"always fetches csv and the export format is applied at save time"
        )
    return key

# ---------------------------------------------------------------------------
# 分页定序 (P0-1): 无 ORDER BY 时服务端不保证稳定行序 —— 线上实测同一 sqlid
# 连续两次 GET (不带 sort/order) 行数相同但行序不同, 集合重叠仅 1/50 (见
# references/site-endpoints-and-interactions.md 分页排序非确定一行)。用
# ``page=N`` 偏移翻页会静默重复行与丢行 (不抛异常, truncated 也不置位),
# 因此阶段 2 分页**尽量**携带确定性排序列。
# ⚠ **这是尽力而为, 不是保证** (H3-03 实测订正): 服务端只按它**认得的列**排序,
# 而本表登记的排序列可能整列为空 —— ps1 注入 ``ps1_source_id``, 实测 174/174
# 行为空, 于是该注入对 ps1 是空操作, 行序实际取决于**未声明的服务端行为**。
# 本轮观测未见问题 (跨两个独立会话、跨中断边界产物逐字节相同), 但那是观测不是
# 契约。**排序列是否为空还取决于天区与记录类型**: ps1 混对象记录 (id 非空) 与
# 点源记录 (整列空串)。要真正定序只能换一个线上确有取值的列 (如 ``ps1_ra``),
# 那会改变请求形态与产物字节序 —— 未取证前不做, 详见 SSOT 同名两行。
# 2026-10-05 **全 12 表逐张实跑**订正 (85 请求零失败, 逐表清单见 SSOT §11.1):
# 登记的排序列里**只有 ps1 是空列** (0/1000); 其余 9 张有数据的表排序列**全部非空**
# 且 asc/desc **双向单调** (7 张数值 + 2 张字符串字典序) —— 注入在这些表上真的在排。
# ``landolt``/``jplus_dr3`` 覆盖恒 0 无数据行, **未取证**。故丢行/重行的风险面
# 集中在 **ps1 一张表**, 而不是全部 12 张 —— 但"尽力而为"的定性不变。
# 权威来源: 同上文档的 sort+order 端点参数形态与"注入的排序列可能整列为空"一行;
# 消费方: build_page_url (两个客户端分页 URL 的唯一构造单点, 取代各自硬编码的
# 查询串)。键为星表 id, 值为该星表的默认排序列 (响应列名): 优先取 ID 类列, 无 ID
# 列的星表 (jplus_dr3) 退到坐标列 —— 单列不足保证唯一, 但远优于完全无序。
# 2026-09-29 线上核验: smss_dr4/uss_dr1 不再发布 source_id (幻影排序列会被
# 服务端静默忽略, asc/desc 实测不反转), 分别退到坐标列; uss_dr1 的坐标列是
# 按波段的 ``uss_dr1_ra_u`` (该星表 CSV 响应虽用裸名 ``ra_u``, 但 sort 参数
# 与站点 datagrid 一样接受带前缀拼写, asc/desc 实测两种都生效)。
# ⚠ uss_dr1 另有一条**方向**陷阱 (2026-10-05 实测, SSOT §11.2): 同一 sqlid 下
# ``order=asc`` 首页 200 行 ``ra_u`` 全有值, ``order=desc`` 首页 200 行 ``ra_u``
# **全是 nan** 且与 asc **零行重叠** (NULL 块在 desc 被顶到开头)。默认 asc 不受影响,
# **调用方不要在 uss_dr1 上显式请求 desc**。
PAGINATION_SORT_COLUMNS: dict[str, str] = {                                               # 键为星表 id 值为确定性排序列: 无序分页会静默重复与丢行
    # 2026-07 逐表实测订正 (探针见下方「实测脚注」): 注入列**整列为空**时, 服务端当
    # 空操作处理 —— 排序参数发了等于没发, page=N 偏移翻页遂退化成无序遍历。ps1 与
    # uss_dr1 两张表已实测踩中, 各退到一张实测有值的坐标列。其余十张的注入列实测
    # 有值, 保持不动 (实测见函数 docstring 的「实测脚注」段)。
    "ps1": "ps1_ra",                    # 实测 174 行全空 -> 退到坐标列; 改后实测零逆序
    "uss_dr1": "ra_u",  # 实测 200 行全空 -> 退到波段坐标列; **裸名**。该表响应列是 ra_u/g/i/z…
                       # (无星表前缀), 而 CATALOG_COLUMNS 登记的是 uss_dr1_ra_u —— 两套命名
                       # 本就不一致, 这正是本表「方向陷阱」的成因。实测带不带前缀服务端都收。
    "stripe82": "stripe82_calibstars_id",
    "gaia_dr3_18": "gaia_dr3_18_source_id",   # 实测 200/200 有值
    "gaia_dr3": "gaia_dr3_18_source_id",      # 旧拼写别名, 随主表
    "smss_dr4": "smss_dr4_ra",
    "landolt": "landolt_source_id",
    "splus_dr4": "splus_dr4_id",              # 实测 200/200 有值
    "scr_galah": "scr_galah_source_id",
    "scr_lamost": "scr_lamost_source_id",
    "xpsp": "gaiaxp_photinfo_replenish_source_id",   # 实测 200/200 有值 (主键在共享表)
    "dr3xpcorr": "gaiaxp_photinfo_replenish_source_id",  # 同上, 共享表前缀
    "jplus_dr3": "jplus_dr3_ra",
}


def pagination_sort_key(catalog: str) -> Optional[str]:
    """星表 id 或路径 -> 分页确定性排序列 (响应列名)。

    **实测脚注 (2026-07, 逐表打真站点核对)**: 注入列**整列为空**时, 服务端当空操作 ——
    排序参数发了等于没发, page=N 偏移翻页于是退化成无序遍历 (实测 ps1/180/30/60″:
    注入 ps1_source_id 时 174 行有 84 处逆序; 换 ps1_ra 后**零逆序**、严格单调)。
    两张表已因此退到实测有值的坐标列: ``ps1 -> ps1_ra`` 与 ``uss_dr1 -> ra_u``
    (uss_dr1 坐标按波段分布, 响应列是裸名; 带不带 ``uss_dr1_`` 前缀实测都生效)。
    其余十张的注入列实测有值 (gaia_dr3_18 / xpsp / splus_dr4 / dr3xpcorr 各 200/200),
    保持不动; 探不到源的六张 (stripe82 / smss_dr4 / scr_galah / scr_lamost / landolt /
    jplus_dr3 在所选天区返 0 行) 无法证伪, 沿用原登记 —— 「没测到」不等于「错」。

    Args:
        catalog: 星表 id (``ps1``)、旧拼写别名或路径 (``ps1/q``); 空串按
            "无星表上下文"处理。

    Returns:
        该星表的默认排序列; 星表未登记或入参无法解析时返回 ``None``
        (调用方据此决定是否注入 sort)。
    """
    if not catalog:  # 空星表上下文按无序处理, 不替它猜一个默认列
        return None
    try:
        # SIM108: 三元替 if-else — 路径形态走 catalog_from_path (会抛
        # ValueError), 其余按别名表归一
        resolved = (catalog_from_path(catalog) if "/" in catalog  # 路径形态先剥 /q, 别名形态查别名表
                    else CATALOG_ALIASES.get(catalog, catalog))                                  # 别名形态查表归一: 查不到就按原名继续, 不猜
    except ValueError:
        return None
    return PAGINATION_SORT_COLUMNS.get(resolved)


def build_page_url(
    base_url: str,                                                                             # 站点根: 去尾斜杠由本函数负责, 调用方可带可不带
    sqlid: str,                                                                                 # 会话号: 调用方已过白名单归一, 本函数不再复校
    page: int,                                                                                # 页码从 1 起: 与服务端页序一致, 少一即重取一页
    page_size: int = 1000,                                                                     # 单页行数: 太大则单次回包难中断, 太小则往返过多
    catalog: str = "",                                                                       # 星表上下文: 仅用于解析默认排序列, 空串则不注入排序
    sort: Optional[str] = None,                                                         # 显式排序列: 空串是明确不注入的逃逸口, 与 None 语义不同
    order: str = "asc",
) -> str:
    """构造阶段 2 分页 GET 的完整 URL (两个客户端共用的单一事实源)。

    默认按星表注入排序列 (P0-1): 服务端无 ORDER BY 时行序不保证稳定,
    ``page=N`` 偏移翻页会静默重复/丢行。调用方显式传 ``sort`` 时尊重调用方
    的值; 传空串表示明确要求不注入 (逃逸口, 仅测试/调试用)。

    ..Warning::
       注入排序列是**尽力而为, 不是定序保证** (H3-03): 服务端只按它认得的列
       排序, 而登记的排序列可能整列为空 —— 整列为空时该次请求等于**没带排序**,
       ``page=N`` 偏移翻页会静默重复与丢行。ps1 与 uss_dr1 两张表实测踩中过,
       已退到实测有值的坐标列 (见 :func:`pagination_sort_key` 的实测脚注);
       但是否为空**仍可能随天区与记录类型变化** (ps1 混对象记录/点源记录)。
       本轮未见丢行/重行, 那是观测不是契约; 详见模块头注释与
       references/site-endpoints-and-interactions.md 同名两行。

    Args:
        base_url: BEST 基地址 (``https://nadc.china-vo.org/data/best``)。
        sqlid: 查询会话号 (``s3839`` 形态, 调用方已过 normalize_sqlid)。
        page: 页码 (1 起)。
        page_size: 单页行数 (``rows`` 参数)。
        catalog: 星表 id 或路径; 仅用于解析默认排序列。
        sort: 显式排序列; ``None`` 时按星表注入默认列。
        order: ``asc`` (默认) 或 ``desc``; 仅注入 sort 时携带。

    Returns:
        完整分页 URL (必含 ``output.fmt=csv``; 注入排序时必含 ``sort``+``order``)。
    """
    params: dict[str, Any] = {  # 三键是协议最小集, 少一个服务端就按默认值处理
        "output.fmt": "csv",
        "rows": page_size,
        "page": page,
    }
    # sort 为 None 才走默认注入; 空串是显式逃逸口 (不注入)
    effective_sort = sort if sort is not None else pagination_sort_key(catalog)  # None 才走默认注入, 空串是显式逃逸口
    if effective_sort:                                                           # 逃逸口因此不注入 order, 免得半截排序参数
        params["sort"] = effective_sort                                          # 排序列取响应列名, 与表头一致才排得动
        params["order"] = order                                                  # 方向只在有 sort 时携带, 单独发会被站点忽略
    query = urlencode(params, doseq=True)                                        # doseq 必需: 多值键不给它会被编码成一个长串
    return f"{base_url.rstrip('/')}/{SQLID_PATH.format(sqlid=sqlid)}?{query}"    # 路径模板只在这一处成型, 客户端不自己拼

# 报文解析正则: sqlid 形态 (phase-1 HTML 提取 / URL 占位校验) 与列名白名单
# (裸列名与 ``table.column`` 限定形式)。消费方: parse_sqlid / normalize_sqlid /
# qualify_column; 严格白名单保证调用方给的列名无法把 ``.`` 或控制字符注入表单键。
_SQLID_RE = re.compile(r"sqlid/(s?\d+)")  # 只认 s 加数字: 免得把任意路径片段当成会话号
_SAFE_SQLID_RE = re.compile(r"s?\d+\Z")                                                             # 全串匹配带尾锚: 防路径穿越与前缀注入
_VALID_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")                                        # 裸列名白名单: 杜绝点号与控制字符混进表单键
_QUALIFIED_COLUMN_RE = re.compile(                                                                 # 限定列名白名单: 恰好一段点号, 多段即拒
    r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$"
)
# 列名形态 (P2-2): 以字母/下划线开头的标识符状串 (容许空格外的小数点/连字符,
# 覆盖 ``inputobjs_dist_arcsec`` / ``obj name`` 一类真实列名)。
_COLUMN_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ .\-]*$")                                    # 容忍点号与连字符: 真实响应列名里确有这类字符
# 数据值形态 (P2-2): 纯数值 (含科学计数 ``1.2e-05``) 与 null 类哨兵 —— 这些
# 即使含 ASCII 字母 (``e``/``null``) 也不是列名, 不得把首行数据误判成表头。
_VALUE_LIKE_RE = re.compile(                                                                 # 纯数值与空值哨兵不算列名: 否则首行数据会被当表头吞掉
    r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$|^(?:null|nan|none)$", re.IGNORECASE
)

logger = logging.getLogger(__name__)                                                # 模块级 logger: 列错位告警只从这里出, handler 交调用方


def normalize_sqlid(sqlid: str) -> str:
    """在把 sqlid 拼进 URL 之前校验它。

    Args:
        sqlid: 形如 ``s3839`` 或 ``3839`` 的查询会话号。

    Returns:
        去首尾空白后的原值 (不强制加 ``s`` 前缀, 保持调用方拼的 URL 不变)。

    Raises:
        ValueError: 值不符合 sqlid 白名单形态 (防止路径穿越/注入)。
    """
    value = str(sqlid).strip()                                                                  # 先去空白: 会话号常从命令行与文件来, 常带换行
    if not _SAFE_SQLID_RE.fullmatch(value):                                                         # 全串匹配而非包含: 白名单只认纯形态
        raise ValueError(f"Invalid BEST sqlid: {sqlid!r}")
    return value


def count_sqlid(sqlid: str) -> str:
    """返回 BEST ``getcount`` 端点要求的数字 id。

    Args:
        sqlid: sqlid (``s`` 前缀可选)。

    Returns:
        剥掉 ``s`` 前缀的数字字符串 (``s3839`` -> ``3839``); 非法 sqlid 由
        :func:`normalize_sqlid` 抛 ``ValueError``。
    """
    return normalize_sqlid(sqlid).removeprefix("s")  # 先过白名单再剥前缀: 非法值因此仍抛而非被削成怪串


def parse_sqlid(html: str) -> str | None:
    """从 phase-1 响应 HTML 提取 sqlid (s?\\d+); 缺失返回 None。"""
    match = _SQLID_RE.search(html)                             # search 而非 match: sqlid 出现在结果页中段
    return normalize_sqlid(match.group(1)) if match else None  # None 与空串分得开: 无 sqlid 是失败信号不是空会话


def catalog_from_path(catalog_path: str) -> str:
    """从请求路径 (如 ps1/q) 解析星表 id; 未知路径抛 ValueError。"""
    path = catalog_path.strip("/").removesuffix("/q")  # 剥首尾斜杠与 /q: 调用方给路径或裸 id 两种形态
    candidate = path.rsplit("/", 1)[-1]                # 取末段: 前面可能是 calib/std 这类导航前缀
    if candidate not in CATALOG_PATHS:                 # 查表即验存活: 导航组路径在这里被挡下
        raise ValueError(f"Unknown BEST catalog path: {catalog_path!r}")
    return candidate  # 归一后的裸 id 供下游查表与拼排序列


def _catalog_table_columns(catalog: str) -> dict[str, set[str]]:
    """星表 -> {表单表: 该表已知列集合} (由 :data:`CATALOG_COLUMNS` 反推)。

    响应列名以表名为前缀 (``ps1_ra`` -> 表 ``ps1`` 的 ``ra``;
    ``gaiaxp_photinfo_replenish_g_mag`` -> 表 ``gaiaxp_photinfo_replenish``
    的 ``g_mag``), 按 :func:`catalog_tables` 的长表优先顺序剥离, 于是
    ``gaia_dr3_18_source_id`` 落在 ``gaia_dr3_18`` 而不是 ``gaia_dr3``。

    Args:
        catalog: 星表 id 或旧拼写别名。

    Returns:
        每张表单表到其已知列集合的映射; 未登记响应列的星表给空集合。
    """
    resolved = CATALOG_ALIASES.get(catalog, catalog)                                                # 旧拼写先归一: 多表结构查表要用新 id
    tables = catalog_tables(catalog)                                                                # 表名按长表优先: 决定列名前缀的归属顺序
    result: dict[str, set[str]] = {table: set() for table in tables}                                # 每张表单表一个列集合: 未命中的表留空集
    for column in CATALOG_COLUMNS.get(resolved, []):  # 登记的响应列是列名唯一来源, 站点新增列需同步此表
        for table in tables:                          # 按长表优先序试, 首个前缀命中即止
            prefix = f"{table}_"
            if column.startswith(prefix):                                                        # 前缀命中即归属该表: 长表优先保证前缀歧义不发
                result[table].add(column[len(prefix):])                                            # 剥前缀存裸列名: 后续存在性校验按裸名比对
                break
    return result


def qualify_column(catalog: str, column: str) -> str:
    """把 Python/结果侧列名 (如 ``ps1_ra``) 翻译成 Django 表单键 ``ps1.ra``。

    列名先过严格白名单校验才进入表单键, 因此调用方提供的列名无法把 ``.`` 或
    控制字符注入表单键。已带 ``表.列`` 形式的名称仅当其表确属该星表发布列的表、
    且列真实存在于该表时才被接受 —— 于是 ``correctedxpspecv1.flux`` 对
    ``dr3xpcorr`` 成立, 而 ``evil.col`` 对任何星表都不成立。裸列名同样校验
    存在性 (P1-3): 打错列名会落到服务端忽略的未知表单键上, 静默返回全表而非
    过滤结果, 必须显式失败。

    Args:
        catalog: 星表 id 或旧拼写别名 (旧前缀经 :data:`CATALOG_ALIASES` 归一)。
        column: 裸列名 (``rpsf``)、带前缀列名 (``ps1_rpsf``) 或已限定列名
            (``ps1.rpsf``)。

    Returns:
        ``{table}.{column}`` 形式的表单键。

    Raises:
        ValueError: 列为空、列名不在白名单内、限定表不属于该星表, 或列不在
            该星表任何已发布表的已知列集合内 (P1-2/P1-3 fail-closed)。
    """
    name = column.strip()                                                                        # 去空白再判形态: 列名常从响应表头直接复制而来
    if not name:                                                                                 # 空列名显式拒: 拼出点号开头的键会被服务端丢弃
        raise ValueError("Constraint column cannot be empty")
    tables = catalog_tables(catalog)                                                              # 表清单按长表优先: 后面两轮匹配都依赖这个序
    table_columns = _catalog_table_columns(catalog)                                                # 列集合现算: 站点新增列只需同步登记表一处
    if _QUALIFIED_COLUMN_RE.fullmatch(name):                                                        # 已限定形态单独处理: 表与列都要校验归属
        table, col = name.split(".", 1)  # 只拆一次: 列名自身可能含点, 如 obj name 类拼写
        # P1-3: 已限定形态既校验表归属也校验列存在 (只校验表归属的话,
        # ``ps1.nonexistent`` 一类幻影限定列可直入表单)。
        if table not in tables or col not in table_columns.get(table, set()):                    # 表归属与列存在性双查: 幻影限定列不得进入表单
            raise ValueError(f"Invalid column name: {column!r}")
        return name
    if not _VALID_COLUMN_RE.fullmatch(name):                                                      # 裸列名过严格白名单: 点号与控制字符在此拦掉
        raise ValueError(f"Invalid column name: {column!r}")
    for table in tables:                                                                            # 按长表优先逐表试前缀: 首个命中即止
        prefix = f"{table}_"
        if name.startswith(prefix):                                                                 # 带前缀列名走这条路: 转成表单键形式
            col = name[len(prefix):]                                                                # 剥前缀取裸列名: 存在性校验按裸名比对
            if col in table_columns.get(table, set()):                                              # 命中且列真实存在才认: 幻影列在此被拒
                return f"{table}.{col}"
            break  # 前缀命中但列不存在: 不再试其它表, 交由下方集合判定收口
    # 无表前缀匹配 (P1-2): 列必须唯一落在某张表的已知列集合里。不得无条件
    # 拼 ``{resolved}.{name}`` 兜底, 那会对 xpsp/dr3xpcorr 产出服务端不存在的
    # 错表名 (xpsp.g_mag), 波段过滤静默不生效。
    matches = [table for table in tables                                                       # 无前缀时列必须落在某张表: 多表星表的同名列最易踩
               if name in table_columns.get(table, set())]                                         # 按长表优先收集候选: 顺序决定最终选哪张表
    if matches:                                                                                     # 有候选即取第一张: 确定性优先于覆盖面
        # 多表同名列取 catalog_tables 的优先序 (长表名优先), 保证确定性。
        return f"{matches[0]}.{name}"
    raise ValueError(f"Invalid column name: {column!r}")


def _constraint_value(constraint: Any, key: str, default: Any = None) -> Any:
    """从约束项读取一个字段, 兼容 dict 与属性对象两种约束写法。

    ``constraint`` 是双重身份键: dict 形式下既接受 ``constraint`` 也接受 ``op``
    作为操作名 (历史调用方两种拼写都存在); 属性对象形式直接取属性, 键缺失时
    返回 ``default``。
    """
    if isinstance(constraint, Mapping):                                                         # 字典与属性对象两种写法都收: 历史调用方两种都有
        if key == "constraint":
            return constraint.get("constraint", constraint.get("op", default))
        return constraint.get(key, default)
    return getattr(constraint, key, default)



def quality_column(catalog: str, kind: str) -> str:
    """把质量指标解析到该星表真实存在的列上。

    Args:
        catalog: 星表 id 或旧拼写别名 (先经 :func:`resolve_catalog` 解析)。
        kind: ``snr`` / ``fwhm`` / ``class_star`` 之一。

    Returns:
        该指标的 ``{table}.{column}`` 形式表单键。

    Raises:
        ValueError: 该星表没有发布这个质量列 —— fail-closed, 而不是去约束一个
            服务端永远不会返回的列名。
    """
    resolved = resolve_catalog(catalog)                                                           # 先归一再查质量列: 旧别名在质量表里没有条目
    key = str(kind or "").strip().lower()
    columns = QUALITY_COLUMNS.get(resolved, {})                                                     # 取该星表发布的指标集合: 缺表即空集合
    column = columns.get(key)                                                                       # 按指标名取列: 键是去空白并小写后的形态
    if column is None:                                                                              # 缺列即抛: 不去约束服务端永不返回的列名
        available = ", ".join(sorted(columns)) or "none"
        raise ValueError(
            f"BEST catalogue {resolved!r} publishes no {key!r} quality column "
            f"(available: {available})"
        )
    return qualify_column(resolved, column)


# 这四列**不是 proximity 独有** (2026-10-05 全 12 表实跑订正, SSOT §11.4):
# ``pos.type=cone`` 的**锥搜**回包同样带这 4 列, 且固定排在表头最前 ——
# 17 份原始 CSV 里 16 份带, 唯一例外是 ``uss_dr1`` (0 个)。故两条纪律:
# ① 拿回包表头宽度与 ``CATALOG_COLUMNS`` 长度对账必须**先摘掉这 4 列**,
#    否则每张表假报 +4 漂移; ② 连"这 4 列总在"都**不能当不变量** ——
#    判列数要按"回包表头里有没有"来判, 不按"星表是谁"来判。本仓的剔除逻辑按
#    列名前缀判, 形态无关, 现状正确。
# 提交了 ``showcol`` 时这些列带 ``inputobjs_`` 前缀 (线上实测 sqlid s3929/s3938);
# 未提交 ``showcol`` 的提交只返回这四列元数据且**不带**前缀, 一个星表列都不给 (V-1)。
# 把一行重新接回其输入坐标时两种拼写都接受。定义收在本模块, 使行模型
# (BestSource.from_row) 与交叉匹配器共享同一个"这列是匹配元数据而非测光"的判定。
PROXIMITY_META_COLUMNS: tuple[str, ...] = (                                                       # 带前缀拼写: 提交了列投影时元数据列才带前缀
    "inputobjs_input_line", "inputobjs_dist_arcsec",
    "inputobjs_input_ra", "inputobjs_input_dec",
)
# 无 showcol 提交时的无前缀拼写 (同一批元数据的另一种列名), 消费方同上。
PROXIMITY_META_COLUMNS_BARE: tuple[str, ...] = (                                                   # 无前缀拼写: 未提交投影时服务端只回这四列
    "input_line", "dist_arcsec", "input_ra", "input_dec",
)


def proximity_radec_text(
    ra_list: Iterable[float], dec_list: Iterable[float], radius_arcsec: float                    # 三入参同取: 半径是每个输入位置共用的匹配半径
) -> str:
    """为 proximity 批量匹配构造 ``ra,dec,radius`` 多行 textarea 文本。

    Args:
        ra_list: 输入 RA 序列 (度)。
        dec_list: 输入 Dec 序列 (度), 与 ``ra_list`` 逐位配对。
        radius_arcsec: 每个输入位置共用的匹配半径 (角秒)。

    Returns:
        每行 ``{ra},{dec},{radius}`` 的文本, 直接作为 ``pos.radecTextarea``
        提交 (对应 ``pos.type=proximity``)。

    Raises:
        ValueError: 两序列长度不齐 (SA-P3-5: zip 不加 strict 会静默截断, 多出的
            坐标被悄悄丢弃, 匹配结果对不齐还毫无提示)。
    """
    pairs = list(zip(ra_list, dec_list, strict=True))       # strict 必开: 长度不齐直接抛, 不静默截断丢坐标
    return "\n".join(                                       # 换行分隔: 服务端把 textarea 按行当成独立输入位置
        f"{float(ra)},{float(dec)},{float(radius_arcsec)}"  # 逐行三段式: 半径内联在每行, 服务端不认缺省
        for ra, dec in pairs                                                                     # 逐行拼三段式: 服务端按行把文本当独立输入位置
    )


def magnitude_column(catalog: str, band: str) -> str:
    """把波段标签解析到该星表真实存在的星等列上。

    上面的逐星表映射表是波段命名的唯一权威: ``ps1`` 发布 ``gpsf``/``rpsf``,
    ``stripe82`` 发布 ``u_h22``, ``landolt`` 发布 ``vmag``, ``splus_dr4`` 发布
    ``u_pstotal``, ``gaia_dr3_18`` 发布 ``phot_g_mean_mag``。按
    ``f"{band}psf"`` / ``f"{band}mag"`` 一类启发式拼名会拼出没有任何星表发布的
    列名,
    于是波段过滤静默约束在不存在的列上 (返回 0 行或服务端错误), 而不是过滤到
    调用方真正想要的波段。

    Args:
        catalog: 星表 id 或旧拼写别名 (先经 :func:`resolve_catalog` 解析)。
        band: :data:`CATALOG_MAG_COLUMNS` 发布的波段标签 (大小写不敏感)。

    Returns:
        该波段的 ``{table}.{column}`` 形式表单键。

    Raises:
        ValueError: 该星表没有发布这个波段, 或波段标签为空。
    """
    resolved = resolve_catalog(catalog)                                                           # 先归一再查波段表: 旧别名在波段表里没有条目
    key = str(band or "").strip().lower()
    if not key:                                                                                   # 空波段标签显式拒: 静默放行会退化成不限波段
        raise ValueError("a band label is required")
    columns = CATALOG_MAG_COLUMNS.get(resolved, {})                                                 # 取该星表真实发布的波段集合
    for column, label in columns.items():                                                         # 逐项比对标签: 标签相等才认, 不做前缀猜测
        if label == key:                                                                        # 标签精确匹配: 启发式拼列名是波段过滤失效的根因
            return qualify_column(resolved, column)  # 过白名单再返回: 映射表错字不许静默进表单
    available = ", ".join(sorted(set(columns.values()))) or "none"
    raise ValueError(
        f"BEST catalogue {resolved!r} publishes no {key!r}-band magnitude "
        f"(available bands: {available})"
    )


# ColumnConstraint 上协议层**从不读取**的字段 (A2-04 实测: 传了也只发
# ``{col}.textarea``/``.constraint``, 其余静默丢弃)。``show`` 不在此列, 因为它是
# 布尔且缺省 True, 判定语义不同 — 见 build_query_form 约束循环内的单独一支。
# 处置是**显式拒绝**而不是实现: 这两项各自需要站点侧的能力(值文件上传/按列排序),
# 本仓既无实测回包支撑, 也没有协议依据, 猜一个实现出来同样是静默给错答案。
DEAD_CONSTRAINT_FIELDS = ("file", "sort")

# BEST 表单 ``{table}.{col}.operation`` 的**可取操作符**白名单 (fail-closed, P1-04)。
# 2026-10-05 实站逐项取证 (ps1 @180,30 300", 同锥无约束 total=5109, 每项一个独立
# sqlid 会话; temp/h3/probe_operation2.json + confirm_operation.py): 未知操作符
# **不会被站点忽略**, 而是被接受后静默返回**空表** —— 拼错的 ``greatr`` (max=16) 与
# 旧登记里当方言的 ``grater`` (min=15) 都 total=0 且回包是 426 B 的表头 CSV, 而
# ``greaterequal`` (min=15) 同锥出 1559 行。**未列在此表的操作符一律显式 ValueError**,
# 不原样下发: 静默产出空表会被读成"这片天区没有源" (铁律 5)。
# 权威来源: references/site-endpoints-and-interactions.md §2.3 (站点表单实测取值表);
# 逐项行数证据与复现命令见 temp/FIX-H3-builder-sentinels.md。
# ``grater`` **故意不在**白名单里: 旧文档称 strict-greater 的站点拼写是它, 实测它恒返
# 0 行, 与 ``greaterequal`` 只差这一个字母 —— 因此本仓也不再把 ``greater`` 映射成它
# (那会把一条可读的操作变成静默空结果), ``greater`` 按未知操作拒。
ALLOWED_OPERATIONS = frozenset({"equal", "notequal", "less", "lessequal",
                                "greaterequal", "between", "contains", "in"})


def build_query_form(
    catalog: str,                                                                              # 目标星表: 必填且须可归一, 后续所有键都按它展开
    constraints: Iterable[Any] = (),                                                            # 约束项可迭代: 支持生成器, 逐项翻译成表单四键
    *,
    output_format: str = PHASE1_HANDOFF_FORMAT,                                                # 缺省交接格式: 阶段 1 换别的格式就拿不回会话号
    ra: float | None = None,                                                                        # 锥搜赤经可空: 三参数须同时给齐
    dec: float | None = None,                                                                       # 锥搜赤纬可空: 与赤经同进同出
    radius_arcsec: float | None = None,                                                         # 角秒半径可空: 少给一个就退化成无空间约束的查询
    box: tuple[float, float, float, float] | None = None,                                        # 矩形四元组可空: 与锥搜互斥, 谁后设谁清对方
    radec_text: str | None = None,                                                         # 已序列化的坐标块: proximity 路径用它取代三元组
    default_radius_arcsec: float | None = None,                                             # 逐行默认半径: 给才下发, 服务端自带值与本地口径不一致
    nearest_only: bool = False,                                                                    # 最近邻开关: 由服务端过滤, 不在本地裁剪
    sort: str | None = None,                                                                     # 排序列可空: 空串是明确不排序, 不回落默认列
    order: str = "asc",
    show_columns: Iterable[str] | None = None,                                                      # 列投影可空: 缺省请求该星表全部登记列
) -> dict[str, Any]:
    """拼出 BEST 星表页真正接受的 Django 表单 (phase-1 提交体)。

    ``output_format`` 默认 ``html``, 因为只有该提交会回交一个 ``sqlid``;
    ``csv``/``json``/``votable``/``txt`` 会让服务端把行内联流式返回, 两阶段分页
    协议就丢了。空间选择互斥: ``ra``/``dec``/``radius_arcsec`` 锥形、
    ``box`` 矩形, 或 ``radec_text`` 坐标表 (服务端逐行匹配,
    ``pos.type=proximity``, 响应因此多出 ``inputobjs_*`` 列)。

    ``nearest_only`` 要求服务端对每个输入位置只保留最近匹配
    (``cone_nearestonly`` / ``proximity_nearestonly``); ``sort`` 是星表列
    (与约束项过同一套白名单) 且 ``order`` 取值 ``{"asc", "desc"}``。

    Args:
        catalog: 星表 id 或旧拼写别名。
        constraints: 约束项 (dict 或属性对象), 字段见
            :func:`_constraint_value` 的兼容说明。
        output_format: 导出格式, 默认 ``html`` (见 :data:`PHASE1_HANDOFF_FORMAT`)。
        ra/dec/radius_arcsec: 锥形检索中心与半径 (角秒), 三者必须同时给齐。
        box: 矩形边界 ``(ra_min, ra_max, dec_min, dec_max)``。
        radec_text: proximity 多行坐标表文本 (见 :func:`proximity_radec_text`)。
        default_radius_arcsec: proximity 模式的服务端默认匹配半径 (角秒)。
        nearest_only: 是否只保留每个输入位置的最近匹配。
        sort: 排序列名; ``None`` 表示不排序。
        order: 排序方向, 大小写不敏感。
        show_columns: 显式请求的列; ``None`` 时请求该星表全部已登记列。

    Returns:
        可直接作为 POST 表单提交的 ``{键: 值}`` dict。

    Raises:
        ValueError: 星表不可查询、空间参数混用或越界、半径非正/非有限/超 5° (交由
            :func:`src.scripts.guards.validate_search_radius` 单点判定, 协议层不另立
            判据)、排序方向非法、列约束的
            ``operation`` 不在 :data:`ALLOWED_OPERATIONS` 内 (未知操作符会让站点
            静默返回空表, 因此显式拒)、约束项缺 min/max/value, 列名不在白名单内,
            或约束项带了协议层不读取的 ``file``/``sort``/``show=False`` (显式拒绝,
            不静默丢弃)。
    """
    resolved = resolve_catalog(catalog)  # 组名与旧拼写在此一次性收敛
    # 双保险: resolve_catalog 已保证 id 合法, 这里再确认它确实可查询 (分组名与
    # 未知名都在上面抛错), 之后才允许进入表单拼装。
    if resolved not in CATALOG_PATHS:  # 双保险: 确认归一结果确实可查询才继续拼表单
        raise ValueError(f"Unknown BEST catalog: {catalog!r}")

    # SA-P2-5: output_format 白名单校验 (模块注释声明的责任在此兑现) —
    # phase-1 提交只接受 html (回交 sqlid) 或四种导出格式; fits 不在任何
    # BEST 导出菜单里, 非法值显式抛错而不是静默拼进表单键
    fmt_key = str(output_format or "").strip().lower()                     # 归一再比白名单: 大小写差异不该让查询失败
    if fmt_key not in (PHASE1_HANDOFF_FORMAT, *SUPPORTED_OUTPUT_FORMATS):  # html 与四种导出格式取并集: 前者回交 sqlid, 后者落盘转换
        raise ValueError(
            f"unsupported output_format {output_format!r} "
            f"(allowed: {PHASE1_HANDOFF_FORMAT}, "
            f"{', '.join(SUPPORTED_OUTPUT_FORMATS)})"
        )

    form: dict[str, Any] = {"output.fmt": fmt_key}
    spatial = (ra, dec, radius_arcsec)  # 打包成三元组: 互斥判定要同时看三项
    # 三种空间选择互斥: 锥形 / 矩形 / proximity 坐标表。混用时服务端只会认其中
    # 一种而静默忽略另一个, 因此显式拒绝而不是替调用方挑一个。
    if box is not None and any(value is not None for value in spatial):  # 混用显式拒: 服务端只认一种, 静默忽略无法察觉
        raise ValueError("Choose either a cone or a box region, not both")
    if radec_text is not None and (box is not None or any(v is not None for v in spatial)):  # 坐标表是第三种模式, 与前两者同样互斥
        raise ValueError("radec_text replaces the cone and box constraints")
    if any(value is not None for value in spatial):  # 任一给齐即走锥形分支, 三项须同进同出
        # 锥形检索三参数必须同时给齐, 并逐个校验物理范围 —— 越界坐标发出去只会
        # 换来一个难以定位的服务端错误。
        if ra is None or dec is None or radius_arcsec is None:  # 只给一部分是最常见的调用错误, 必在此拦
            raise ValueError("ra, dec and radius_arcsec must be provided together")
        if not 0.0 <= float(ra) < 360.0:  # 半开区间: 360 与 0 是同一天区, 取一舍一
            raise ValueError("ra must be in [0, 360) degrees")
        if not -90.0 <= float(dec) <= 90.0:  # 闭区间: 两个天极都是合法坐标
            raise ValueError("dec must be in [-90, 90] degrees")
        validate_search_radius(float(radius_arcsec))  # 纵深防御: 复用全仓半径守卫单点 (非正/NaN/Inf/超 5° 都在那里), 本层不写第二份判据
        form.update({                                                                           # 位置键一次写全: 少一个服务端就按无空间约束处理
            "pos_group": "ra,dec",
            "pos.type": "cone",
            "pos.racenter": str(ra),
            "pos.deccenter": str(dec),
            "pos.radius": str(radius_arcsec),
        })
        if nearest_only:                     # 每输入位置只留最近邻, 由服务端过滤而非本地
            form["cone_nearestonly"] = "on"  # 值为 on: 服务端只判键是否存在, 读的是键不是值
    elif box is not None:
        ra_min, ra_max, dec_min, dec_max = (float(v) for v in box)  # 四元组解包: 顺序错位不报错, 因此次序必须钉住
        # 矩形边界同样做物理范围校验, 并显式拒绝 dec_min > dec_max (服务端对反序
        # 边界的行为未定义, 不能替它猜)。
        if not 0.0 <= ra_min < 360.0 or not 0.0 <= ra_max < 360.0:  # 两个 RA 边界分别校验, 不取区间包络
            raise ValueError("box RA bounds must be in [0, 360) degrees")
        if not -90.0 <= dec_min <= 90.0 or not -90.0 <= dec_max <= 90.0:  # Dec 闭区间: 天极坐标合法
            raise ValueError("box Dec bounds must be in [-90, 90] degrees")
        if dec_min > dec_max:  # 反序边界的服务端行为未定义, 不能替调用方猜
            raise ValueError("box dec_min must not exceed dec_max")
        form.update({                                                                    # 矩形四键一次写全: 边界反序的服务端行为未定义, 已在上方拒掉
            "pos_group": "ra,dec",
            "pos.type": "rect",
            "pos.ramin": str(ra_min),
            "pos.ramax": str(ra_max),
            "pos.decmin": str(dec_min),
            "pos.decmax": str(dec_max),
        })
    elif radec_text is not None:
        # proximity: 服务端按坐标表逐行匹配, 响应因此多出 inputobjs_* 元数据列
        # (见 PROXIMITY_META_COLUMNS); defaultRadius 缺省时由服务端定半径。
        form.update({                                                              # proximity 三键: 服务端按坐标表逐行匹配, 响应因此多出元数据列
            "pos_group": "ra,dec",
            "pos.type": "proximity",
            "pos.radecTextarea": radec_text,
        })
        if default_radius_arcsec is not None:        # 给才下发: 服务端自带半径会与本地口径不一致
            validate_search_radius(float(default_radius_arcsec))  # 与锥形分支同一纪律同一判据: 非正/NaN/Inf/超限一律显式拒
            form["pos.defaultRadius"] = str(default_radius_arcsec)
        if nearest_only:                          # proximity 的最近邻键与锥形不同名, 不能复用
            form["proximity_nearestonly"] = "on"  # 值同为 on: 服务端仍然只判键
    else:
        # 无空间约束: 全表扫描式提交, 只受 sort/constraint 约束。
        form["pos.type"] = "none"

    if sort is not None:              # None 才是真不排序; 空串走下方显式报错
        sort_key = str(sort).strip()  # 去空白: 排序列名常从 CSV 表头直接复制来
        if not sort_key:              # 空串非法: 静默回落 asc 会让调用方误判自己的排序生效了
            raise ValueError("sort must be a catalogue column name")
        # ``order`` 按原值校验 (空串视为非法而不是静默回退默认): ``order or "asc"``
        # 会把空值吞掉, 让调用方以为自己的排序生效了。
        order_key = str("asc" if order is None else order).strip().lower()  # None 才回默认, 空串原样送检不吞掉
        if order_key not in ("asc", "desc"):                                # 只认两种方向: 其它值的服务端行为未定义
            raise ValueError("order must be 'asc' or 'desc'")
        form["sort"] = qualify_column(resolved, sort_key)
        form["order"] = order_key

    # ``showcol`` 键是 ``{table}.{column}``; qualify_column 把裸列名 (``rpsf``)、
    # 带前缀列名 (``ps1_rpsf``) 与已限定列名 (``ps1.rpsf``) 过同一套逐星表白名单,
    # 与约束项走同一条校验路径。
    selected = list(show_columns) if show_columns is not None else CATALOG_COLUMNS[resolved]  # None 意味着请求该星表全部登记列
    form["showcol"] = [qualify_column(resolved, col) for col in selected]

    seen_columns: dict[str, str] = {}  # 已占用列 -> 该列已用的操作符 (同列多约束的判定依据, 见下)

    for item in constraints:                                                            # 逐项拼一组四键: 服务端按键名成对识别操作
        # 死参数 fail-closed (A2-04): 传了就必须报错, 不能静默丢掉后照样返回一个
        # "看着按值文件筛过/按指定列排过、其实两者都没发生"的结果集 ——
        # 静默丢弃比抛错危险得多, 因为调用方无从察觉自己拿到的是错答。
        # ``show`` 缺省 True, 故只有 False 改变语义, 与另两项的空值判据分开。
        dead = [f for f in DEAD_CONSTRAINT_FIELDS if _constraint_value(item, f) is not None]
        if dead or not _constraint_value(item, "show", True):
            names = dead or ["show=False"]                                                    # 报错要指名道姓: 只说"不支持"等于让人自己猜
            raise ValueError(f"ColumnConstraint {names} not supported for column "
                             f"{_constraint_value(item, 'name', '?')!r}: build_query_form "
                             f"never reads them")
        name = _constraint_value(item, "name", "")                                      # 列名必填: 缺名拼出的是点号开头键, 会被丢弃
        operation = str(_constraint_value(item, "constraint", "between") or "between")  # 默认 between: 历史调用方常只给 min 与 max
        if operation not in ALLOWED_OPERATIONS:  # 白名单 fail-closed (P1-04): 未知操作符站点收下后返**空表**, 调用方会读成"这片天区没源"
            raise ValueError(f"unknown column operation {operation!r} for {name!r} ('grater' is not accepted); "  # 显式抛而不原样下发: 原样下发是本仓查询构造层仅存的 fail-open
                             f"allowed: {', '.join(sorted(ALLOWED_OPERATIONS))}")  # 白名单全量列进报错: 让人当场看到该用什么, 不用去翻文档
        prefix = qualify_column(resolved, str(name))  # 约束列与排序列同一套白名单, 杜绝表单键注入
        # 同列多约束 fail-closed (P0-16): 表单键是 ``{prefix}.operation`` 这一**对**,
        # 同一个前缀写第二次就是静默覆盖。实测本仓原行为: 同一列先给
        # ``greaterequal 15.0`` 再给 ``lessequal 18.0`` 时, 只剩后者
        # (operation 键数 = 1), 于是「15 <= r <= 18 的区间」悄悄退化成
        # 「r <= 18」, 返回集里混进大量 r < 15 的源, 而调用方以为自己限了下界。
        #
        # **不自动合并成 between**: 合并不总是合法的 —— 两次 `greaterequal`、
        # `contains` 与 `lessequal` 的组合都无从合并, 猜一个语义出来仍是静默
        # 给错答案。与上一支的未知操作符同一处置: 显式抛, 并把出路写进报错。
        if prefix in seen_columns:
            raise ValueError(  # 报错带列名与两个操作符: 只说"重复"等于让人自己回溯
                f"duplicate constraint on column {name!r}: "  # 列名用调用方的原名, 不给白名单拼过的键
                f"{seen_columns[prefix]!r} and {operation!r} both target "  # 指出冲突双方, 让人知道该合并哪两个
                f"{prefix!r}; the form carries one operation per column, so the first "
                f"would be silently dropped. Merge them into a single 'between' constraint."
            )
        seen_columns[prefix] = operation  # 登记本列已用操作: 第二次命中即上面的重复分支
        form[f"{prefix}.operation"] = operation

        minimum = _constraint_value(item, "min")  # 三值分别取值: 区间型用两端, 单值型用一端
        maximum = _constraint_value(item, "max")  # 上限可缺, 但 between 缺它必抛
        value = _constraint_value(item, "value")  # 显式 value 优先于 min/max 回落
        if operation == "between":                # 区间型两端都必填, 少一个语义就变了
            if minimum is None or maximum is None:                                     # 区间型两端都必填: 少一端语义就变了, 静默补默认值等于换了个查询
                raise ValueError(f"between constraint for {name!r} needs min and max")
            form[f"{prefix}.min"] = str(minimum)
            form[f"{prefix}.max"] = str(maximum)
        else:
            # 单值操作: ``greaterequal`` 缺省取 min, 其余取 max; ``contains``/``in``
            # 走 textarea 字段而不是 constraint 字段 (表单约定)。
            if value is None:                                                            # 显式 value 缺省才回落: 0 是合法取值, 不能用真值判空
                value = minimum if operation == "greaterequal" else maximum  # 方向型操作取下界, 其余取上界, 沿用站点表单约定
            if value is None:                                                            # 两端都没有即非法: 拼空约束会被服务端静默忽略
                raise ValueError(f"{operation} constraint for {name!r} needs a value")
            suffix = "textarea" if operation in {"contains", "in"} else "constraint"  # contains 与 in 走 textarea 字段, 站点单独实现了这两个
            form[f"{prefix}.{suffix}"] = str(value)
    return form


def _sniff_delimiter(text: str) -> str:
    """判别分隔符文本用的是逗号还是制表符 (只看首个非空行)。

    Args:
        text: 已去 BOM 的响应体。

    Returns:
        ``","`` 或 ``"\\t"``; 无法判别时按站点默认口径给逗号。

    Note:
        **只判别表头行**: 数据行里的逗号可能出现在字符串值内 (如
        ``obj_name`` 列含 "M31, NGC 532"), 据数据行判别会把一列错拆成两列,
        且这种错误不抛异常 — 整表列序静默偏移。
        表头行是列名, 不会含分隔符本身, 是唯一安全的判别位置。
        动机: 站点的 ``output.fmt=txt`` 回的是 TSV, 人工从站点另存的也是 TSV,
        而本 skill 线上只请求 csv — 两者都要能读。
    """
    for line in text.splitlines():                                                          # 只看首个非空行判别: 数据行里的逗号可能出现在字符串值内
        stripped = line.strip()                                                                     # 去空白再判: 表头行末尾常有换行残留
        if not stripped:                                                                    # 跳过空行: 空行不参与判别, 否则会把空行当表头判成逗号
            continue
        if "\t" in stripped and "," not in stripped:
            return "\t"
        return ","
    return ","


def parse_csv_rows(text: str, catalog: str = "", stats: Optional[dict] = None) -> list[dict[str, str]]:
    """解析 BEST CSV/TSV, 含旧式 sqlid 表头不完整的响应。

    分隔符自动判别: 逗号 (``output.fmt=csv``) 与制表符 (站点 ``txt`` 导出 /
    人工从站点另存的 TSV) 都能读 —— 判别只看**表头行** (数据行里逗号可能
    出现在字符串值内, 据数据行判别会把一列错拆成两列且不抛异常)。

    Args:
        text: CSV/TSV 端点响应体 (可能带 UTF-8 BOM 与首尾空白)。
        catalog: 星表 id; 提供时用于按 :data:`CATALOG_COLUMNS` 修复短表头,
            空串表示无星表上下文 (退回纯形态推断)。
        stats: 可选出参 dict; 解析完写入 ``truncated_rows`` (末行被传输
            拦腰截断而丢弃的条数) 与 ``overflow_rows`` (宽于表头的行数)。
            丢弃事实只进 ``logger.warning`` 时对调用方不可见 —— 丢行与
            "服务端就只有这些行"在返回值上同形, 调用方无从对账 (A2-01)。
            空响应早退时无键可写, 调用方按缺键取 0 即可 (本就无数据行)。

    Returns:
        行 dict 列表, 键为列名、值为去空白后的字符串; 空响应返回 ``[]``。
    """
    raw = text.lstrip("\ufeff").strip()
    if not raw:                                                                                 # 空响应早退: 去 BOM 与去空白后为空即无数据
        return []
    delimiter = _sniff_delimiter(raw)                                                    # 分隔符只由表头行决定: 数据行不可作判据, 会把一列错拆成两列
    records = list(csv.reader(io.StringIO(raw), delimiter=delimiter))                     # 用标准 csv 读: 引号与转义规则必须与站点另存的形态一致
    if not records:                                                                                 # 空表早退: 没有首行就没法判表头
        return []

    first = records[0]                                                                             # 首行单独取出: 后面两条路径都要拿它判形态
    # 表头动态判定 (P2-2 修正): 列名形态 = 标识符状且非纯数值/null 哨兵。
    # 设计理由: 同一 /sqlid CSV 全包只允许一套表头假设 — 多种互斥假设并存
    # (位置分割 / DictReader 强制表头 / 本函数动态判定) 时, M8 盲删首行突变
    # 会存活; 现全包单一假设 (Q-05); 表头行绝不进入数据 (Q-02 幻影源根因)。
    # 旧判据"任一单元格含 ASCII 字母"会把 ``1.2e-05`` (含 e) 与 ``null``
    # 也当表头证据, 无表头响应的首行数据被整行吞掉且列名变成数据值。
    has_header = any(                                                                               # 任一单元格形似列名即认定有表头
        _COLUMN_NAME_RE.fullmatch(value or "")                                                     # 列名形态判定: 标识符状且容许点号与连字符
        and not _VALUE_LIKE_RE.fullmatch(value or "")                                        # 排除纯数值与空值哨兵: 否则首行数据会被当表头整行吞掉
        for value in first                                                                         # 遍历首行全部单元格: 不用单个单元格下结论
    )
    data_rows = records[1:] if has_header else records                                              # 表头行绝不进入数据: 幻影源就是这么来的
    # 行宽取所有数据行的最大值 (短行稍后补空串): 旧 sqlid 的投影列数不齐时不至于
    # 把数据错位到错误列。注意 width 只用于旧式短表头修复与无表头命名两条路径,
    # 不再是"表头是否可信"的判据 (P1-1)。
    width = max((len(row) for row in data_rows), default=len(first))                           # 行宽取最大值: 短行稍后补空串, 不因此把数据错位
    known = CATALOG_COLUMNS.get(catalog) if catalog else None                                     # 登记列作参照: 空星表上下文时退回纯形态推断

    if has_header and (known is None or len(first) >= len(known)):                      # 表头宽是权威判据: 宽于登记列就原样采用, 不拿数据行宽度替换它
        # P1-1: 表头宽是权威判据 —— 不许据"数据行最大宽"判定, 任一行数据
        # 错位 (值内含未转义逗号 / 服务端偶发多一列) 都会让 width +1, 把
        # 真实表头整行丢弃并换成 CATALOG_COLUMNS 补齐列, 坐标/星等全部串列
        # 且不抛异常。所以表头原样采用, 宽于表头的数据行多余值落 overflow_i
        # 键 (列不错位, 多余值可见可查)。
        header = list(first)                                                                     # 拷贝而非引用: 下面按宽度切片时要改写这份表头
    elif known is not None and width >= len(known):
        # 旧式短表头: 首行只含元数据列 (匹配列/行号), 星表列按 CATALOG_COLUMNS
        # 权威表补齐; 未命名的元数据列按 metadata_{i+1} 顺序编号。
        metadata_width = width - len(known)                                                       # 多出来的宽度即元数据列: 旧式短表头靠它识别
        visible = first[:metadata_width] if has_header else []                                      # 只取数据部分: 元数据列不参与列名推导
        visible.extend(f"metadata_{i + 1}" for i in range(len(visible), metadata_width))
        header = visible + known                                                                    # 短表头用登记列补齐: 比留一排空列名可用
    elif has_header:
        # 表头比数据短 (尾部列缺失): 补 col{i+1} 占位名, 不丢数据。
        header = first + [f"col{i + 1}" for i in range(len(first), width)]
    else:
        # 很旧/mock 的 sqlid 可能连表头都没有, 只给一个短投影。已知星表时优先用
        # 它的真实前列命名, 于是截断的 ``std`` 行被标成 ``std_id, std_name``
        # 而不是被错当成 ``ra, dec``。
        if known is not None:                                                                   # 有登记列才走修复路径: 无星表上下文时按形态推
            header = known[:width] + [f"col{i + 1}" for i in range(len(known), width)]
        elif catalog and width >= 2:
            # 未登记星表但有星表上下文: 至少保证前两列是 ra/dec 语义。
            header = [f"{catalog}_ra", f"{catalog}_dec"]
            header.extend(f"col{i + 1}" for i in range(2, width))
        else:
            # 无任何上下文: 纯位置命名, 不做天文语义猜测。
            header = [f"col{i + 1}" for i in range(width)]

    rows: list[dict[str, str]] = []                                                                 # 结果容器: 只收非全空行
    overflow_rows = 0                                                                               # 多余值行计数: 报错时要指明有几行出过
    truncated_rows = 0                                                                          # 短行计数: 与多余值分开统计, 两种错位方向不同
    # 物理行 (供半行判定): BEST 的 CSV 值为数值/标识符, 不含引号内换行,
    # 按行切分与 csv.reader 的记录一一对应 (表头行按 has_header 偏移)。
    physical = raw.splitlines()                                                                     # 物理行备用: 需要按原文定位行号时才用
    body_offset = 1 if has_header else 0                                                           # 表头占一行: 物理行号与数据行下标差这一行
    for idx, values in enumerate(data_rows):                                                        # 逐数据行组装: 下标用于判断是不是末行
        # 半行判定 (E4 RB-29): **末行**字段数少于表头 = 传输被拦腰截断 —
        # 连接中断只可能发生在回包末尾, 行中间的短行是旧式 ragged 投影
        # (补空保留, 见下)。半行不得补空后当完整行入库: pad 成
        # "尾列缺失"的合法行的话, 网络截断被静默读成一颗数据不全的源。
        # (注: 不能只用"行尾无分隔符"判 — 截断点可能恰好落在逗号后。)
        if idx == len(data_rows) - 1 and len(values) < len(header):                        # 只有末行短才算截断: 中间行短属服务端错乱, 不能混为一谈
            truncated_rows += 1                                                                     # 记数: 半行整行丢弃, 不补空入库 (见上方半行判定)
            logger.warning(                                                                         # 短行要告警: 不告警则半行数据静默进结果
                "Truncated last CSV line dropped (%d/%d fields): %.60s",
                len(values), len(header),                                                         # 报出实际与期望宽度: 复核者据此定位错位方向
                physical[idx + body_offset] if idx + body_offset < len(physical) else "",
            )
            continue
        # 短行补空串到表头宽度; 键值都去首尾空白 (BEST 的 CSV 列间带空格);
        # 全空行丢弃 (表尾分隔行/空行不算源)。
        padded = values + [""] * (len(header) - len(values))
        row = {key.strip(): value.strip() for key, value in zip(header, padded)}                    # 键值都去空白: 服务端列名常带尾随空格
        # P1-1: 宽于表头的数据行 (值内含未转义逗号 / 服务端偶发多一列) 其
        # 多余值落 overflow_{i} 键 —— 与"据数据行最大宽重贴整表列名"的做法
        # 相反: 列不错位, 多余值显式可见, 且本行计数进 WARN 日志。
        if len(values) > len(header):                                                            # 多余值不丢弃: 落到带序号的溢出键, 可见可查
            overflow_rows += 1                                                                      # 多余行同样计数: 与短行一起构成错位报告
            for i, extra in enumerate(values[len(header):]):                                    # 逐个多余值按序号落键: 静默截断会让数据凭空消失
                row[f"overflow_{i}"] = extra.strip()
        if any(row.values()):                                                                       # 全空行不入库: 站点尾部空行不该变成空源
            rows.append(row)                                                                   # 入库的是补齐后的行: 列宽统一, 下游不必再防短行
    if overflow_rows:                                                                              # 有多余值才告警: 干净响应不该每次都刷一条
        # 一次解析只 WARN 一次 (列错位是数据面事故, 但不该每行刷屏)。
        logger.warning(                                                                          # 多余值告警: 同一现象汇总成一条, 不逐行刷屏
            "parse_csv_rows: %d 行宽于表头 (%d 列), 多余值已落 overflow_* 键"
            " — 检查是否存在未转义分隔符或服务端列数漂移",
            overflow_rows, len(header),                                                         # 报出总行数与列宽: 便于判断是普遍错位还是个别行
        )
    if truncated_rows:                                                                        # 短行单独统计: 截断与溢出是两回事, 混报会误导排查
        # 半行是传输事故 (连接被拦腰截断): 调用方需要知道"少了几行",
        # 否则会把 4 行当全量 — 与 E4 RB-29 的 truncated 语义联动。
        logger.warning(                                                                         # 短行告警: 与溢出分开, 便于定位是哪一侧出问题
            "parse_csv_rows: %d 个半行 (传输截断) 已剔除, 未入库",
            truncated_rows,                                                                       # 只报数量: 行号已在解析层定位, 不在此重复
        )
    if stats is not None:                                                                          # 出参可空: 只关心行本身的调用方不必改签名
        stats.update({"truncated_rows": truncated_rows, "overflow_rows": overflow_rows})            # 丢弃计数出参: 只发日志的丢行对调用方不可见
    return rows


def parse_count(text: str) -> int | None:
    """解析 BEST 的计数响应, 兼容 JSON 与旧式纯整数两种形态。

    Args:
        text: ``getcount`` 端点响应体 (``{"total": N}`` 或裸整数文本)。

    Returns:
        总行数; 空响应或无法解析为整数时返回 ``None`` (调用方按"计数未知"
        处理, 而不是当成 0 行)。
    """
    value = text.lstrip("\ufeff").strip()
    if not value:                                                                                   # 空串不当结构体解: 无载荷时直接回空
        return None
    try:
        payload = json.loads(value)                                                                # 有载荷才尝试解析: 解析失败在这一层显式抛
    except json.JSONDecodeError:
        payload = value                                                                             # 非结构化时原样带过: 站点偶尔回纯文本
    if isinstance(payload, Mapping):                                                              # 只把映射当结构体: 标量载荷不构成可寻址内容
        payload = payload.get("total")
    try:
        return int(payload)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 软错误 (P0-3): HTTP 200 + 短 JSON 错误体
# ---------------------------------------------------------------------------
# BEST 对未知路由、导航分组查询路径和已失效的 sqlid 会话一律回 HTTP 200 + 响应体
# ``{"error":"Not Found"}`` (22B) 或 ``{"error":"Internal Server Error"}`` (34B)
# —— 线上实测 (``calib/stripe82/q``、``std/q``)。不检测的话, 第二阶段会把这样的
# 响应体当成"只有表头的 CSV"解析, 于是失效会话静默表现成一次"成功的空结果",
# 所有 ``http_status == 200`` 门控被绕过。
# 权威来源: 线上错误体实测; 消费方: is_soft_error() / Soft404Error 与两个客户端
# 的响应体门控。
SOFT_ERROR_BODIES: frozenset[str] = frozenset({                                           # 软错误体白名单: BEST 用 200 加这几段文本宣告失败
    '{"error":"Not Found"}',
    '{"error":"Internal Server Error"}',
})

# JSON 软错误体的**键数上界** (BC-03)。白名单是精确匹配, 站点一改文案就落空;
# 于是留了 JSON 回退, 判据是「含 error 键」。但回退也不能无界: 一份真的数据
# 回包也可能带 error 键吗? 不会 —— 但一份大的 JSON 错误信封会带几十个键, 与
# 数据载荷的区分度靠的就是"键很少"。4 足以容纳 error + message + code + time
# 这类伴随字段, 又与真实载荷划得开。判据写在 is_soft_error 的 docstring 里。
_SOFT_ERROR_MAX_KEYS = 4

# 映射到 contracts/error-codes.contract.yaml (BEST_1006), 使门控与调用方能用一个
# 稳定错误码做分支, 而不是去嗅人类可读的响应体文本。消费方: Soft404Error.code 与
# BestQueryResult.error_code。
SOFT_404_ERROR_CODE = "E_SOFT_404"                                                             # 软 404 专属码: 上层据此把软失败与硬失败分开

# 其余运行时错误码 (契约同file: BEST_1001 入参非法 / BEST_1004 无 sqlid / BEST_1009 兜底)。
# 单一事实源必须是协议层: client_paging 抽离件要 import 它们, 从 client import 会成环
# (client → client_paging 委派壳 → client 常量)。
E_INVALID_INPUT = "E_INVALID_INPUT"                                                                 # 入参非法码: 与查无此项分开计数
E_NO_SQLID = "E_NO_SQLID"                                                                     # 阶段 1 未回会话号: 软 404 之外的另一类失败
E_BACKEND = "E_BACKEND"  # T1 补本层真源: 此前 ai_tools 定义 + crossmatch._QUERY_FAILED 各抄一份, 值逐字不变


class Soft404Error(RuntimeError):
    """HTTP 200 但响应体是 BEST 软错误页 (P0-3)。

    用抛异常替代"静默返回空结果", 使 ``http_status`` 门控重新获得判别力。

    Attributes:
        code: 稳定错误码 (:data:`SOFT_404_ERROR_CODE`), 供调用方分支。
        detail: 服务端返回的错误字符串。
        url: 触发软错误的请求 URL (便于定位是路由错还是会话失效)。
    """

    code = SOFT_404_ERROR_CODE                                                                    # 软失败统一用这一支码: 不按回包内容动态造码

    def __init__(self, detail: str, url: str = "") -> None:
        """构造软 404 异常 (detail 原样进入消息, 是运行时契约不可翻译)。

        Args:
            detail: 服务端返回的错误字符串 (如 ``Not Found``)。
            url: 触发软错误的请求 URL; 为空时消息里以 ``the request`` 代替。
        """
        self.detail = detail                                                                       # 可读细节: 服务端给不出时调用方要自己兜底
        self.url = url                                                                            # 目标地址随异常走: 复核时能直接复现这次请求
        super().__init__(                                                                     # 基类消息只放一句: 细节与地址走属性, 不塞进消息体
            f"{self.code}: BEST answered {url or 'the request'} with a soft "
            f"error body ({detail}); the route or session does not exist"
        )


class NameResolveError(RuntimeError):
    """``/nss/solve`` 无法解算天体名 (P1-8)。

    该端点代理 CDS Sesame, 用哨兵对 ``ra=dec=-1000`` (HTTP 200) 表示失败,
    因此只看状态码会把错误坐标当成结果喂给上层。

    Attributes:
        code: 稳定错误码 (``E_NAME_UNRESOLVED``)。
        remark: Sesame 返回的备注 (外部内容, 见 models.ResolvedName 的 S-3 说明)。
    """

    code = "E_NAME_UNRESOLVED"

    def __init__(self, message: str, remark: str = "") -> None:
        """构造天体名解算失败异常 (message 原样进入消息, 是运行时契约)。

        Args:
            message: 人类可读的失败描述。
            remark: Sesame 返回的备注 (外部内容, 原样透传不做解释)。
        """
        self.remark = remark                                                                      # 外部备注原文: 只透传显示, 不自动抓取展开
        super().__init__(f"{self.code}: {message}")


def is_soft_error(text: str) -> bool:
    """判断一个 HTTP 200 响应体是否其实是 BEST 的软错误页。

    精确匹配两条线上实测错误体 (BOM/空白归一化之后), 外加一个宽松 JSON 回退:
    任何能解析成"**含 ``error`` 键且键数很少**"的 JSON 对象。正常 CSV/JSON 负载
    永远不匹配, 因此结果解析不会把数据误判成错误。非字符串输入 (测试替身) 被强转
    为 ``str`` 且永不匹配。

    键数上界为什么必须存在 (BC-03): 判据原先是 ``set(payload) == {"error"}``, 要求
    键集合**精确等于**单键。站点一旦在错误体里多带一个 ``message``/``code``/``time``,
    判据立刻失效 —— 而失效方向是**漏判**: 软错误体被当成数据载荷喂给 CSV 解析器,
    生成一整列伪数据。严格等于是把"服务端加了个字段"直接变成静默事故。

    上界取 ``<= 4`` 而不是不限: 一份真正的数据回包极少只有几个键且还带 ``error``,
    但放开到"任意大小"又会把正常的 JSON 错误对象误吞。上界让"新增一两个伴随字段"
    这类演进能扛住, 同时仍与数据载荷划得开。

    Args:
        text: 响应体。

    Returns:
        True 表示这是软错误页 (调用方应抛 :class:`Soft404Error`)。
    """
    value = str(text or "").lstrip("\ufeff").strip()
    if not value:                                                                                   # 空串不是软错误: 无载荷不等于宣告失败
        return False
    if value in SOFT_ERROR_BODIES:                                                              # 白名单精确匹配: 免得正文里碰巧出现同名词就误判
        return True
    if value.startswith("{") and value.endswith("}"):
        try:
            payload = json.loads(value)                                                           # 有结构才按结构解: 非结构化文本走纯文本分支
        except (json.JSONDecodeError, ValueError, TypeError):
            return False
        # 含 error 键 + 键数不超上界: 不用 == {"error"}, 见上方"键数上界为什么必须存在"
        return (isinstance(payload, Mapping) and "error" in payload
                and len(payload) <= _SOFT_ERROR_MAX_KEYS)
    return False


def soft_error_detail(text: str) -> Optional[str]:
    """返回软错误体里服务端的错误字符串; 不是软错误则返回 ``None``。

    Args:
        text: 响应体。

    Returns:
        服务端 ``error`` 字段值 (解析失败时退回归一化后的原文), 或 ``None``。
    """
    if not is_soft_error(text):                                                                 # 非软错误体不进这条解析: 正常回包不必付解析代价
        return None
    value = str(text or "").lstrip("\ufeff").strip()
    try:
        payload = json.loads(value)                                                                 # 尝试按结构解: 软错误体也可能是结构化的
    except (json.JSONDecodeError, ValueError, TypeError):
        return value
    if isinstance(payload, Mapping):                                                              # 只有映射才是结构体: 标量载荷不构成失败标记
        return str(payload.get("error", value))
    return value


# ---------------------------------------------------------------------------
# 天体名解算 (P1-8): /nss/solve 代理 CDS Sesame
# ---------------------------------------------------------------------------

def is_name_resolve_failure(payload: Any) -> bool:
    """判断一个 ``/nss/solve`` 响应是否携带失败哨兵。

    哨兵是 ``ra=dec=-1000`` (不是一个错误状态码), 因此靠这个检查 —— 而不是
    HTTP 码 —— 把错误坐标挡在结果之外。非 Mapping 负载 (或 ra/dec 无法转 float)
    一律视为失败: 宁可误判失败, 也不要把无意义坐标当结果。

    Args:
        payload: :func:`parse_name_resolve` 解析出的负载。

    Returns:
        True 表示解算失败 (调用方应抛 :class:`NameResolveError`)。
    """
    if not isinstance(payload, Mapping):                                                            # 非映射即非结构体: 后面按标量处理
        return True
    try:
        ra = float(payload.get("ra", NAME_RESOLVE_FAIL_SENTINEL))
        dec = float(payload.get("dec", NAME_RESOLVE_FAIL_SENTINEL))
    except (TypeError, ValueError):
        return True
    return ra <= NAME_RESOLVE_FAIL_SENTINEL or dec <= NAME_RESOLVE_FAIL_SENTINEL


# ---------------------------------------------------------------------------
# 重试策略 (P1-6): 两个客户端共用的唯一出处
# ---------------------------------------------------------------------------
# BestClient 用这些常量配置 urllib3 的 Retry —— 重试的**唯一**一层就在那里。
# 原先并列的第二个入口 (pybest 打包产物里的手写重试循环, 及其 is_retryable_status
# 一族助手) 随该模块一并删除, 故"两个入口防漂移"已无从谈起; 见下方 P3-2 注记。
# 软错误 (HTTP 200 + 错误体) 不是状态码, 因此无法进
# forcelist —— 两个客户端都在响应体层面检测它 (is_soft_error / Soft404Error, P0-3)。
# 权威来源: BEST 线上重试行为实测; 消费方: src 客户端模块的全部请求路径。
RETRY_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})                        # 只重试可恢复码: 业务性 4xx 重试没有意义
# 最大重试次数 (不含首次请求); 消费方同上。
MAX_RETRIES = 3                                                                                # 次数封顶: 再多也不把一次瞬时抖动放大成十几轮请求
# 基准退避 (秒): 第一次重试前的等待时长; 消费方同上。
RETRY_BACKOFF_S = 2.0                                                                   # 退避基数: 服务端 Retry-After 优先, 此值只作兜底
# 单次退避上限 (秒): 指数退避的封顶值; 消费方同上。
MAX_BACKOFF_S = 60.0                                                                         # 退避上限: 无上限时重试会拖到分钟级, 调用方以为卡死

# P3-2: 本层不得再暴露 is_retryable_status/parse_retry_after/backoff_delay 一类
# 公开助手 — 它们生产零引用 (只有自家测试消费), 且它们是一套"手写第二重试层"
# 的 dormant 零件: 重试的唯一层在 session 的 HTTPAdapter (Retry +
# respect_retry_after_header), 再留手工解析器就是 P1-6 刚修掉的双层结构。
# 按 Q-09 (公开符号须有生产引用) 删除; README 能力边界表的相应表述同步修正。


def parse_name_resolve(text: str) -> dict[str, Any]:
    """把 ``/nss/solve`` 响应体解析成普通 payload dict。

    失败不由返回值表达: 哨兵在 200-OK 响应体内部, 调用方必须对返回值调用
    :func:`is_name_resolve_failure`。

    Args:
        text: 响应体。

    Returns:
        解析后的 payload dict。

    Raises:
        ValueError: 响应体不是可解析的 JSON 对象。
    """
    value = str(text or "").lstrip("\ufeff").strip()
    try:
        payload = json.loads(value)                                                                 # 计数体按结构解: 站点回的是单键映射
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"unparseable solve response: {value[:80]!r}") from exc
    if not isinstance(payload, Mapping):                                                            # 非映射不当计数: 标量载荷拿不到计数键
        raise ValueError(f"solve response is not a JSON object: {value[:80]!r}")
    return dict(payload)
