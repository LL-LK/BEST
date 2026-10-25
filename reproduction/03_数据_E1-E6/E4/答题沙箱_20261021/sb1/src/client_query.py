# -*- coding: utf-8 -*-
"""src.client_query — BestClient 的通用查询表面 (抽离件, budget §3.2 阶段 2/4/5)。

能力边界: 列约束/锥形/proximity 三类查询的**表单构造与执行编排** —
``build_form`` (共享表单构造, 六个查询方法的唯一表单源) + ``query_result``
(信封 seam, E2 对账消费) / ``query`` (裸行投影, TAP 后端消费) /
``_query_result`` (两者共享的执行主体)。抽离缘由: client.py 当时 581 净行仍超
400 预算 (§3.2 阶段 2 预案)。

**阶段 4/5 扩边 (2026-10-05)**: 本模块头自建立起就宣称覆盖「列约束 / 锥形 /
proximity 三类查询的表单构造与执行编排」, 但锥形与 proximity 两类此前仍留在
client.py —— **声明的能力边界与实际持有不一致**。阶段 4 把 ``cone_search``
(锥形, 含 std 导航组成员展开与合并) 与 ``crossmatch_batch`` (proximity 批量)
补齐进来; 阶段 5 再补 ``query_standard_stars`` / ``query_panstarrs`` /
``query_calibrated`` (三个固定星表查询缝) —— 至此边界首次与持有完全对齐,
client.py 同时降到 400 预算内。五者形态与阶段 1/2 同款: 原地委派壳保留
``BestClient`` 上的同名同签名公开 seam。

契约 (与阶段 1/2 同款):
  - 原地委派壳: ``BestClient._build_form`` 保留 (其余查询方法的调用点零
    改动); ``query_result``/``query``/``cone_search``/``crossmatch_batch``
    与三个固定星表查询方法皆为公开 seam, 壳只做转发;
  - self 依赖面经 client 参数穿透 (`base_url` / `_execute_query` / `_build_form` /
    `_query_result` / `cone_search` 递归 —— 清单即 `client.<属性>` 的全量 AST
    实测, 新增 client 属性时必须同步加进这一行; 本模块不碰 session, 会话由
    phase-1 建);
  - 约束方言双拼写容忍 (column/op/value:{min,max} ↔ name/op/扁平) 不变 —
    E2/E5 场景 YAML 与 TAP 执行器两种方言都收;
  - 锥形路径的入参校验 (Q-51) 与 std 组的**单点失败隔离 + 失败码透传 +
    truncated 取 or** 逐条不变 —— 后三者是 P2-5 修掉的静默失败面。
    失败码透传只覆盖 `part.error` 一支: 成员**抛异常**那条 (`:439`) 无码可透,
    只记 `error` 并置 `success=False`, 故那种信封的 `error_code` 留 None。

白盒锚点: src/client.py (公开 seam 与 phase-1 执行组) / src/client_paging.py
(phase-2 取数引擎) / src/protocol.py (build_query_form 权威层) /
src/crossmatch.py (proximity 批量路径的唯一下游消费方)。
"""
from __future__ import annotations

# 标准库: 可缺查询参数的统一标注写法 / logger (std 组单点失败隔离要留痕)
import logging  # std 组成员失败的告警: 只报异常文本看不出是哪张表挂了
from typing import Optional  # 用 Optional 而非 | None: 与 client.py 既有签名写法保持一致

# 本地: 数据模型 (列约束/查询结果载体) 与协议层权威件 (表单构造/星表路径/
# 导航组成员表/波段列映射/软错误判定/错误码/phase-1 交接格式/proximity 线格式/
# 导出格式白名单)
from src.models import BestQueryResult, ColumnConstraint  # 内部唯一形态: 表单与执行都只见 ColumnConstraint
from src.protocol import (
    CATALOG_GROUPS,  # 导航组成员表: cone_search 的 std 组展开据此取成员
    CATALOG_PATHS,  # 星表 id 到查询路径的映射: 路径查表只认归一后的 id
    PHASE1_HANDOFF_FORMAT,  # 阶段一唯一合法格式: 改它就取不回会话标识
    SOFT_404_ERROR_CODE,  # 软 404 错误码: 可重试的软失败与硬失败靠它分开
    Soft404Error,  # 软失败异常: 抛给调用方时带实际请求地址
    build_query_form,  # 表单键集单一来源: 绕过它就会与站点实测表单漂移
    magnitude_column,  # 波段到真实列名的映射: 猜列名是非 ps1 锥搜返 0 行的根因
    proximity_radec_text,  # proximity 坐标块线格式: 串只此一处拼, 免得与服务端解析漂移
    resolve_catalog,  # 星表归一: 未登记 id 在碰网络前就早炸
    validate_export_format,  # 导出格式白名单: 非法格式必须在建会话之前拒掉
)

# 本地: 入参校验 (坐标/半径合法性, Q-51 入口即拒)。src.scripts 走 PEP 562
# 惰性导出, 模块顶部导入不与本模块成环 (guards 只依赖 src.csv_safety)。
from src.scripts.guards import validate_coordinate, validate_search_radius

logger = logging.getLogger(__name__)  # 模块级 logger: std 组单点失败的告警走调用方配置的 handler


def build_form(
    client,                                                                                         # 客户端: 表单构造与两阶段执行都经它
    catalog: str,                                                                                   # 星表 id: 必填且须可归一
    constraints: list[ColumnConstraint],                                                        # 列约束列表: 缺省空列表, 纯空间锥搜也走这条路
    max_rows: int,                                                                                 # 取回上限: phase-2 本地封顶; build_query_form 无此键, 不进阶段 1 表单、不改服务端会话 (A2-03)
    ra: Optional[float] = None,                                                                     # 锥搜赤经可空: 三参数须同时给齐
    dec: Optional[float] = None,                                                                    # 锥搜赤纬可空: 与赤经同进同出
    radius_arcsec: Optional[float] = None,                                                         # 角秒半径可空: 少给一个就退化成无空间约束
    radec_text: Optional[str] = None,                                                     # 坐标块文本可空: proximity 批量路径用它取代三元组
    default_radius_arcsec: Optional[float] = None,                                        # 逐行默认半径可空: 给才下发, 服务端自带值与本地口径不一致
    columns: Optional[list[str]] = None,                                                            # 列投影可空: 缺省下发该星表全部登记列
    sort: Optional[str] = None,                                                                   # 排序列可空: 空串是明确不排序, 不回落默认
    order: str = "asc",
    nearest_only: bool = False,                                                                    # 最近邻开关: 由服务端过滤, 不在本地裁剪
) -> dict[str, str]:
    """Phase-1 检索表单: 委托 protocol.build_query_form (权威协议层, Q-01)。

    键集必须由协议层生成, 且以星表表单页实测为准: 一律走 ``pos.*`` 锥搜/矩形键,
    自建 ``{col}.constraint`` box-between 键集与之完全不相交, 会让锥形检索
    结构性失效, 不可回退。``showcol`` 投影同样以表单页实测为准。

    ``output.fmt`` 固定为 ``html`` (PHASE1_HANDOFF_FORMAT): 这是唯一能取回
    ``sqlid`` 的提交形态; 行数据在 phase-2 以 ``output.fmt=csv`` 分页拉取。
    空间选择 (ra/dec/radius_arcsec 锥, box, radec_text) 由协议层互斥校验。

    ``radec_text`` 走服务端 ``pos.type=proximity`` 批量坐标匹配 (P0-1),
    ``default_radius_arcsec`` 是其默认匹配半径; ``columns`` 收窄 ``showcol``
    投影, ``sort``/``order`` 服务端排序, ``nearest_only`` 每输入位置只留
    最近邻 (P1-8)。
    """
    items = [  # 手写五元组而非 asdict: 协议层按"键存在"判区间/标量, 补全字段会改语义
        {                                                                                        # 每条约束一个字典: 键名与协议层读取的完全一致
            "name": c.name,
            "constraint": c.constraint,
            "min": c.min,
            "max": c.max,
            "value": c.value,
        }
        for c in (constraints or [])  # None 不能直接迭代: 纯空间锥搜无列过滤, 归一在此一次
    ]
    return build_query_form(  # 键集以星表表单页实测为准: 绕过协议层就会与真实表单漂移
        catalog,                                                                                    # 星表传首位: 渲染层靠它解析波段与质量列
        items,                                                                                      # 约束项整份传: 顺序即输出顺序
        output_format=PHASE1_HANDOFF_FORMAT,  # html 是 phase-1 唯一能取回 sqlid 的形态, 改它就取不回
        ra=ra,                                                                                      # 赤经: 位置键, 与赤纬半径同进同出
        dec=dec,                                                                                    # 赤纬: 同上
        radius_arcsec=radius_arcsec,                                                                # 角秒半径: 上游锥形接口以角秒为单位
        radec_text=radec_text,                                                               # 坐标块: proximity 路径专用, 与三元组互斥
        default_radius_arcsec=default_radius_arcsec,                                                # 逐行默认半径: 只随坐标块一起下发
        sort=sort,                                                                                  # 排序列: 过白名单后才进表单
        order=order,                                                                                # 排序方向: 只在有排序列时携带
        nearest_only=nearest_only,                                                                  # 最近邻开关: 服务端只判键是否存在
        show_columns=columns,                                                                       # 列投影: 每列都过同一套逐星表白名单
    )


def query_result(
    client,                                                                                         # 客户端: 共享执行主体要经它的会话
    catalog: str = "ps1",
    constraints: Optional[list[dict]] = None,                                                       # 约束可空: 缺省即无列过滤
    ra: Optional[float] = None,                                                                     # 锥搜赤经可空: 同上
    dec: Optional[float] = None,                                                                    # 锥搜赤纬可空: 同上
    radius_arcsec: Optional[float] = None,                                                          # 角秒半径可空: 同上
    max_rows: int = 50000,                                                                         # 取回上限: 与信封版同口径, 便于两缝对照
    columns: Optional[list[str]] = None,                                                            # 列投影可空: 不给则取完整列
    sort: Optional[str] = None,                                                                     # 排序列可空: 站点直传字符串
    order: str = "asc",
    nearest_only: bool = False,                                                                     # 最近邻开关: 缺省关, 交调用方显式要求
) -> BestQueryResult:
    """``query`` 的同参信封版: 返回完整 BestQueryResult (含 total/truncated)。

    存在理由: ``query`` 按 TAP 后端契约只回裸行投影 (行字典);
    评测/审计面 (E2 对账的 M4 截断三元组、M5 四态、M6 provenance) 需要
    信封字段, 故开一个同参的信封缝 — 两条缝共享同一执行路径
    (``_build_form`` → ``_execute_query``), 不会漂移出两套结果。
    """
    return client._query_result(  # 原样转发: 归一全压进 _query_result, 两条缝才不会演化出不同错误语义
        catalog, constraints, ra, dec, radius_arcsec, max_rows,                                     # 位置直传: 与共享主体签名逐位对齐
        columns, sort, order, nearest_only,                                                      # 尾部四项: 顺序固定, 错位不报错只静默换结果
    )


def query(
    client,                                                                                         # 客户端: 裸行投影与信封共享同一次执行
    catalog: str = "ps1",
    constraints: Optional[list[dict]] = None,                                                       # 约束可空: 双拼写方言由共享主体归一
    ra: Optional[float] = None,                                                                     # 赤经可空: 非锥搜路径不传
    dec: Optional[float] = None,                                                                    # 赤纬可空: 与赤经同进同出
    radius_arcsec: Optional[float] = None,                                                          # 角秒半径可空: 三者齐备才是原生锥搜
    max_rows: int = 50000,                                                                          # 取回上限: 与信封版同口径
    columns: Optional[list[str]] = None,                                                            # 列投影可空: 不给则取完整列
    sort: Optional[str] = None,                                                                     # 排序列可空: 拼错静默退回默认序
    order: str = "asc",
    nearest_only: bool = False,                                                                 # 最近邻开关: 缺省关, 免得调用方误以为已去冗余
) -> list[dict]:
    """通用列约束查询 → **裸行投影** (TAP 后端与脚本式调用面, P1 合并入口)。

    两阶段协议 (phase-1 表单 → sqlid → phase-2 分页) 的表单构造与执行都经本类的
    协议层单点 (``_build_form`` / ``_execute_query``): 本仓不允许出现第二份协议
    编排副本, 新增查询入口必须挂到这两个单点上。dict 形态的 constraints
    (``{name, op, value|min|max}``) 在
    此翻译为 ``ColumnConstraint`` — 与 TAP 执行器 ``_query_kwargs`` 的
    产出对齐。

    返回**站点原始列名的裸行** (``BestSource.raw_data`` 的拷贝), 不做
    归一化: 归一化行会追加 ``magnitudes`` 字典, 被 VOTable 转换层
    ``str()`` 成 ``"{'g': 19.4}"`` 字符列, 污染科学消费端的类型推断
    (TAP 后端的硬要求; 领域模型路径的归一化由 ``BestSource.from_row``
    承担, 两个消费面从此各取所需)。

    Args:
        catalog: 星表 id (导航组名会被拒绝)。
        constraints: 列约束 dict 列表 (``{name, op, value|min|max}``)。
        ra/dec/radius_arcsec: 可选原生服务端锥搜 (度/度/角秒)。
        max_rows: 最大行数。
        columns: showcol 投影 (None = 全部列)。
        sort/order: 服务端排序键与方向。
        nearest_only: 锥搜时每位置只留最近邻。

    Returns:
        裸行投影字典列表; 服务端无 sqlid (合法空结果) 时返回 []。

    Raises:
        Soft404Error: 回包是软错误体 (路由不存在/会话死亡, P0-3)。
        RuntimeError: 其余查询失败 (错误信息原样带出, 不降级为空结果)。
    """
    result = client._query_result(  # 先拿信封再投影: 两缝共享同一次执行, 否则 sqlid 与 total 会对不上
        catalog, constraints, ra, dec, radius_arcsec, max_rows,                             # 先拿信封再投影: 两缝共享同一次执行, 否则总数会对不上
        columns, sort, order, nearest_only,                                                         # 尾部四项顺序固定: 错位只表现为结果不对
    )
    return [dict(s.raw_data) for s in result.sources]  # dict 拷贝: 防调用方就地修改反写进缓存的 source 对象


def _query_result(
    client,                                                                                         # 客户端: 共享主体的会话与限流都在它身上
    catalog: str,                                                                                 # 星表 id: 裸 id, 归一在函数首行完成
    constraints: Optional[list[dict]],                                                              # 约束可空: 两种方言拼写在此收敛
    ra: Optional[float],                                                                            # 赤经可空: 三参数同进同出
    dec: Optional[float],                                                                           # 赤纬可空: 同上
    radius_arcsec: Optional[float],                                                                 # 角秒半径可空: 同上
    max_rows: int,                                                                                  # 取回上限: phase-2 本地封顶, 不改服务端会话 (A2-03)
    columns: Optional[list[str]],                                                                   # 列投影可空: 缺省为该星表全部登记列
    sort: Optional[str],                                                                            # 排序列可空: 空串是明确不排序
    order: str,                                                                                     # 排序方向: 缺省升序由上层给值
    nearest_only: bool,                                                                             # 最近邻开关: 显式传入, 不设隐式默认
) -> BestQueryResult:
    """query/query_result 共享的执行主体 (表单构造 → 两阶段执行 → 失败判定)。

    失败语义 (两条缝一致): 软错误体抛 Soft404Error, 其余失败抛
    RuntimeError (错误信息原样带出, 不降级为空结果 — M5 四态判据)。
    """
    resolved = resolve_catalog(catalog)  # 碰网络前先解析: 未登记 id 早炸, 免拿请求去换 404 页
    items = []  # 先归一成 ColumnConstraint: 协议层只见一种键名形态
    for c in (constraints or []):                                                                   # 逐条归一: 协议层只见一种键名形态
        op = str(c.get("op") or c.get("constraint") or "equal")  # 方言双拼写: YAML 写 op, TAP 写 constraint
        value = c.get("value")  # 是区间容器还是标量, 决定 lo/hi 怎么取
        if isinstance(value, dict):  # {min,max} 容器形态: 必须与下面平铺写法等价
            lo, hi, scalar = value.get("min"), value.get("max"), None
        else:
            lo, hi, scalar = c.get("min"), c.get("max"), value
        items.append(ColumnConstraint(  # 空列名不在此拦: 交协议层报软错误, 避免两处措辞不一致
            name=str(c.get("name") or c.get("column") or ""),
            constraint=op,                                                                          # 操作名: 缺省按等于处理, 不猜
            min=lo,                                                                                 # 下界: 区间容器与平铺写法取到的是同一处
            max=hi,                                                                                 # 上界: 同上
            value=scalar,                                                                         # 标量值: 区间形态下必须为空, 否则语义混淆
        ))
    form = build_form(  # 表单唯一来源: 绕过它键集就会与星表实测表单漂移, 锥搜失效正是这么来的
        client, resolved, items, max_rows,                                                          # 实例与星表随行传: 被委派方靠它回调会话
        ra=ra, dec=dec, radius_arcsec=radius_arcsec,                                            # 几何三参数同传: 少一个就退化成无空间约束的查询
        columns=columns, sort=sort, order=order, nearest_only=nearest_only,                      # 投影排序与最近邻同传: 少一项就静默少一项能力
    )
    result = client._execute_query(  # 末位 1000 是 phase-2 分页批大小: 更细的截断边界换双倍请求数
        CATALOG_PATHS[resolved], form, "csv", max_rows, 1000,
    )
    if not result.success:  # 不折叠成空列表: 空结果与"查无此项"不可区分, 混同即数据事故
        if result.error_code == SOFT_404_ERROR_CODE:  # 软错误可重试, 与参数写错的硬失败分开, 否则上层盲目重试
            raise Soft404Error(
                result.error or "soft error",
                f"{client.base_url}/{CATALOG_PATHS[resolved]}",  # 带实际 URL: 软错误排查只能靠它
            )
        raise RuntimeError(result.error or "query failed")  # 抛而不降级: M5 四态要求失败与零行可区分
    return result


def query_standard_stars(
    client,                                                                                         # 客户端: 三个查询方法共用同一出口, 失败语义因此一致
    constraints: Optional[list[ColumnConstraint]] = None,                                           # 可选列约束: None 与空列表等价, 键集仍固定下发
    output_format: str = "csv",                                                                     # 声明式格式: 只进溯源, 阶段 2 一律按 csv 拉
    max_rows: int = 50000,                                                                          # 取回上限: 与页大小解耦, 批处理时好按批切
    page_size: int = 1000,                                                                          # 每页行数: 单页过大时一次失败就要重跑整页
    table: str = "scr_lamost",                                                                      # 标准星成员表: 导航组名本身会被 /q 路由拒绝
    columns: Optional[list[str]] = None,                                                            # 可选列投影: 不给就按该星表的完整实测列清单下发
    sort: Optional[str] = None,                                                                     # 服务端排序键: 拼错时站点静默退回默认序, 不报错
    order: str = "asc",                                                                              # 升序为默认: 最近邻类查询要先取到角距最小的一批
    nearest_only: bool = False,                                                                     # 只留最近邻: 跨匹配批量时按输入位置去冗余
) -> BestQueryResult:
    """查询 Standard Stars 组成员表之一。

    BEST 把 Standard Stars 发布为 ``std`` 导航组; 可查询成员是
    ``scr_galah``、``scr_lamost`` 和 ``xpsp`` (导航组名本身会被 /q
    路由拒绝, 见 :meth:`cone_search` 的组展开逻辑)。

    Args:
        constraints: 列约束列表 (ColumnConstraint)
        output_format: 声明的导出格式 (csv/txt/json/votable 之一, 大小写
            不敏感)。注意: 阶段 2 始终以 csv 拉取后本地解析, 该值进
            ``query_params`` 溯源, 真正的格式转换在落盘层 (P2-9)
        max_rows: 最大返回行数
        page_size: 每 API 页行数
        table: Standard Stars 成员 id (默认 ``scr_lamost``)
        columns: 可选 ``showcol`` 投影 (P1-8); 默认该星表完整实测列清单
        sort: 可选服务端排序列 (``{table}.{col}`` 或裸列名)
        order: ``asc`` (默认) 或 ``desc``
        nearest_only: 每个输入位置只留最近邻

    Returns:
        BestQueryResult
    """
    output_format = validate_export_format(output_format)  # 校验前置: 非法格式要在发请求前拒, 不白建一次 sqlid 会话
    path = CATALOG_PATHS[resolve_catalog(table)]           # 表名到路径的映射归协议层: 客户端不认 URL 拼接规则
    form = client._build_form(                               # 空约束也要建表单: 键集固定, 服务端据此判定返回列
        table, constraints or [], max_rows,  # 位置传参: 顺序与表单生成实现逐位对齐, 错位不报错只查空
        columns=columns, sort=sort, order=order, nearest_only=nearest_only,  # 四个投影与排序开关同传: 拆开写必漏一半, 站点静默忽略未知键
    )
    return client._execute_query(path, form, output_format, max_rows, page_size)  # 位置传参: 顺序与 _execute_query 签名逐位对齐


def query_panstarrs(
    client,                                                                                         # 客户端: 本方法只固定表名, 其余能力与另两个查询方法同源
    constraints: Optional[list[ColumnConstraint]] = None,                                           # 可选列约束: 空列表也要建表单, 键集固定
    output_format: str = "csv",                                                                     # 声明式格式: 走同一份白名单校验
    max_rows: int = 50000,                                                                          # 取回上限: 缺省值与另两个查询方法一致, 便于横向比较
    page_size: int = 1000,                                                                          # 每页行数: ps1 行宽, 页太大回包解析压力高
    columns: Optional[list[str]] = None,                                                            # 可选列投影: ps1 列数多, 投影能显著缩小回包
    sort: Optional[str] = None,                                                                     # 服务端排序列: 与页序一致才能拿到稳定的前 N 行
    order: str = "asc",                                                                              # 升序默认: 与排序键配对才有确定含义
    nearest_only: bool = False,                                                                     # 最近邻开关: 批量匹配时才需要, 单次全表查不置
) -> BestQueryResult:
    """查询 Pan-STARRS All-Sky 星表 (ps1)。

    Args:
        constraints: 列约束列表 (ColumnConstraint)
        output_format: 声明的导出格式 (csv/txt/json/votable 之一, 大小写
            不敏感)。注意: 阶段 2 始终以 csv 拉取后本地解析, 该值进
            ``query_params`` 溯源, 真正的格式转换在落盘层 (P2-9)
        max_rows: 最大返回行数
        page_size: 每 API 页行数
        columns: 可选 ``showcol`` 投影 (P1-8)
        sort: 可选服务端排序列 (P1-8)
        order: ``asc`` (默认) 或 ``desc``
        nearest_only: 每个输入位置只留最近邻 (P1-8)

    Returns:
        BestQueryResult
    """
    output_format = validate_export_format(output_format)  # 同一份格式白名单: 三个查询方法共用一个校验入口
    form = client._build_form(                               # 表名写死 ps1: 本方法不开放换表, 换表请走 query_calibrated
        "ps1", constraints or [], max_rows,  # 表名写死 ps1: 本方法不开放换表, 换表走巡天查询
        columns=columns, sort=sort, order=order, nearest_only=nearest_only,  # 四个可选键同传: 少一个就静默少一项能力
    )
    return client._execute_query("ps1/q", form, output_format, max_rows, page_size)  # 路径与 CATALOG_PATHS 表项同值, 固定表名时省一次查表


def query_calibrated(
    client,                                                                                         # 客户端: 旧别名归一后才允许进路径表查路径
    survey: str = "stripe82",                                                                       # 巡天名: 接受旧别名, 归一后写进表单的是新拼写
    constraints: Optional[list[ColumnConstraint]] = None,                                           # 可选列约束: 归一后按目标表的可选列判定
    output_format: str = "csv",                                                                     # 声明式格式: 走同一份白名单, 避免建会话后才发现非法
    max_rows: int = 50000,                                                                          # 取回上限: 与另两个查询方法同口径
    page_size: int = 1000,                                                                          # 每页行数: 巡天表行宽不同, 页大小只影响往返次数
    columns: Optional[list[str]] = None,                                                            # 可选列投影: 不给则取该表完整实测列
    sort: Optional[str] = None,                                                                     # 服务端排序列: 排序键的表前缀要跟归一后的表名一致
    order: str = "asc",                                                                              # 升序默认: 站点对未知值不报错, 写错只会静默换序
    nearest_only: bool = False,                                                                     # 最近邻开关: 仅在按坐标批匹配时有意义
) -> BestQueryResult:
    """查询一个 well-calibrated 巡天星表。

    支持的 survey: stripe82, gaia_dr3_18 (旧别名 ``gaia_dr3`` 仍接受),
    jplus_dr3, smss_dr4, landolt, uss_dr1, splus_dr4, ps1

    Args:
        survey: 巡天名 (如 ``"stripe82"``、``"gaia_dr3_18"``)
        constraints: 列约束列表 (ColumnConstraint)
        output_format: 声明的导出格式 (csv/txt/json/votable 之一, 大小写
            不敏感)。注意: 阶段 2 始终以 csv 拉取后本地解析, 该值进
            ``query_params`` 溯源, 真正的格式转换在落盘层 (P2-9)
        max_rows: 最大返回行数
        page_size: 每 API 页行数
        columns: 可选 ``showcol`` 投影 (P1-8)
        sort: 可选服务端排序列 (P1-8)
        order: ``asc`` (默认) 或 ``desc``
        nearest_only: 每个输入位置只留最近邻 (P1-8)

    Returns:
        BestQueryResult
    """
    output_format = validate_export_format(output_format)  # 格式白名单统一前置: 避免建会话后才发现格式非法
    resolved = resolve_catalog(survey)                     # 旧别名在此收敛: gaia_dr3 归一后才允许进路径查表
    path = CATALOG_PATHS[resolved]                         # 必须先归一再查表, 否则旧别名在表里没有条目
    form = client._build_form(                               # 表单里写归一后的 id: 服务端只认新拼写
        resolved, constraints or [], max_rows,  # 表单里写归一后的 id: 服务端只认新拼写
        columns=columns, sort=sort, order=order, nearest_only=nearest_only,  # 四个可选键同传: 与另两个查询方法完全同构
    )
    return client._execute_query(path, form, output_format, max_rows, page_size)  # 同一条出口: 三个查询方法的失败语义因此一致


def cone_search(
    client,                                                                                         # 客户端: 锥搜与巡天查询共用同一出口 (会话/限流/表单/执行都经它)
    ra: float,                                                                                      # RA(度, ICRS): 入口即校验, 负值直接拒
    dec: float,                                                                                     # Dec(度, ICRS): 越界值在入口拒, 否则服务端只回空集
    radius_arcsec: float = 180.0,                                                                    # 角秒半径: 天文语境下比度更贴近使用习惯
    catalog: str = "ps1",                                                                            # 星表 id: 导航组名会被展开成成员逐个查再合并
    band: Optional[str] = None,                                                                      # 波段过滤: 经协议层映射成真实列, 不给即不限波段
    max_records: int = 1000,                                                                         # 返回记录上限: 组查询时按成员数分摊, 总量仍以此封顶
    page_size: int = 1000,                                                                           # 每页行数: 默认与上限同值, 便于单页取完
    columns: Optional[list[str]] = None,                                                             # 可选列投影: 不给则按该表完整列清单
    sort: Optional[str] = None,                                                                      # 服务端排序列: 按角距排才便于取最近邻
    order: str = "asc",                                                                              # 升序: 最近邻语义要求角距由小到大
    nearest_only: bool = False,                                                                      # 只留最近邻: 批量输入时每个位置只留一条
) -> BestQueryResult:
    """锥形检索: 以天球位置为中心的圆域查询 (原生服务端锥搜, Q-01)。

    锥形通过协议层的原生 ``pos.type=cone`` 字段提交, 而不是 RA/Dec
    box-between 约束 — 后者服务端从未接受, 那样锥搜结构性失效。

    Args:
        ra: RA (度, ICRS)
        dec: Dec (度, ICRS)
        radius_arcsec: 检索半径 (角秒)
        catalog: 可查询星表 id (ps1, stripe82, gaia_dr3_18, jplus_dr3,
            smss_dr4, landolt, uss_dr1, splus_dr4, scr_galah, scr_lamost,
            xpsp, dr3xpcorr), 或导航组 ``std`` (展开为全部成员后合并)
        band: 可选波段过滤
        max_records: 最大返回记录数
        page_size: 每 API 页行数
        columns: 可选 ``showcol`` 投影 (P1-8); 默认该星表完整实测列清单
        sort: 可选服务端排序列 (P1-8)
        order: ``asc`` (默认) 或 ``desc``
        nearest_only: 只保留最近邻 (P1-8)

    Returns:
        BestQueryResult (``std`` 组为各成员表合并结果)
    """
    if catalog == "std":  # 导航组走成员展开分支: 组名本身不是可查询路由
        # Q-22: std 是导航组; 展开为全部成员表并合并。不得静默改写成
        # 单一表 (硬编码 table=scr_lamost 会让用户以为搜的是标准星全集)。
        members = list(CATALOG_GROUPS["std"])  # 取成员表副本: 循环期间若有人改组表, 迭代不受影响
        # P2-5 ③ + SA-P3-4: 成员各取 max_records 会让合并结果 N 倍超限 —
        # 总量封顶按成员数分摊 (末次截断置 truncated), 与单表路径语义一致
        per_member = (max(1, max_records // len(members))  # 按成员数分摊上限: 不分摊会让合并结果成 N 倍超限
                      if max_records else max_records)  # 上限不限时不分摊: 整数除法会把不限变成 0
        merged = BestQueryResult(  # 合并信封先建空壳: 计数在循环里逐成员累加
            success=True, total_count=0, returned_count=0,  # 先乐观置成功: 任一成员失败时在循环里翻回 False
            # P2-5 ②: 合并结果带溯源 (溯源恒 {} 就无法回答"这结果是谁合并的")
            query_params={  # 溯源必须带成员清单: 否则无法回答结果是谁合并来的
                "catalog": "std",  # 记组名而非首张成员表: 溯源恒空字典就断链
                "members": members,  # 成员表 id 逐个登记: 复现同一结果的前提
                "ra": ra, "dec": dec,  # 中心坐标入溯源: 同参数不同中心的结果不可混用
                "radius_arcsec": radius_arcsec,  # 半径入溯源: 半径变化会改变成员返回集
                "band": band,  # 波段入溯源: 为空也要留键, 免得对账时缺字段
            },
        )
        for member in members:  # 逐成员查询: 单点失败隔离在循环体内, 不炸整组
            # P2-5 ③: 单点失败隔离 — 不加 try 时, band="u" 的
            # magnitude_column("xpsp","u") 抛出的 ValueError 会从循环内
            # 直接冒泡,
            # 炸掉整个组查询 (一个成员的坏波段让另外两张表也查不成)
            try:
                part = client.cone_search(  # 递归调本方法: 传裸成员 id, 不会再进组分支
                    ra=ra, dec=dec, radius_arcsec=radius_arcsec,  # 中心与半径对所有成员一致: 组查询不改几何条件
                    catalog=member, band=band, max_records=per_member,  # 传分摊后的上限: 避免单个成员吃满全部配额
                    page_size=page_size, columns=columns, sort=sort,  # 页大小与投影沿用调用方口径: 组内各表保持同形
                    order=order, nearest_only=nearest_only,  # 排序与最近邻开关同传: 各成员排序不一致时合并无意义
                )
            except Exception as exc:  # noqa: BLE001 单点失败隔离: 记后继续
                logger.warning("std group member %s failed: %s", member, exc)  # 记成员名: 只报异常文本看不出是哪张表挂了
                merged.success = False  # 整体标失败: 部分成员可用的结果不得当成完整成功
                merged.error = f"{member}: {exc}"  # 错误带成员前缀: 多成员失败时能定位最后一个
                continue
            merged.sources.extend(part.sources)  # 追加而非替换: 循环里多次 extend 才不会只剩最后一张表
            # 三个计数逐项累加而非只加 sources: total_count 与
            # returned_count 语义不同 (服务端报告总数 vs 实际取回),
            # 只累一个会让上层把"取回数"当"总数"报出去。
            merged.total_count += part.total_count  # 服务端报告总数逐项累加: 与取回数语义不同, 不能只加一个
            merged.returned_count += part.returned_count  # 实际取回数单独累加: 上层靠它判断是否被上限截断
            # truncated 用 or 而非 and: 任一成员截断则合并结果即截断,
            # 这是保守取法 — 宁可多报截断, 不可让调用方以为数据完整。
            merged.truncated = merged.truncated or part.truncated  # 取 or 而非 and: 任一成员截断即整体截断, 宁可多报
            merged.success = merged.success and part.success  # 成功状态取 and: 任何成员失败都不能被后面的成功盖掉
            if part.error:  # 有错误消息才覆盖: 空错误不该把已有描述冲掉
                merged.error = part.error  # 保留最近一次失败原因: 全量错误列表会让信封无法读
                # P2-5 ①: 失败码透传 (恒 None 时合并失败与成功无法区分)
                merged.error_code = part.error_code or merged.error_code  # 失败码透传: 恒 None 时合并失败与成功无法区分
        # 总量封顶: 分摊后仍可能超出 (成员行数不均), 截断并如实标记
        if max_records and len(merged.sources) > max_records:  # 分摊后仍可能超限(成员行数不均): 末次统一截断
            del merged.sources[max_records:]  # 原地截尾: 切片删除不另留引用, 上层拿到的就是定长结果
            merged.truncated = True  # 截断必须如实标记: 不标会被当成完整结果报出去
        return merged

    resolved = resolve_catalog(catalog)  # 先归一: 旧别名在路径表里没有条目, 不归一会取不到路径
    path = CATALOG_PATHS[resolved]  # 路径查表得到: 客户端不认 URL 拼接规则
    constraints: list[ColumnConstraint] = []  # 显式建空列表: 波段约束要往里追加, 不用 None 占位
    if band:  # 只有给了波段才加列约束: 不限时多一个键可能被站点误解
        # 波段 → 真实列名: 经协议层显式映射表转换; 按 f"{band}psf" 一类
        # 模式猜出的列名星表根本不发布 (非 ps1 锥搜约束幻影列 → 返回 0 行,
        # 而不是过滤请求的波段)。
        constraints.append(ColumnConstraint(  # 追加而非覆盖: 表单里可能还有调用方给的其它约束
            name=magnitude_column(resolved, band),  # 波段经协议层映射成真实列名: 猜列名星表根本不发布
            constraint="notequal",  # 用不等于空来表达有值: 星表没有按波段取子集的算子
            value="null",  # 空值哨兵: 服务端对空值的不等判断等价于滤掉无值行
        ))
    # Q-51: 入参校验接线 (负 RA/0 半径/超限半径在入口即拒)。src.scripts 已
    # 改 PEP 562 惰性导出, 模块顶部导入不再形成环。
    ra, dec = validate_coordinate(ra, dec)  # 入口即拒非法坐标: 星表侧只会回一句查无此项, 越晚暴露越难归因
    radius_arcsec = validate_search_radius(radius_arcsec)  # 半径同在入口校验: 负半径与超限半径会静默返空集
    form = client._build_form(  # 统一走表单生成: 键集权威在协议层, 本方法不自拼
        resolved, constraints, max_records,  # 位置传参: 表名用归一后的 id, 约束带上波段项
        ra=ra, dec=dec, radius_arcsec=radius_arcsec,  # 传归一后的几何量: 校验可能改过值, 旧值不能再用
        columns=columns, sort=sort, order=order, nearest_only=nearest_only,  # 四个可选键同传: 与另三个查询方法同构, 少传即少能力
    )
    return client._execute_query(path, form, max_rows=max_records, page_size=page_size)


def crossmatch_batch(
    client,                                                                                         # 客户端: 批量匹配复用同一会话与限流
    ra_list: list[float],                                                                            # RA 列表(度): 与 Dec 列表按位配对, 长度必须相等
    dec_list: list[float],                                                                           # Dec 列表(度): 长度不等时宁可判失败也不截断配对
    catalog: str = "ps1",                                                                            # 星表 id: 一次 POST 只打一张表
    radius_arcsec: float = 3.0,                                                                      # 默认三角秒: 交叉匹配按此半径筛同一天区
    columns: Optional[list[str]] = None,                                                             # 可选列投影: 回显列只在 csv 形态稳定出现
    nearest_only: bool = True,                                                                       # 默认只要最近邻: 批量匹配的常规诉求
    max_rows: int = 50000,                                                                           # 取回上限: 覆盖全部输入点的期望返回量
    page_size: int = 1000,                                                                           # 每页行数: 大批量时页数决定总往返次数
) -> BestQueryResult:
    """服务端 proximity 批量交叉匹配 (P0-1, 公开缝)。

    一次 POST 携带全部坐标 (``ra,dec,radius`` 多行 textarea,
    ``pos.type=proximity``); 回包在 ``inputobjs_*`` 列回显输入行与角距。
    替代逐个坐标锥搜: 网络往返从 N 次降为 1 次。
    """
    if not ra_list or not dec_list:  # 空坐标表直接判失败: 不为一个无意义请求去建会话
        # 空坐标表: 无意义请求, 直接判失败而不是 POST 一个空表单
        return BestQueryResult(success=False, error="Empty coordinate list")
    if len(ra_list) != len(dec_list):  # 长度不一致即失败: 静默 zip 截断会让配对错位
        # RA/Dec 长度不一致: 配对会错位, 宁可判失败也不静默 zip 截断
        return BestQueryResult(success=False, error="RA/Dec list length mismatch")
    resolved = resolve_catalog(catalog)  # 先归一再查表: 旧别名在路径表里没有条目
    form = client._build_form(  # 统一走表单生成: proximity 的键位在协议层一处
        # 约束列表传空 []: proximity 路径的"约束"就是坐标表本身,
        # 再叠列约束会与 pos 键在服务端互相覆盖。
        resolved, [], max_rows,  # 约束传空列表: 这条路径的约束就是坐标表本身, 叠列约束会互相覆盖
        # 线格式由协议层生成 (radec_text 归属权威层), 本方法不拼串。
        radec_text=proximity_radec_text(ra_list, dec_list, radius_arcsec),  # 坐标块线格式由协议层生成: 客户端不拼串, 免得与服务端解析漂移
        # 默认半径同时作每行半径: 服务端对没带 radius 的行套用此值。
        default_radius_arcsec=radius_arcsec,  # 同时作逐行默认半径: 服务端对没带半径的行套用此值
        nearest_only=nearest_only,  # 最近邻开关: 与逐行半径一起进表单, 拆开传必漏一半
        columns=columns,  # 列投影: 不给则按该表完整列, 回显列会自动附带
    )
    # 格式硬编码 csv: proximity 回包需逐行解析成 BestSource,
    # 且 inputobjs_* 回显列只在 csv 形态稳定出现。
    return client._execute_query(
        CATALOG_PATHS[resolved], form, "csv", max_rows, page_size,  # 位置传参: 格式硬编码 csv, 回显列只在 csv 形态稳定出现
    )
