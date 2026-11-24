# -*- coding: utf-8 -*-
"""src.client_paging — BestClient 的 phase-2 取数引擎 (抽离件)。

能力边界: BEST 两阶段协议的**第二阶段** (sqlid → 分页 GET → CSV 解析 → 源
对象) 的全部编排, 以及 phase-0 的服务端计数。取数引擎与"表单构造/公开 seam"
是两个关注点, 单件可达 198 物理行量级 (BestClient 内最长方法的规模), 因此
独立成件: 主链更短, 取数引擎可独立单测
(docs/architecture/file-size-budget.md §3.2)。

契约 (与原类方法逐字等价):
  - 原地委派壳: `BestClient._fetch_sqlid_data` / `BestClient._count` 保留
    同名同签名 (测试对实例方法的 patch 依然生效 — §3.2 实测该性质);
  - self 依赖面只有 `session` / `base_url` / `_rate_limit_wait` / `_count` /
    `request_timeout` (超时也经 client 参数穿透, :97/:179) / `_fetch_sqlid_data`
    (公开缝 `fetch_page` 委派回 client 的那一个调用点, :375), 全部经 client
    参数穿透 — 无隐藏耦合, 不持第二份协议副本;
  - 失败语义不变: 首页网络失败 → 显式 E_BACKEND (不降级空结果); 分页中断 →
    truncated=True; 软错误体 → E_SOFT_404 显式失败; 行级损失 → 跳过的行进
    query_params.skipped_malformed_rows。**来源细分只走成功信封**
    (query_params.skipped_malformed_breakdown =
    malformed_coordinates / truncated_transport_rows, E4 F-E4-01 + A2-01,
    截断来源进 query_params.truncation_reasons): 首页失败与软错误两个失败信封
    只报 skipped_malformed_rows 合计, 不带 breakdown/truncation_reasons ——
    软错误路径可带 pages_fetched>0 提前返回, 此时调用方拿不到来源细分。

白盒锚点: src/client.py (两阶段协议的另一个阶段 + 公开 seam);
src/protocol.py (URL 构造/CSV 解析/软错误判定的权威层 — 本模块只编排不复制)。
"""
from __future__ import annotations

# 标准库: 调用点可调用类型 (观测钩子) / Optional (可能缺失的服务端计数) /
#         logging (传输/半行/软错误三类事实留痕)
import logging  # 三类事实留痕: 传输失败 / 半行跳过 / 软错误
from typing import Callable, Optional  # 观测钩子的可调用类型 + 可能缺失的服务端计数

# 第三方: requests (网络异常类型判定 — 计数端点失败降级的前提)
import requests  # 网络异常类型判定: 计数端点与分页的降级都靠它识别

# 本地: 查询结果载体 (BestQueryResult/BestSource) 与协议层权威件
from src.models import (
    BestQueryResult,  # 结果信封: 分页的最终返回形态
    BestSource,  # 源对象: 每行解析后的载体
    malformed_coordinate_reason,  # 半行判定: 坐标列为空即判结构不完整
)
from src.protocol import (
    E_INVALID_INPUT,  # 入参非法码: 会话号格式错归这一支
    GETCOUNT_PATH,  # 计数端点路径: 客户端不硬编码端点
    SOFT_404_ERROR_CODE,  # 软 404 码: 会话已死与硬失败靠它分开
    build_page_url,  # 分页地址单一构造点: 排序列等参数不复制第二份
    catalog_from_path,  # 路径转星表: 表头列前缀剥离靠它
    count_sqlid,  # 会话号取数字部分: 计数端点只认数字
    is_soft_error,  # 软错误判定: 计数不可信时同样按无计数处理
    normalize_sqlid,  # 会话号归一: 白名单不过就抛, 不静默带病进地址
    parse_count,  # 计数解析: 不可解析时给空值而不是编一个数
    parse_csv_rows,  # 行解析单一实现: 本模块不复制表头判定规则
    resolve_catalog,  # 星表归一(含旧别名): fetch_page 拼续取路径前用它把旧别名收敛
    soft_error_detail,  # 软错误细节: 取不到时调用方要自己兜底
)

logger = logging.getLogger(__name__)  # 模块级 logger: 调用方按 logger 名过滤或静音这两类事实

# 页面回调抛出的控制流异常 (下载取消) 必须中断分页循环, 而不是被记录后忽略
_CONTROL_FLOW_ERRORS: tuple[type[BaseException], ...] = ()  # 空元组当哨兵: 首次调用才真导入, 打破与 download_manager 的环


def _control_flow_errors() -> tuple[type[BaseException], ...]:
    """惰性收集控制流异常类型 (本模块的取数引擎专用)。

    ``JobCancelledError`` 定义在 ``src.download_manager``, 而该模块反向依赖
    client (→ client_paging 委派), 顶层导入会成环; 首次调用时才导入并缓存
    到模块级元组。唯一调用点是本模块的观测钩子滤镜。
    """
    global _CONTROL_FLOW_ERRORS                                                                # 控制流异常元组: 用元组形态是为了能随声明变化重算
    if not _CONTROL_FLOW_ERRORS:  # 空元组为假值 → 只有首次进入才付导入代价
        # 延迟导入打破环: download_manager → client → client_paging
        from src.download_manager import JobCancelledError

        _CONTROL_FLOW_ERRORS = (JobCancelledError,)                                            # 只收取消这一种: 控制流信号必须先于普通异常捕获
    return _CONTROL_FLOW_ERRORS  # 供观测钩子的 except 子句逐页调用, 已缓存故无重复导入


def count_sqlid_rows(client, sqlid: str) -> Optional[int]:
    """通过 ``getcount`` 端点取 sqlid 的服务端真实总行数 (P0-2)。

    计数不可用 (请求失败/软错误/回包不可解析) 时返回 None: 调用方回退到
    本地解析行数, 而不是让整个查询失败。官方文档警告*无约束*会话在该
    端点可能超时, 因此取值前已 live 验证可用性 (V-4)。

    Args:
        sqlid: 查询会话 id (``s3839`` 或纯数字)

    Returns:
        服务端总行数; 不可用时返回 None
    """
    try:
        client._rate_limit_wait()  # 计数也占配额: 绕开限流既会被服务端限速, 口径也与分页不一致
        # 阶段 2 计数端点 (GET): getcount 只认数字 id (s3839 → 3839),
        # 回包 {"total": N}; 无约束会话可能超时, 失败按"无计数"降级。
        # P3-2: URL 走协议层端点常量 GETCOUNT_PATH 单点 (客户端不硬编码)
        resp = client.session.get(  # 外部 IO: URL 由协议层端点常量拼出, 客户端不硬编码
            f"{client.base_url}/{GETCOUNT_PATH.format(count=count_sqlid(sqlid))}",
            timeout=client.request_timeout,                                                     # 超时取实例口径 (A2-02): 缺省即协议层常量, 显式配置才生效
        )
        resp.raise_for_status()  # 4xx/5xx 转成 RequestException, 与连接失败走同一条降级路径
        if is_soft_error(resp.text):  # 200 + 软错误体: 计数不可信, 同样按"无计数"处理
            logger.warning("getcount soft error for sqlid %s", sqlid)
            return None  # None 而非 0: 0 会被调用方读成"服务端说共 0 行"
        return parse_count(resp.text)  # 解析委托协议层: 不可解析时由它给 None
    except requests.RequestException as exc:  # 只捕网络类: 编程错误该冒泡, 不被降级掩盖
        # 网络类失败降级为 None: 查询本身还能继续, 不因计数端点故障中断
        logger.warning("getcount for sqlid %s failed: %s", sqlid, exc)
        return None



def fetch_sqlid_data(
    client,                                                                                         # 客户端: 限流时钟与会话都在它身上
    sqlid: str,                                                                                     # 会话号: 阶段一交回的查询会话
    output_format: str = "csv",
    max_rows: int = 50000,                                                                          # 取回上限: 与页大小解耦, 便于分批
    page_size: int = 1000,                                                                        # 页大小: 末页判据靠它, 返回不足一页即到底
    catalog_path: str = "",
    start_page: int = 1,                                                                            # 起始页: 断点续传从这一页继续
    on_page_fetched: Optional[Callable[[int, list[BestSource]], None]] = None,                     # 逐页回调可空: 钩子负责断点落盘与取消注入
    initial_sources: Optional[list[BestSource]] = None,                                         # 历史源可空: 续传基线, 拷贝后不改调用方的列表
) -> BestQueryResult:
    """阶段 2: 从 BEST sqlid API 分页取数 (带会话内约束)。

    使用 CSV 格式 (含真实数据行、无表头行) 并解析为 BestSource 对象。

    失败语义:
      - 网络类错误中断分页, 返回已取部分 (``success=True`` 带
        ``truncated``), 供断点续传;
      - sqlid 会话过期/路由死亡 (HTTP 200 + 软错误 Body) 整笔判失败 —
        软错误页一旦被当 header-only CSV 解析, 调用方就静默拿到
        "成功的空结果", 把服务故障读成"天上没有源";
      - 末行被传输拦腰截断 (半行) 时该行被丢弃, 但丢弃数进
        ``query_params`` 且 ``truncated`` 置真 (A2-01): 丢行对调用方不可见
        的话, 少收的结果会被读成全量。
    """
    try:
        sqlid = normalize_sqlid(sqlid)  # s3839 → 3839 归一: getcount 端点只认数字 id
    except ValueError as e:  # 显式登记的输入错误: 归为 E_INVALID_INPUT 而不是崩栈
        return BestQueryResult(success=False, error=str(e), error_code=E_INVALID_INPUT)  # 显式失败: 不静默返回空结果冒充查询成功

    # P0-2: 分页前先问服务端要真实总数, 结果才能报告服务端 ``total_count``
    # 与 ``truncated`` 标志; 拿本地解析行数当总数的话, 只要 ``max_rows``
    # 截断就在撒谎。
    server_total = client._count(sqlid)  # 分页前先问总数: 否则 max_rows 截断时 total_count 只能撒谎

    all_sources: list[BestSource] = list(initial_sources) if initial_sources else []  # list() 拷贝续传基线, 不改调用方的列表
    page = start_page                                                                               # 页号从起始页起: 偏移翻页靠它自增
    # 本轮**实际取到的页数** (H3-06): 与"末页页号"分开计。旧写法把 pages_fetched
    # 报成循环退出时的 `page`, 于是从第 1 页起跑时碰巧正确, 续传 (起点 >1) 就会
    # 把"实翻 24 页 (3…26)"报成 26 —— 复核人拿 sidecar 对账请求日志必然对不上,
    # 且看不出发生过续传。计数随成功取回逐页自增, 失败/软错误页不计。
    pages_fetched = 0  # 实取页数: sidecar 的 pages_fetched 取它, 不取页号
    total_fetched = len(all_sources)  # 从已取行数起算: 否则续传会再取满 max_rows 行
    # 分页是否被网络故障中断 (供末尾 truncated 判定: 中断即"未取全")
    network_interrupted = False  # 中断标记: 末尾据此把 truncated 置真, 不谎称"已取全"
    # 结构半行 (坐标列存在但空值) 跳过计数 — 进 query_params 供对账 (E4 F-E4-01)
    skipped_malformed = 0  # 显式计数: 半行不是静默丢弃, 调用方要对账丢了多少行
    # 传输半行 (末行被拦腰截断) 丢弃计数 — 与结构半行分开统计: 两者来源不同,
    # 混成一个数就分不清"服务端给的行不完整"与"结构不合法" (A2-01)
    dropped_truncated = 0  # 协议层只发日志的丢弃事实, 必须经它才对调用方可见
    truncation_reasons: list[str] = []  # 截断来源清单: 一个布尔位不该背多种含义

    while total_fetched < max_rows:  # 循环条件只看实取行数: 按估算页数会提前停或超取
        client._rate_limit_wait()  # 每页一次: 放在循环内, 放到循环外等于整轮不节流
        # phase-2 分页 URL 走协议层单一构造点 (P0-1): 构造点按星表**尽量**注入
        # 排序列 —— 无 ORDER BY 的服务端行序不保证稳定, page=N 偏移翻页会静默
        # 重复/丢行 (线上实测集合重叠仅 1/50)。**但这只是尽力而为, 不是保证**
        # (H3-03 实测订正): 服务端只按它认得的列排序, ps1 注入的 ps1_source_id
        # 实测整列为空 → 该注入对 ps1 是空操作, 行序依赖未声明的服务端行为
        # (本轮跨会话/跨中断产物逐字节相同, 但那是观测不是契约)。详见
        # protocol 模块头与 SSOT。约束随 phase-1 表单进入 sqlid 会话 (P1-4: 不要
        # 反推 EasyUI filterRules 二次传一遍, 已 live 证冗余)。
        fetch_url = build_page_url(  # URL 单一构造点: 排序列等参数不在此复制第二份
            client.base_url, sqlid, page, page_size, catalog=catalog_path,                          # 地址逐项传入: 排序列注入在构造点内完成
        )
        try:
            # 阶段 2 分页 GET: 每页一次独立请求; 网络类失败保留已取页并
            # break (断点续传靠 initial_sources/start_page 接管, 不抛异常)
            resp = client.session.get(fetch_url, timeout=client.request_timeout)                        # 每页一次请求: 分页本身就是多次往返, 超时取实例口径 (A2-02)
            resp.raise_for_status()                                                                 # 状态码先判: 错误页正文不得进入解析
        except requests.RequestException as e:
            logger.warning("Page %d fetch failed: %s", page, e)  # 留痕带页号: 中断是用户可见的, 必须能定位断在哪一页
            if total_fetched == 0:  # 首页即失败: 没有已取行可续, 照常 break 会谎称"成功且 0 行"
                # 首页即失败: 没有任何已取行可续。若照常 break, 调用方会
                # 拿到 success=True + 0 行 — 把网络故障读成"天上没源"
                # (E4 RB-24 包装形态 #2; 与 E2 M5 阻断项 ERROR→EMPTY
                # 同源)。此处显式判失败, 错误码取契约登记的 E_BACKEND
                # (contracts/error-codes.contract.yaml; 工具层同码)。
                return BestQueryResult(
                    success=False,                                                           # 首页失败即判失败: 没有已取行可续, 不能谎称零行成功
                    error=(                                                                    # 错误文案写明不是空结果: 排障要能区分故障与无数据
                        f"E_BACKEND: page {page} fetch failed ({e}); no "
                        f"rows retrieved — a network failure is not an "
                        f"empty result"
                    ),
                    error_code="E_BACKEND",
                    total_count=0,                                                               # 总数报零: 没有任何行到手, 报一个假数会误导
                    returned_count=0,
                    sources=[],                                                                     # 源列表为空: 失败信封不带半截数据
                    query_params={                                                                # 溯源整份重建: 页数与半行数都要在, 供对账
                        "catalog": catalog_path,
                        "sqlid": sqlid,
                        "output_format": output_format,
                        "max_rows": max_rows,
                        "pages_fetched": pages_fetched,  # 实取页数, 不是末页页号: 续传起点 >1 时两者不同 (H3-06)
                        "skipped_malformed_rows": skipped_malformed + dropped_truncated,   # 失败信封同样报全量跳过数: 丢了多少行不能因失败就不可见
                        "server_total": server_total,
                    },
                )
            # 已取部分行: 保留断点续传语义 (initial_sources/start_page
            # 可接管), 但必须记"中断" — 末尾据此置 truncated。
            network_interrupted = True  # 先记中断再 break: 末尾 truncated 完全依赖这个标记
            break

        # P0-3: 死亡/过期的 sqlid 会话以 200 + 软错误 Body 应答;
        # parse_csv_rows 会把它读成 header-only CSV, 调用方静默拿到
        # "成功的空结果" — 必须在此显式判失败。
        if is_soft_error(resp.text):  # 200 + 软错误体: 会话已死, 继续翻页毫无意义
            detail = soft_error_detail(resp.text) or "soft error"  # 取不到细节时给占位: 错误文案不该是空串
            logger.error(
                "Phase 2 soft error on sqlid %s page %d: %s", sqlid, page, detail
            )
            return BestQueryResult(
                success=False,                                                                   # 软错误即判失败: 会话已死, 继续翻页毫无意义
                error=(                                                                       # 错误文案带会话与页码: 复核要能定位到哪一页开始不对
                    f"{SOFT_404_ERROR_CODE}: sqlid session {sqlid} answered page "
                    f"{page} with a soft error body ({detail}); the session is "
                    f"dead or expired"
                ),
                error_code=SOFT_404_ERROR_CODE,                                                     # 软 404 码: 上层据此与硬失败分开
                total_count=len(all_sources),                                                       # 总数取已取行数: 服务端此刻已不可信
                returned_count=len(all_sources),
                sources=all_sources,                                                                # 已取行原样回传: 断点续传靠它接管
                query_params={                                                                      # 溯源整份重建: 与首页失败同一套字段
                    "catalog": catalog_path,
                    "sqlid": sqlid,
                    "output_format": output_format,
                    "max_rows": max_rows,
                    "pages_fetched": pages_fetched,  # 实取页数而非页号: 软错误页本身不计入
                    "skipped_malformed_rows": skipped_malformed + dropped_truncated,  # 软错误信封同样报全量跳过数: 丢了多少行不能因失败就不可见
                },
            )

        raw_text = resp.text                                                                 # 回包文本先取出: 下面要判软错误又要解析, 只解一次码
        pages_fetched += 1  # 该页确实取回来了才计数: 失败/软错误页不计入"实翻页数"
        # Q-02/03/04/05: 解析统一委托 protocol.parse_csv_rows (权威协议层):
        # 表头动态判定 (has_header) 消除幻影源; 列名映射消除波段错位;
        # catalog 透传 from_row 剥离前缀; 全包单一表头假设 (BOM 由协议层 lstrip)。
        cat = catalog_from_path(catalog_path) if catalog_path else ""
        page_stats: dict = {}  # 本页解析出参: 半行丢弃数经它才离开协议层 (否则只存在于日志)
        rows = parse_csv_rows(raw_text, catalog=cat, stats=page_stats)  # 解析全委托协议层: 本模块只编排, 不复制表头判定规则
        # A2-01: 传输半行被协议层丢弃后, 调用方必须能对账丢了多少行 ——
        # 缺键只可能来自空回包早退 (本就零数据行), 故按 0 计。
        dropped_truncated += int(page_stats.get("truncated_rows", 0))  # 累加跨页: 每一页都可能拦腰截断一次
        if not rows:                                                                                # 空页即末页: 正常终止信号, 不是错误
            # 空页 = 已到会话末页: 正常终止信号, 不是错误 (不要再翻页)
            break

        page_sources: list[BestSource] = []                                                         # 本页容器: 钩子只看本页, 便于增量落盘
        for row in rows:                                                                            # 逐行组装: 结构半行在下面被显式跳过
            # E4 F-E4-01: 结构半行 (坐标列存在但值为空, 如"有 ra 无 dec")
            # 显式跳过并计数 — pad 成合法源入库的话, 下游按 None 坐标
            # 匹配/去重时静默出错。计数进 query_params 供调用方对账
            # (与传输截断半行 RB-29 的 truncated 语义同族)。
            reason = malformed_coordinate_reason(row, cat)  # 坐标列为空即判半行: pad 成合法源会让下游静默错配
            if reason is not None:                                                                 # 有半行理由才跳: 正常行不该被判结构不完整
                skipped_malformed += 1                                                             # 半行计数累加: 调用方要知道自己丢了多少行
                logger.warning(                                                                   # 告警带原因与原文前缀: 排障要能对上原始回包
                    "Malformed row skipped (%s): %.80s",
                    reason, str(row)[:80],
                )
                continue
            src = BestSource.from_row(row, catalog=cat)                                            # 行转源对象: 列前缀与波段映射在模型层完成
            page_sources.append(src)                                                                # 入本页容器: 钩子据此做增量上报
            all_sources.append(src)                                                                 # 入总容器: 最终结果就是这份累加
            total_fetched += 1  # 只数成功源: 被跳过的半行不占 max_rows 配额
            if total_fetched >= max_rows:                                                           # 触顶即停: 被跳过的半行不占行数配额
                break

        if on_page_fetched:                                                                         # 有钩子才回调: 不可续传时可以整个不给
            try:
                on_page_fetched(page, page_sources)  # 只传本页: 钩子据此做增量落盘与进度上报
            except _control_flow_errors():  # 控制流必须先于普通 Exception 捕获, 否则被下面吞掉
                # 取消等控制流信号必须中断分页循环: 在此吞掉它们的话,
                # 长查询上 Ctrl-C 失效 (下载仍会跑完并覆盖文件)。
                raise  # 原样重抛: 取消信号若被吞, 长查询上 Ctrl-C 就失效了
            except Exception as hook_err:
                # 观测钩子自身故障不应中断数据获取: 记警告后继续翻页
                logger.warning("on_page_fetched hook error on page %d: %s", page, hook_err)

        if len(rows) < page_size:  # 末页判据: 返回行数不足一页即说明没有下一页
            # 末页判据: 返回行数少于页大小即没有下一页
            break  # 正常终止, 与上面的网络中断 break 语义不同 (这里不是故障)
        page += 1  # 页号自增: 偏移翻页靠它, 漏加会死循环在同一页上

    # P0-2: getcount 有答时 ``total_count`` 用服务端值, 否则用诚实的本地
    # 行数; 只要服务端知道本结果之外还有行 (或客户端在无计数情况下停在
    # max_rows), ``truncated`` 即为 True。
    hit_cap = total_fetched >= max_rows                                                           # 触顶标记: 无服务端计数时它是唯一的截断证据
    if server_total is not None:                                                                  # 有服务端计数才用它: 无计数时不能拿它编总数
        total_count = max(server_total, len(all_sources))  # 取大者: 计数可能小于实取 (续传叠加的截断)
        truncated = server_total > len(all_sources)  # 服务端知道还有行 → 显式 truncated, 不谎称完整
    else:
        total_count = len(all_sources)  # 无服务端计数: 报诚实的本地行数, 不编一个总数
        truncated = hit_cap  # 无计数时只有触顶才能说明"没取全"
    if network_interrupted:                                                                    # 网络中断即置截断: 未能确认到达末页就不能说取全了
        # 分页被网络故障中断: 已取部分之外必然还有行 (或至少未能确认
        # 到达末页) — truncated 必须为 True, 否则"已取全"是包装
        # (E4 包装形态 #5; 断点续传的调用方依赖这个标志决定是否续传)。
        truncated = True  # 断点续传的调用方依赖这个标志决定是否续传, 谎成 False 就会漏数据
    if dropped_truncated:                                                                      # 半行丢弃即"没取全": 与触顶截断同级
        # A2-01 (fail-closed): 末行被拦腰截断 = 确实少了一行。服务端计数说
        # 共 N 行、调用方只拿到 N-1, 与 max_rows 截断是同一层的损失, 报成
        # "已取全"就是把数据事故包装成成功。
        truncated = True
    # 截断来源逐条登记: 只在 truncated 为真时登记, 否则"触顶但恰好取全"会被
    # 误报成一次截断。布尔位只说"没取全", 这里说"为什么没取全"。
    if truncated:
        if hit_cap:                                                                            # 客户端主动停在 max_rows
            truncation_reasons.append("max_rows_cap")
        if server_total is not None and server_total > len(all_sources):                      # 服务端明确知道还有行
            truncation_reasons.append("server_total_exceeds_returned")
        if network_interrupted:                                                                # 分页被网络故障中断
            truncation_reasons.append("network_interrupted")
        if dropped_truncated:                                                                  # 传输半行被丢弃 (与触顶是两回事)
            truncation_reasons.append("transport_half_row_dropped")

    return BestQueryResult(
        success=True,  # 能走到这行就算成功: 输入错误/软错误/首页失败已各自提前返回
        total_count=total_count,                                                              # 总数按上面口径: 服务端值优先, 否则诚实的本地行数
        returned_count=len(all_sources),  # 与 total_count 分离: 两者不等就是被截断的证据
        truncated=truncated,                                                                        # 截断位: 调用方据此决定要不要续拉
        sources=all_sources,                                                                        # 源列表即累加容器: 续传基线也在这里
        query_params={                                                                              # 溯源整份重建: 行级损失与截断来源都可对账
            "catalog": catalog_path,
            "sqlid": sqlid,
            "output_format": output_format,
            "max_rows": max_rows,
            "pages_fetched": pages_fetched,  # 本轮实取页数 (H3-06): 续传起点 >1 时它比末页页号小, 报页号会让复核人拿 sidecar 对不上请求日志
            "skipped_malformed_rows": skipped_malformed + dropped_truncated,                            # 跳过行总计: 调用方按 returned + skipped 对账
            "skipped_malformed_breakdown": {                                                             # 细分来源: 混成一个数就分不清是谁丢的行
                "malformed_coordinates": skipped_malformed,                                              # 结构半行: 坐标列存在但值为空
                "truncated_transport_rows": dropped_truncated,                                          # 传输半行: 末行被拦腰截断而丢弃
            },
            "truncation_reasons": truncation_reasons,                                                    # 截断来源清单: 布尔位之外的机器可读依据
            "server_total": server_total,
        },
    )



def fetch_page(
    client,                                                                                         # 客户端: 续取也走同一会话与同一把限流
    sqlid: str,                                                                                     # 已有会话 id: 续取不重新提交表单
    page: int = 1,                                                                                  # 页码从 1 起: 与服务端页序一致, 少一即重取一页
    page_size: int = 1000,                                                                          # 每页行数: 与缺省上限同值, 保证单页取完
    catalog: str = "",                                                                              # 可空: 续取通常不重复给星表, 强制要求会到处补参
    max_rows: Optional[int] = None,                                                                 # 可空上限: 为空时按页大小封顶一页
    on_page_fetched: Optional[Callable[[int, list[BestSource]], None]] = None,                     # 逐页回调: 单页也要回调, 否则进度条不动
    initial_sources: Optional[list[BestSource]] = None,                                             # 续传已取行: 累计计数由下游重算
) -> BestQueryResult:
    """只取一个会话页 (公开的阶段 2 缝)。

    ``max_rows`` 默认为 ``page_size``: agent 要"第 3 页"时拿到的就是
    恰好一页, 而不是整个会话 (旧行为会把全部剩余页拉完)。
    """
    # catalog 缺省时传空路径: fetch_page 是"已有 sqlid 的续取"语义,
    # 调用方通常不重复给出星表, 强制要求会让续传调用点到处补参。
    catalog_path = f"{resolve_catalog(catalog)}/q" if catalog else ""  # 有星表才拼路径: 空串是续取语义的一部分, 不是漏填
    return client._fetch_sqlid_data(
        sqlid,  # 会话 id 传首位: 被委派方按位置参数接住
        # 硬编码 csv: 续取只用于解析成 BestSource, 其它格式无法逐页解析。
        output_format="csv",  # 硬编码 csv: 续取只用于解析成行对象, 其它格式无法逐页解析
        # 缺省封顶一页: None 时用 page_size 而非不限, 防止调用方
        # 漏传 max_rows 把整个会话剩余页全拉完。
        max_rows=max_rows if max_rows is not None else page_size,  # 缺省封顶一页: 防调用方漏传上限把整个会话剩余页拉完
        page_size=page_size,  # 页大小: 与上限同值时恰好取满一页
        catalog_path=catalog_path,  # 路径只为错误信封服务, 空串也可接受
        start_page=page,  # 页码映射到起始页: 续取语义在此完成转换
        on_page_fetched=on_page_fetched,  # 回调透传: 单页调用也要能报进度
        initial_sources=initial_sources,  # 续传已取行透传: 让分页器算准累计计数
    )
