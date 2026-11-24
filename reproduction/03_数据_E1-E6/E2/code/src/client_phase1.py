# -*- coding: utf-8 -*-
"""src.client_phase1 — BestClient 的 phase-1 建会话引擎与两阶段公开缝 (抽离件, budget §3.2 阶段 6)。

能力边界: BEST 两阶段协议的**第一阶段** —— 「把表单 POST 到星表 /q 端点建
服务端 SQL 会话, 从 HTML 回包取出 sqlid」, 以及围绕它的编排与公开缝:
``_submit_query_for_sqlid`` (POST 与 sqlid 抽取的唯一实现) /
``_execute_query`` (阶段 1 + 阶段 2 的一次性编排) / ``submit_phase1``
(只建会话) / ``submit_query`` (公开的阶段 1+2 缝) /
``_error_code_from_message`` (只被 ``_execute_query`` 与 ``submit_query``
调用, 故随之迁出)。抽离缘由:
client.py 拆分前实测 463 净行超 400 预算 (本轮
`ops/audit/count_code_lines.py` 实测已回到 380 净行, 预算问题不复存在),
而本组正是 budget §3.2 自己写下的
拆分触发条件所指的那一组 (「cone_search 或 phase-1 执行组发生结构性修改时
顺势再抽」)。

**与 client_paging 的分工**: phase-2 取数引擎 (分页 GET / CSV 解析 / 源对象
组装 / 断点续传) 与 phase-0 服务端计数在 ``src.client_paging``; 本模块只管
「会话怎么建出来」以及「两阶段怎么串起来」, 阶段 2 一律经
``client._fetch_sqlid_data`` 委派过去 —— 两模块各持一段, 交接点只有那一个
委派调用, 因此「一次查询经历什么」仍可沿 client → client_phase1 →
client_paging 一次读完。

契约 (与 §3.2 阶段 1/2/4/5 同款):
  - 原地委派壳: ``BestClient`` 上五个方法保留同名同签名, 测试对实例方法的
    patch 因此依然生效 (§3.2 实测性质);
  - 失败分流是两条路且**不可合并**: 软错误体与「无 sqlid」是协议层判定,
    返回 ``(None, 错误消息)``; 传输/HTTP 层失败 (requests 异常) 则原异常
    上抛, 不压成字符串 —— 真实状态码只存在于 ``e.response.status_code``,
    压平即丢失 (钩子的分级与 ask 载荷都拿不到)。需信封语义的调用方
    (submit_query / _execute_query) 在自己出口 catch 后还原;
  - 两种失败在出口都被还原成同一条失败信封 (``error_code`` 由消息前缀
    反推), M5 四态判据依赖它区分软/硬失败 —— 逐条未动。
"""
from __future__ import annotations

# 标准库: 日志 (阶段 1 故障须与阶段 2 留在同一日志流) / 回调类型标注 / 可缺参数标注
import logging  # 阶段 1 故障留痕: 只报异常文本看不出打的是哪张表
from typing import Callable, Optional  # 逐页钩子的可调用类型 + 可缺参数

# 第三方: requests (阶段 1 传输/HTTP 失败的异常类型判定)
import requests  # 只为判 RequestException: 阶段 1 失败原异常上抛, 不压成字符串

# 本地: 数据模型 (结果信封/源对象/列约束), 与协议层权威件 (路径表/sqlid
# 解析/软错误判定/错误码/星表归一)
from src.models import BestQueryResult, BestSource, ColumnConstraint
from src.protocol import (
    CATALOG_PATHS,  # 星表 id 到 /q 路径的映射: 客户端不自己拼 URL
    E_INVALID_INPUT,  # 入参非法错误码: 让调用方区分打错了与查无此项
    E_NO_SQLID,  # 阶段 1 未回 sqlid 的错误码: 与软 404 分开计数
    SOFT_404_ERROR_CODE,  # 软 404 错误码: HTTP 200 加软错误体, 只有前缀认得出
    is_soft_error,  # 判 200 携带的软错误体: 状态码白名单看不见它
    parse_sqlid,  # 从 HTML 回包抽 sqlid: 单正则单归一, 与旧客户端共用
    resolve_catalog,  # 星表 id 归一(含旧别名): 导航组名在此被拒
    soft_error_detail,  # 从软错误体取可读 detail: 取不到时调用方要自己兜底
)

logger = logging.getLogger(__name__)  # 库级 logger: 阶段 1 故障必须与阶段 2 留在同一日志流




def _error_code_from_message(message: str) -> Optional[str]:
    """从错误消息前缀恢复稳定错误码; 无契约前缀时返回 None。

    查询失败路径要把带码消息映射回 ``error_code`` 字段, 供调用方按码分支。
    只认前缀匹配: 消息正文里出现其他码字样不算数 (与协议层的生成方式一致),
    普通异常文本一律返回 None, 不猜测。
    """
    text = str(message or "")  # None 也字符串化: 契约允许 error 缺位, 不在此炸
    # 前缀匹配顺序即契约优先级; startswith 保证 "E_NO_SQLID: ..." 这类形态命中
    for code in (SOFT_404_ERROR_CODE, E_NO_SQLID, E_INVALID_INPUT):  # 顺序即优先级: 软 404 先于无 sqlid 与入参非法
        if text.startswith(code):  # 只认前缀: 消息正文里提到别的码不算契约
            return code  # 首个前缀命中即停, 消息正文里的码字样不算契约
    return None


def _submit_query_for_sqlid(
    client,                                                                                         # 客户端: 阶段 1 走本客户端的会话与同一把限流
    catalog_path: str,                                                                             # 星表 /q 路径: 直接取自路径映射表, 不现场拼
    form_data: dict[str, str],                                                                     # 阶段 1 表单键值: 由协议层生成, 客户端不改键
) -> tuple[Optional[str], Optional[str]]:
    """阶段 1: 把表单 POST 到星表 /q 端点并提取 sqlid。

    返回 ``(sqlid, error_msg)``; 失败时 sqlid 为 None。

    契约: 约束随阶段 1 表单进入 sqlid 会话 (live 验证: 极窄的
    ``rpsf between 15.0-15.001`` 表单带或不带阶段 2 filterRules 参数都
    返回 0 行)。不得反推 EasyUI filterRules 作第二约束源: 它把
    ``greaterequal`` 合并进 ``greater``、在 ``contains``/``in`` 取值上
    崩溃, 并且会与表单漂移 (P1-4)。

    **失败分流是两条路, 不可合并**: 软错误体与"无 sqlid"是协议层的
    判定结果, 返回 ``(None, 错误消息)``; 传输/HTTP 层失败 (``requests``
    异常) 则**原异常上抛**, 不压成字符串 —— 真实状态码只存在于异常对象的
    ``.response.status_code`` 上, 压平即丢失, 钩子的分级与 ask 载荷都拿不到。
    需信封语义的调用方 (查询层) 在自己出口 catch 后还原, 见
    :meth:`submit_query` 与 :meth:`_execute_query`。

    Args:
        catalog_path: 星表 /q 路径 (如 ``ps1/q``)
        form_data: 阶段 1 表单键值 (协议层生成)

    Returns:
        ``(sqlid, None)`` 成功; ``(None, error_msg)`` 协议层判定失败

    Raises:
        requests.RequestException: 阶段 1 传输或 HTTP 层失败 (原异常上抛)
    """
    client._rate_limit_wait()                                # POST 同样要节流: 站点限流不区分请求方法
    q_url = f"{client.base_url}/{catalog_path.lstrip('/')}"  # 剥前导斜杠: 传入的 catalog_path 各处写法不统一
    try:
        # 阶段 1 (POST): allow_redirects=True 让服务端把含 sqlid 的结果页
        # 跟随重定向带回; 软错误体与"无 sqlid"仍在下面收敛为 (None, 错误消息),
        # 传输/HTTP 层失败则原异常上抛 (见 except 块)
        resp = client.session.post(q_url, data=form_data, timeout=client.request_timeout, allow_redirects=True)  # 跟随重定向: 结果页靠 302 带回, 不跟随就拿不到 sqlid
        resp.raise_for_status()                                                                         # 显式失败: 4xx 走这条, 200 携带的软错误由下面单独判
    except requests.RequestException as e:
        # 记阶段号+路径: 两阶段故障在同一日志流里必须能分开, 且要能看出打的是哪张表
        logger.error("Phase 1 (POST) to %s failed: %s: %s", catalog_path, type(e).__name__, e)
        # 原异常上抛, **不压成裸字符串**: 状态码挂在 e.response.status_code 上,
        # 压平后下游钩子的状态码抽取恒得 None, 429/5xx 这两类最该分级的错误
        # 永远判不到 (只剩"如实报错", 没有可交给用户决策的 ask 载荷)。
        # 查询层不因此改变契约: submit_query / _execute_query 在各自出口
        # catch 后仍还原成同一条失败信封。
        raise

    # P0-3: 未知路由 / 导航组路径会以 HTTP 200 + 软错误体应答; 若不做这个
    # 检查, 失败只表现为"没拿到 sqlid", 读起来像"查询无结果"而非"路由已死",
    # 两种语义必须分开 (软 404 有专属错误码)。
    if is_soft_error(resp.text):                                            # P0-3: 死路由回 200 加软体, 不判就退化成查无此项
        detail = soft_error_detail(resp.text) or "soft error"               # 兜底文案: 软体没有可读 detail 时也得给调用方一句人话
        logger.error("Phase 1 soft error on %s: %s", catalog_path, detail)  # 记路径: 软 404 几乎都是 catalog_path 拼错或误传组名
        return None, (
            f"{SOFT_404_ERROR_CODE}: BEST answered {catalog_path} with a soft "  # 错误文案带码前缀: 上层按码分流, 裸文案只能靠字符串猜
            f"error body ({detail}); the route does not exist on the service"  # 带软 404 码前缀: 上层靠它把软失败与硬失败分开
        )

    html = resp.text  # 先取文本再解析: 多处复用同一份回包, 避免重复解码
    # sqlid 抽取只在协议层实现一套 (单正则 + 单归一化), BestClient 与 Best
    # 共用, 避免两个客户端再次漂移出不同的解析行为。
    sqlid = parse_sqlid(html)  # 单正则单归一: 与 Best 共用一套, 防止两个客户端解析漂移
    if not sqlid:              # 两类失败在此分流: 软错误是路由死, 这里才是无结果或表单无效
        return None, (
            f"{E_NO_SQLID}: No sqlid found — the query may have returned no "  # 码前缀让上层按类分支, 裸文案只能靠字符串猜
            f"results or the form was invalid"  # 无 sqlid 的两种成因合并成一句: 服务端不区分, 也不该替它猜
        )

    return sqlid, None  # 成功约定错误位留 None, 调用方一次判两个值即可


def _execute_query(
    client,                                                                                         # 客户端: 阶段 2 分页复用同一会话与同一把限流
    catalog_path: str,                                                                             # 路径只进错误信封: 让调用方知道是哪张表出的问题
    form_data: dict[str, str],                                                                     # 阶段 1 已提交的表单键值: 此处不用但签名要留
    output_format: str = "csv",                                                                     # 声明式格式只进溯源: 阶段 2 一律按 csv 拉后本地解析
    max_rows: int = 50000,                                                                          # 取回上限: **phase-2 本地封顶**, 不进阶段 1 表单、不影响服务端会话 (A2-03)
    page_size: int = 1000,                                                                          # 每页行数: 太大则单次回包难中断, 太小则往返过多
    sort: Optional[str] = None,                                                                 # 显式排序列: 2026-07 起必须一路透传到分页 URL, 否则请求无序
    order: str = "asc",                                                                           # 排序方向: 仅在有排序列时携带
    start_page: int = 1,                                                                            # 起始页: 断点续传靠它跳过已取页
    on_page_fetched: Optional[Callable[[int, list[BestSource]], None]] = None,                     # 逐页回调: 进度落盘与取消检查都挂在这一个钩子上
    initial_sources: Optional[list[BestSource]] = None,                                             # 续传已取行: 与起始页成对, 单给其一会让行号错位
) -> BestQueryResult:
    """对 BEST 数据库执行一次完整两阶段查询 (阶段 1 + 阶段 2)。

    阶段 1: POST 表单到星表 /q 端点创建服务端 SQL 会话, 从 HTML 取回 sqlid;
    阶段 2: GET sqlid API, 按会话约束分页拉取 CSV 数据。

    阶段 1 失败时直接返回 ``success=False`` 且 ``error_code`` 按消息
    前缀恢复, 不进入分页; 阶段 2 的失败语义见 :meth:`_fetch_sqlid_data`。

    Args:
        catalog_path: 星表 /q 路径 (如 ``ps1/q``)
        form_data: 阶段 1 表单键值
        output_format: 输出格式说明 (数据始终以 csv 拉取后本地解析)
        max_rows: 最大行数
        page_size: 每页行数
        start_page: 起始页码 (断点续传)
        on_page_fetched: 每页回调 (下载进度/取消检查)
        initial_sources: 续传时已取到的行

    Returns:
        BestQueryResult
    """
    try:
        sqlid, error = client._submit_query_for_sqlid(catalog_path, form_data)  # 阶段 1 一次调用拿全部结论, 此处不重试
    except requests.RequestException as e:
        # 阶段 1 传输/HTTP 失败: 原异常上抛到这一层, 在此还原成失败信封,
        # 保持本方法"永不抛、只回信封"的既有契约 (调用方按 success 分支即可)。
        # 保留 from e: 排障时 traceback 里仍能看到 requests 的原始异常。
        return BestQueryResult(
            success=False,  # 与下面的协议层失败同一失败态: 没有会话就没有可分页的东西
            error=f"E_BACKEND: {e}",  # 带契约码: 传输故障是后端不可达, 调用方按码分支而非匹配文案
            error_code="E_BACKEND",  # 显式给码: 传输层失败不带前缀, 反推必然落空
            query_params={"catalog": catalog_path},  # 溯源只留路径: 失败信封也要能回答查的是哪张表
        )
    # 阶段 1 失败即整体失败: 没有 sqlid 就没有任何可分页的会话,
    # 继续往下走只会拿到空结果并伪装成"查无此项"。
    if error or not sqlid:  # 两条件并判: 只看 sqlid 会丢掉有 id 却带错误的组合
        return BestQueryResult(
            success=False,  # 阶段 1 失败即整体失败: 没有 sqlid 就没有可分页的会话
            error=error or "No sqlid found",  # 兜底文案: 错误位不能为空, 否则调用方无从判断
            # 错误码由消息反推: 软错误体不带独立字段, 只能这样还原
            # (E2 的 M5 四态判据依赖它区分软/硬失败)。
            error_code=_error_code_from_message(error or ""),  # 从消息反推: 软错误体不带独立字段, 只能这样还原
            query_params={"catalog": catalog_path},  # 溯源只留路径: 失败信封也要能回答查的是哪张表
        )
    # 阶段 1 成功即整份委派阶段 2: 两阶段之间没有中间状态要保留,
    # 拆开只会多一处需要同步的分支。
    return client._fetch_sqlid_data(  # 成功即整份委派阶段 2: 两阶段之间没有中间状态要保留
        sqlid=sqlid,  # 已确认存在的会话 id: 阶段 2 全部请求挂在它上面
        output_format=output_format,  # 声明式格式只进溯源: 阶段 2 实际一律按 csv 拉取
        max_rows=max_rows,  # 上限原样下传: 截断判定统一在分页器里做
        page_size=page_size,  # 页大小下传: 与上限分开, 末页自然不足一页
        catalog_path=catalog_path,  # 路径随委派透传: 错误信封要靠它说明是哪个星表
        sort=sort, order=order,  # 排序列透传: 不给这一对, 分页 URL 里就没有 sort, 服务端按无序返回
        start_page=start_page,  # 续传页号: 与已取行成对, 互斥校验放在下游
        on_page_fetched=on_page_fetched,  # 回调不下传会丢进度与取消: 批量查询靠它才可中断
        initial_sources=initial_sources,  # 续传已取行: 计数与截断标记由下游重算, 不在此拼
    )


def submit_phase1(
    client,                                                                                         # 客户端: 阶段 1 走本客户端的会话与同一把限流
    catalog: str,                                                                                   # 星表 id: 导航组名在此抛错, 而不是等一个软 404 回包
    constraints: Optional[list[ColumnConstraint]] = None,                                           # 可选列约束: 已给表单时这份被忽略, 优先级见下面分支
    form_data: Optional[dict[str, str]] = None,                                                    # 预构造表单: 给定则原样 POST, 不做二次加工
    max_rows: int = 50000,                                                                          # 取回上限: 只在需要现构造表单时才有意义
    radec: Optional[tuple[float, float, float]] = None,                                            # 锥搜三元组: 顺序与表单参数一致, 传反不报错只查错天区
) -> tuple[Optional[str], Optional[str]]:
    """只做阶段 1: 构造并 POST 表单, 返回 ``(sqlid, error)``。

    ``radec`` 提供原生服务端锥搜 (``ra, dec, radius_arcsec``)。把阶段 1
    独立可寻址, 下载器就能在翻页前把 sqlid 存成检查点, 而不必私藏第二份
    提交协议副本。

    Raises:
        ValueError: 星表 id 无法解析 (``/q`` 路由只接受 12 个存活 id;
            导航组在此拒绝, 而不是被软 404 应答)
    """
    resolved = resolve_catalog(catalog)  # 归一在前: 路径表只认新拼写的裸 id
    path = CATALOG_PATHS[resolved]  # 取 /q 路径: 阶段 1 与阶段 2 的错误信封共用它
    # form_data 优先: 调用方已自建表单时原样透传 (不二次加工),
    # 只有没给才从 constraints 构造 —— 两条入口因此可能产出不同
    # 键集, 这是为兼容既有调用方刻意保留的口径。
    form = form_data if form_data is not None else client._build_form(  # 用 is not None 判: 空 dict 是调用方的明确意思, 不能当缺省
        resolved, constraints or [], max_rows,  # 位置传参: 表名用归一后的 id, 约束缺省成空列表
        # radec 三元组按位拆给 (ra, dec, radius_arcsec): 元组顺序
        # 与表单参数顺序一致, 传反会让锥搜中心与半径互换而不报错。
        ra=radec[0] if radec else None,  # 三元组首位是 RA: 拆开写才不会与半径互换
        dec=radec[1] if radec else None,  # 第二位是 Dec: 与 RA 同源同进同出
        radius_arcsec=radec[2] if radec else None,  # 第三位是角秒半径: 位置错位会静默查出别的天区
    )
    return client._submit_query_for_sqlid(path, form)


def submit_query(
    client,                                                                                         # 客户端: 阶段 1 与阶段 2 都经本客户端的会话
    catalog: str,                                                                                   # 星表 id: 导航组名会在阶段 1 被拒
    form_data: Optional[dict[str, str]] = None,                                                    # 预构造表单: 给定即原样使用, 键集正确性由调用方自负
    constraints: Optional[list[ColumnConstraint]] = None,                                           # 列约束: 仅在未给表单时参与构造
    max_rows: int = 50000,                                                                          # 取回上限: phase-2 本地封顶, 不写进阶段 1 会话约束 (A2-03)
    output_format: str = "csv",                                                                     # 声明式格式: 只进溯源, 阶段 2 一律按 csv 拉
    page_size: int = 1000,                                                                          # 每页行数: 决定阶段 2 的往返次数
    sort: Optional[str] = None,                                                                 # 显式排序列: 2026-07 起必须透传, 否则分页请求无序
    order: str = "asc",                                                                           # 排序方向: 仅在有排序列时携带
    start_page: int = 1,                                                                            # 起始页: 断点续传入口
    radec: Optional[tuple[float, float, float]] = None,                                            # 可选锥搜三元组: 给了就走服务端原生锥搜
    on_page_fetched: Optional[Callable[[int, list[BestSource]], None]] = None,                     # 逐页回调: 进度与取消的下游唯一钩子
    initial_sources: Optional[list[BestSource]] = None,                                             # 续传已取行: 与起始页必须成对给
) -> BestQueryResult:
    """从星表 id 跑完整两阶段查询 (公开的阶段 1+2 缝)。

    ``form_data`` 给出时原样使用; 否则经协议层从 ``constraints`` 构造
    阶段 1 表单 — 调用方不得私建表单键集 (键集漂移会让锥搜失效)。

    Args:
        catalog: 星表 id (导航组名会被拒绝)
        form_data: 预构造表单 (原样 POST)
        constraints: 列约束列表
        max_rows: 最大行数
        output_format: 输出格式说明
        page_size: 每页行数
        start_page: 起始页码 (断点续传)
        radec: 可选原生锥搜 ``(ra, dec, radius_arcsec)``
        on_page_fetched: 每页回调
        initial_sources: 续传时已取到的行

    Returns:
        BestQueryResult
    """
    try:
        sqlid, error = client.submit_phase1(  # 阶段 1 结果一次拿全: 失败信封在此分流
            catalog, constraints=constraints, form_data=form_data,  # 表单优先: 给了就跳过构造, 与阶段 1 缝同一口径
            max_rows=max_rows, radec=radec,  # 上限与锥搜三元组同传: 两者都只管 phase-2 取回量, 不改服务端会话 (A2-03)
        )
    except requests.RequestException as e:
        # 与 _execute_query 同一失败契约: 传输/HTTP 失败在此还原成失败信封,
        # 本方法对调用方仍是"只回信封不抛"。
        return BestQueryResult(
            success=False,  # 与内部查询同一失败态: 没有会话就没有可分页的东西
            error=f"E_BACKEND: {e}",  # 带契约码: 传输故障归后端不可达, 不必匹配文案
            error_code="E_BACKEND",  # 显式给码: 传输层异常无前缀, 反推必然落空
            query_params={"catalog": catalog},  # 溯源记调用方给的 id: 与内部路径口径略有差异, 保持原样便于对账
        )
    # 与 _execute_query 同一失败契约: 阶段 1 失败直接产出失败信封,
    # 不进阶段 2 (无 sqlid 时分页请求必然空转)。
    if error or not sqlid:  # 与内部查询同一失败契约: 有 id 却带错误的组合也判失败
        return BestQueryResult(
            success=False,  # 阶段 1 失败即整体失败: 没有会话就没有可分页的东西
            error=error or "No sqlid found",  # 兜底文案: 错误位不许留空
            error_code=_error_code_from_message(error or ""),  # 从消息前缀反推码: 软错误体不带独立字段可读
            query_params={"catalog": catalog},  # 溯源记调用方给的 id: 与内部路径口径略有差异, 保持原样便于对账
        )
    return client._fetch_sqlid_data(
        sqlid=sqlid,  # 交给阶段 2 的会话 id: 此处已确认非空
        output_format=output_format,  # 声明式格式下传: 仍只进溯源, 不影响拉取形态
        max_rows=max_rows,  # 上限下传: 截断判定在分页器里统一做
        page_size=page_size,  # 页大小下传: 末页自然不足一页
        # 这里现拼 catalog_path 而非复用 submit_phase1 里的变量:
        # 两条公开缝各自构造路径, 保证 phase1-only 调用不受影响。
        catalog_path=f"{resolve_catalog(catalog)}/q",  # 现拼路径而非复用上一步的变量: 只跑阶段 1 的调用不受影响
        sort=sort, order=order,  # 排序列透传: 2026-07 前这一对**到不了**分页 URL, 请求恒无序
        start_page=start_page,  # 起始页下传: 断点续传从这里生效
        on_page_fetched=on_page_fetched,  # 回调透传: 不下传会同时丢进度与取消
        initial_sources=initial_sources,  # 续传已取行透传: 与起始页必须同时给
    )
