"""src.download_precise — 精准下载对应数据 (source_id 列表)。

能力边界: 给定 source_id 列表, 以 ``{table}.source_id`` 的 ``in`` 约束
(站点表单 textarea 形态) 只取这些行; 支持列投影 (showcol); 结果行数回核
(0 行/超量都走 hook ask, 不静默)。边界: 单会话 in 查询, ID 数超
``MAX_IDS_PER_QUERY`` 走 hook ask (建议改 proximity 上传或分批); 不覆写
download_manager 的后台/并行/进度/hook 机制 — 经它接线执行。
白盒锚点: references/ALGORITHM-SPEC.md §2 (download_precise 锚点)。

站点协议依据 (实测): 表单每列 operation 支持
``equal/notequal/less/lessequal/grater/greaterequal/between/contains/in``;
``in``/``contains`` 的值走 ``{table}.{col}.textarea`` (见
site-endpoints-and-interactions.md §2.3); 各星表 ID 列响应名为
``{catalog}_source_id`` (protocol.CATALOG_COLUMNS)。
"""

from __future__ import annotations

# 标准库: 日志 / dataclass (任务参数载体) / uuid (自动输出名的唯一后缀) /
# 类型标注 (取消检查回调协议)
import logging  # 标准库: 部分命中的告警出口 (不升级为 hook)
import uuid  # 标准库: 自动输出名的唯一后缀, 保证并行任务不互覆盖
from dataclasses import dataclass, field  # 标准库: 任务参数载体 (field 避免可变默认值)
from typing import Any, Callable, Optional  # 标准库: 注入回调与可缺参数的标注

# 本地 src.*: hook 层 (0 行/超量拦截与 ask 载荷) / 进度追踪器 /
# 数据模型 (列约束) / 协议层 (星表别名/表单构造权威实现)
from src.download_hooks import (
    SEVERE_EMPTY_PRECISE,  # 空结果严重级标签: 回核 0 行时用它作 ask 的类别
    SEVERE_PRECISE_TOO_LARGE,  # 超量严重级标签: ID 数超限时用它, 便于调用方按类分流
    DownloadHooks,  # 钩子层: 拦截、重试与回核出口都在这一层
)
from src.download_progress import ProgressTracker  # 本地: 页级进度, 与其他下载路径共用一份进度文件
from src.models import ColumnConstraint  # 本地: 约束模型, downloader 路径要它而非 dict
from src.protocol import CATALOG_ALIASES, build_query_form  # 协议层: 别名归一与表单构造的权威实现

logger = logging.getLogger(__name__)  # 模块级 logger: 部分命中只 warn, 不经 hooks 升级

# 单次 in 查询的 ID 上限 (站点 textarea 实际承载未经文档化, 取保守值;
# 超出走 hook ask — 建议分批或改用 proximity 坐标上传)
MAX_IDS_PER_QUERY = 1000  # 站点 textarea 承载未经文档化, 取保守值; 超出走 hook ask

DEFAULT_ID_COLUMN = "source_id"  # 兜底裸列名: 星表映射未登记时用它

# 各星表 ID 列 (响应列名口径, live 实证):
# - ps1: 响应列 ps1_source_id 存在但**线上值为空** (锥搜/盒式均实证) ->
#   ps1 精准下载会 0 行, 由 hook empty_precise_result ask (设计内);
# - stripe82: 响应用**裸列名** calibstars_id (非 stripe82_ 前缀), 值非空;
# - 其余星表: {catalog}_source_id (CATALOG_COLUMNS 口径)。
CATALOG_ID_COLUMNS: dict[str, str] = {  # 响应列名实证表: stripe82 是裸列名, 与 CATALOG_COLUMNS 的前缀口径不同
    "ps1": "source_id",
    "stripe82": "calibstars_id",
}
# 线上 ID 值为空的星表 (精准下载不可用, 走 proximity 坐标上传)
EMPTY_ID_CATALOGS = ("ps1",)  # ps1 线上 ID 值为空, 精准下载必然 0 行 (走设计内 ask)


@dataclass
class PreciseDownloadJob:
    """精准下载任务: 按 source_id 列表取精确行。

    用途: 走查询协议的 "in 约束" 路径, 与锥形/文件下载并列的第三种
    任务形态 — 提交的是已知标识列表, 而非空间范围。

    字段口径: ``source_ids`` 用 ``default_factory`` 而非可变默认值,
    否则所有实例共享同一个 list; ``id_column`` 缺省按星表映射解析
    (见 :meth:`resolved_id_column`), ``columns`` 是响应列名而非星表
    原始列名 (如 ``ps1_ra``/``ps1_gpsf``), 二者别混。
    """
    source_ids: list[str] = field(default_factory=list)  # factory 而非可变默认值: 否则所有实例共享同一个 list
    catalog: str = "ps1"
    id_column: str | None = None  # 缺省按星表映射 (CATALOG_ID_COLUMNS)
    columns: Optional[list[str]] = None  # 响应列名 (如 ["ps1_ra","ps1_gpsf"])
    output_format: str = "csv"  # 缺省 CSV: 零依赖, 且能被 parse_csv_rows 直接回核
    output_file: Optional[str] = None  # 缺省交给 precise_output_file 生成带唯一后缀的名字
    max_rows: int = 50000  # 远大于 ID 数: 按 ID 命中时行数天然受 ID 数约束
    page_size: int = 1000  # 与 MAX_IDS_PER_QUERY 同量级: 分页批大小取保守值

    def resolved_id_column(self) -> str:
        """生效 ID 列 (表单裸名): 显式 > 星表映射 > 缺省 source_id。"""
        if self.id_column:  # 显式列名优先: 调用方懂站点方言时可绕过映射
            return _bare_id_column(self.catalog, self.id_column)  # 去表前缀: 表单只认裸列名
        return CATALOG_ID_COLUMNS.get(  # 次选星表映射, 末选缺省裸名
            CATALOG_ALIASES.get(self.catalog, self.catalog),                                       # 星表先归一: 旧别名在标识列映射里没有条目
            DEFAULT_ID_COLUMN)                                                                      # 末选缺省裸名: 映射表没有该表时才用


def normalize_ids(source_ids: Any) -> list[str]:
    """清洗 ID 列表: 去空/去重 (保序)/转str; 非列表输入抛 TypeError。"""
    if source_ids is None:                                                                          # 空值归一成空列表: 省略参数是合法输入
        return []  # None 归一为空列表: 省略参数是合法输入
    if isinstance(source_ids, str):                                                                 # 单串当单元素: 命令行侧常只传一个标识
        source_ids = [source_ids]  # 单串当单元素: CLI 侧常只传一个 ID
    if not isinstance(source_ids, (list, tuple, set)):                                           # 类型错当场抛: 包成列表会把调用方的错误藏起来
        raise TypeError(f"source_ids must be a list of str, got {type(source_ids)!r}")  # 抛而非包成列表: 类型错要当场暴露
    seen: set[str] = set()                                                                         # 去重用的集合: 只判存在, 不决定输出顺序
    out: list[str] = []                                                                             # 输出容器: 顺序即首次出现顺序
    for raw in source_ids:                                                                        # 逐个归一: 标识形态五花八门, 统一在此收口
        if raw is None:
            continue  # None 是调用方错误, 不得变成字符串 "None"
        sid = str(raw).strip()  # 统一 str+strip: 调用方可能给 int 形态的 ID
        if not sid or sid in seen:  # 去空 + 去重且保序: textarea 里重复 ID 无意义
            continue
        seen.add(sid)                                                                               # 登记已见: 集合只用于判重, 不参与输出
        out.append(sid)                                                                           # 追加保序: 去重要保序, 否则同输入不同输出
    return out


def _bare_id_column(catalog: str, id_column: str) -> str:
    """ID 列归一台: 响应名 (ps1_source_id) -> 表单裸名 (source_id)。"""
    resolved = CATALOG_ALIASES.get(catalog, catalog)  # 先过别名: 导航组名要落到真表名
    prefix = f"{resolved}_"  # 前缀按真表名拼: 与 CATALOG_COLUMNS 的响应列名口径一致
    return id_column[len(prefix):] if id_column.startswith(prefix) else id_column  # 已是裸名原样返回: 幂等


def build_precise_form(job: PreciseDownloadJob) -> dict[str, Any]:
    """构造精准下载表单: ``{table}.{id_col}`` in 约束 + 列投影。

    ID 列按星表映射 (ps1 -> ps1.source_id; stripe82 -> stripe82.calibstars_id);
    columns 给响应列名 (ps1_ra) 由 protocol 映射为 showcol 键 (ps1.ra)。

    注意本函数是"裸表单构造器" (给非 hook 路径的调用方用): 空 ID/超量
    在这里抛普通 ValueError; 经 DownloadManager 的执行路径
    (run_precise_download) 对同样两个条件走 hooks.severe ask — 两条
    入口的失败语义不同, 是刻意设计 (前者无用户可决策的上下文)。
    """
    ids = normalize_ids(job.source_ids)                                                            # 先归一标识: 空与重复都要在构造表单前剔掉
    if not ids:                                                                                 # 空 id 列表直接拒: 站点会回一个无意义的空集
        raise ValueError("precise download needs at least one source_id")  # 抛而非返空表单: 空表单会被当成"查无此项"
    if len(ids) > MAX_IDS_PER_QUERY:                                                                # 单次批量上限: 超过就是站点超时而不是快
        # 超量: 站点 textarea 实际承载未经文档化, 超限很可能被服务端
        # 静默截断 — 宁可在此 fail-fast 也不赌
        raise ValueError(  # 裸入口抛普通异常: 此处没有用户可决策的上下文 (见 docstring)
            f"too many source_ids ({len(ids)} > {MAX_IDS_PER_QUERY}); "
            "chunk them or use proximity coordinate upload")
    # 表单构造的权威实现在 protocol 层 (showcol 键映射/表名口径都在那里)
    return build_query_form(  # 权威在协议层: 绕过它键集就会与站点实测表单漂移
        job.catalog,                                                                               # 星表与标识列整份传: 权威表单键集在协议层
        [_in_constraint(job, ids)],                                                                 # 单个包含约束: 一次请求覆盖全部标识
        show_columns=job.columns,
    )


def _in_constraint(job: PreciseDownloadJob,
                   ids: list[str]) -> ColumnConstraint:                                         # 约束对象: 下载器与客户端路径要求值对象而非字典
    """in 约束对象 (downloader/client 路径要求 ColumnConstraint, 非 dict)。"""
    # 值用换行拼接: 站点表单的 in/contains 操作走 textarea 形态,
    # 一行一个 ID (见 site-endpoints-and-interactions.md §2.3)
    return ColumnConstraint(name=job.resolved_id_column(),  # 名字用表单裸名: 带表前缀的响应名会被拒
                            constraint="in", value="\n".join(ids))  # 换行拼接: 站点 in/contains 走 textarea, 一行一个 ID


def precise_output_file(job: PreciseDownloadJob, job_id: str = "") -> str:
    """输出文件名: 显式 output_file 优先, 否则 (星表, ID 数) + 唯一后缀。

    唯一性: 自动名带 job_id (直接调用未给 job_id 时用随机 uuid 后缀) — 旧
    实现唯一性只到 (星表, ID 数) 粒度, 同星表同 ID 数的两个并行任务生成
    同名文件, 经 _save_result 原子写互相 os.replace 覆盖 (用户 silently
    少一份数据)。调用方并行提交时应显式给 job.output_file (人读性最好);
    不显式给时由本函数的唯一后缀保证并行不互覆盖。同一作业 (同一 job_id)
    重复执行拿到同一文件名, resume 原地重跑因此是幂等覆盖而不是堆新文件。
    """
    if job.output_file:                                                                           # 显式名优先: 并行提交时由调用方给可读文件名
        return job.output_file  # 显式名优先: 并行提交时由调用方给可读文件名
    n = len(normalize_ids(job.source_ids))  # 用去重后的个数: 文件名里的数字要与实际请求量一致
    tag = job_id or uuid.uuid4().hex[:8]  # 唯一后缀: 同星表同 ID 数的并行任务不互覆盖
    return f"best_{job.catalog}_precise_{n}ids_{tag}.{job.output_format}"  # 同一 job_id 得同名: resume 是幂等覆盖


def run_precise_download(
    downloader: Any,                                                                              # 下载器: 提供断点链与落盘, 本函数只做编排
    job: PreciseDownloadJob,                                                                        # 任务描述: 标识列表加星表加列投影
    hooks: DownloadHooks,                                                                           # 钩子层: 拦截与重试出口
    tracker: Optional[ProgressTracker] = None,                                                      # 进度追踪可空: 为空则不写页级进度
    task_log: Any = None,                                                                           # 任务日志可空: 为空则不记事件
    job_id: str = "",
    cancel_check: Optional[Callable[[], None]] = None,                                              # 取消检查可空: 缺它则精准任务无法取消
) -> str:
    """执行精准下载 (经 downloader 的 checkpoint 链, 后台/进度/hook 俱享)。

    结果回核: 0 行 -> hook severe ``empty_precise_result`` (ID 或星表用错);
    行数 < 请求 ID 数 -> WARN (部分 ID 不存在, 不阻断)。

    Args:
        downloader: ``BestDownloader`` 实例 (提供 checkpoint 链与落盘)。
        job: 精准下载任务 (source_id 列表 + 星表 + 列投影)。
        hooks: hook 层 (0 行/超量拦截与网络重试)。
        tracker: 可选进度追踪器 (页级进度进同一份进度文件)。
        task_log: 可选任务日志 (query/page 事件)。
        job_id: 作业标识 (checkpoint 键与日志上下文)。
        cancel_check: 可选取消检查回调 (无参; 取消即抛
            ``JobCancelledError``)。由 DownloadManager 注入
            (``lambda: self._check_cancelled(job_id)``) 并挂在每页 observer
            首行 — 与 region/sqlid 的 _on_page 同一形态; 缺失时精准任务
            无法取消 (cancel() 置位后仍跑到自然结束, 终态记 done, 见 B1)。
    """
    ids = normalize_ids(job.source_ids)                                                             # 先归一标识: 两个判据都基于去重后的个数
    if not ids:                                                                                  # 空列表即拒: 调用方错误, 用户决策也解决不了
        # 空 ID 列表是调用方错误 (不是服务端问题), 抛普通 ValueError —
        # 不走 hook ask (ask 用户也解决不了空列表)
        raise ValueError("precise download needs at least one source_id")  # 调用方错误不进 hook 分级
    if len(ids) > MAX_IDS_PER_QUERY:                                                             # 超量是可决策问题: 走钩子问用户, 而不是裸抛
        # 超量是"可决策"问题: 走 hook severe ask (分批 or 改 proximity),
        # 而不是裸 raise — severe 必抛, 下行 AssertionError 不可达
        hooks.severe(  # severe 必抛: 给用户一个可决策的出口
            SEVERE_PRECISE_TOO_LARGE,                                                            # 严重级标签: 调用方按类别分流, 不必解析文案
            f"source_id 数量 {len(ids)} 超过单次 in 查询上限 {MAX_IDS_PER_QUERY}",
            {"n_ids": len(ids), "limit": MAX_IDS_PER_QUERY,
             "catalog": job.catalog},
            job_id=job_id,                                                                     # 作业标识入载荷: 用户决策后要能定位到是哪一个作业
        )
        raise AssertionError("unreachable")  # 走到这里说明 hooks.severe 的必抛契约被改坏

    if task_log is not None:  # 可选日志: 生命周期事件由 DownloadManager 统一记, 这里只记 n_ids
        # 生命周期事件 (submit/start/done) 由 DownloadManager 统一记;
        # 本模块只记精准下载特有事实 (n_ids), 事件名用 query 避免重复。
        task_log.log(job_id, "query", "precise download constraints built",
                     n_ids=len(ids), catalog=job.catalog,                                        # 只记精准特有事实: 生命周期事件由管理器统一记
                     id_column=job.resolved_id_column())                                          # 标识列名一并记: 事后能看出当时用的是哪一列

    output_file = precise_output_file(job, job_id)  # 名在此定: 断点续跑靠同名原地覆盖
    # HTTP 调用点 (协议阶段一+二): download_by_constraints 内部 POST /q
    # 提交 in 约束表单取 sqlid, 再分页拉取; 包 run_network — 网络类失败
    # 指数退避重试, 耗尽才升级 HookInterrupt
    path = hooks.run_network(  # form → sqlid → 分页两阶段都在 lambda 内, 重试只重跑整段
        lambda: downloader.download_by_constraints(                                            # 两阶段都在此闭包: 重试只重跑整段, 不做半段续跑
            constraints=[_in_constraint(job, ids)],                                            # 包含约束按值构造: 标识列表已去重, 不再重复过滤
            catalog=job.catalog,                                                                    # 星表透传: 键集由协议层按星表展开
            output_format=job.output_format,                                                     # 格式声明式透传: 只进溯源, 落盘层才真正转换
            output_file=output_file,                                                                # 输出名透传: 断点续跑靠同名原地覆盖
            max_rows=job.max_rows,                                                                  # 取回上限透传: phase-2 本地封顶, 不改服务端会话 (A2-03)
            page_size=job.page_size,                                                                # 页大小透传: 分页批大小取保守值
            job_id=job_id or None,                                                                 # 作业标识空值归一: 空串交由下游当缺省处理
            resumable=True,                                                                         # 强制走断点: 精准任务按页留断点
            on_page_observer=(_make_observer(tracker, task_log, job_id,                       # 观察者按需装配: 三者皆缺就不装, 省掉每页回调开销
                                             cancel_check)  # 三者皆缺就不装 observer, 省每页回调开销
                              if (tracker or task_log or cancel_check)
                              else None),
        ),
        job_id=job_id,                                                                            # 作业标识入重试上下文: 失败日志要能定位作业
        context={"catalog": job.catalog, "n_ids": len(ids)},                                       # 上下文带星表与标识数: 复核时据此判断规模
    )

    # 行数回核: 0 行/部分命中都在 _verify_row_count 内按 hook 分级处理
    # (0 行 = 强异常信号必须 ask; 部分命中只 warn 不阻断)
    _verify_row_count(path, len(ids), job.catalog, hooks, job_id, task_log)  # 回核出口是 hooks, 调用点无需 try
    return path


def _make_observer(tracker: Optional[ProgressTracker], task_log: Any,
                   job_id: str,                                                                     # 任务日志参数: 与进度、取消三者同批装配
                   cancel_check: Optional[Callable[[], None]] = None):                              # 作业标识: 进页事件与取消上下文
    """组装每页 observer (取消检查 + 进度累加 + 页事件入日志)。

    取消检查放在首行: ``JobCancelledError`` 必须能穿透分页循环向上冒泡到
    DownloadManager._run 的 cancelled 分支 — 漏掉它则 cancel() 只置了个
    无人读取的标志, 精准任务跑到自然结束 (B1); 放在进度/日志之后则取消
    晚一代页才生效。
    """
    def _on_page(page_num: int, page_sources: list) -> None:
        """每页落地后的观察者: 查取消 + 推进分页进度 + 写任务日志。

        Args:
            page_num: 刚完成的页码 (从 1 起)。
            page_sources: 该页解析出的源列表 (只取其行数写日志, 不持有内容)。

        Note:
            取消检查首行且先于进度累加 — 取消即抛, 不先把这一页记进进度
            (与 region/sqlid 的 _on_page 同一形态)。
        """
        if cancel_check is not None:  # 取消检查置首: 取消即抛, 不先把这一页记进进度
            cancel_check()  # 回调由 DownloadManager 注入, 抛 JobCancelledError 上冒
        if tracker is not None:                                                                   # 有进度器才推进: 页级进度与其它路径写同一份
            tracker.advance_pages(1)  # 页级进度: 与其他下载路径写同一份进度文件
        if task_log is not None:                                                                   # 有日志才记页事件: 缺日志时不制造无主事件
            task_log.log(job_id, "page", f"page {page_num}",  # 事件名 page: 与 region/sqlid 同一口径
                         rows=len(page_sources))

    return _on_page


def _verify_row_count(path: str, requested: int, catalog: str,
                      hooks: DownloadHooks, job_id: str, task_log: Any) -> None:
    """落盘行数回核 (0 行 = 精准下载的强异常信号, 必须 ask)。

    Args:
        path: 刚落盘的 CSV 路径。
        requested: 调用方请求的 id 个数 (去重后的期望上限)。
        catalog: 星表 id (决定是否属 EMPTY_ID_CATALOGS 的空 id 特例)。
        hooks: 出口, 不可读/行数异常时在此转 severe ask。
        task_log: 任务日志 (记录回核结论)。
        job_id: 任务标识 (进 ask 载荷与日志)。

    正常返回即"行数对得上"; 异常一律经 :meth:`DownloadHooks.severe`
    抛出而非静默放过 — 精准下载回 0 行几乎总是 id 写错或列名映射错,
    当成成功落盘等于交付一份空文件。

    本方法自身不抛普通异常 (出口是 hooks), 因此调用点无需 try。
    """
    # 延迟导入: 解析器只在回核时需要; 函数内导入让协议表的导入代价
    # 只发生在精准下载路径上
    from src.protocol import parse_csv_rows  # 延迟导入: 协议表只为回核这一处付出代价

    try:
        # 外部 IO 调用点: 读回刚落盘的 CSV 数行; utf-8-sig 与落盘编码
        # 一致 (BOM 由解码器剥离, 不脏数据)
        with open(path, "r", encoding="utf-8-sig") as f:  # utf-8-sig 与落盘编码一致, BOM 由解码器剥离
            rows = parse_csv_rows(f.read())  # 整体读入再解析: 产物是数十行量级
    except OSError as exc:
        # 产物不可读 = 磁盘/权限问题, 按 empty_precise severe ask
        # (用户需要知道"文件没拿到"而不是只看到一个失败)
        hooks.severe(SEVERE_EMPTY_PRECISE, f"精准下载产物不可读: {exc}",  # 不可读也走 ask: 用户得知道"文件没拿到"
                     {"path": path}, job_id=job_id)
        return  # 出口是 hooks: 这里只负责不再往下走
    n = len(rows)  # 实际落盘行数: 与 requested 比对是唯一的完整性判据
    if task_log is not None:                                                                        # 有日志才记核数事实: 回核结论要留痕
        # 行数回核事实 (done 生命周期事件由管理器记, 此处只记核数)
        task_log.log(job_id, "query", "precise result verified",
                     rows=n, requested=requested, path=path)                                      # 三项事实入日志: 实得行数、请求数与产物路径
    if n == 0:                                                                                 # 零行单独判: 精准下载回零行几乎总是标识或列名用错
        # 0 行: ID 列用错/星表用错/该星表线上 ID 为空 (如 ps1) —
        # 请求了 N 个却一个都没回来, 静默返回空文件是最坏的结果, 必须 ask
        hooks.severe(  # 0 行必 ask: 当成成功落盘等于交付一份空文件
            SEVERE_EMPTY_PRECISE,                                                                 # 严重级标签: 当成成功落盘等于交付一份空文件
            f"精准下载 0 行 (请求 {requested} 个 source_id)",
            {"requested": requested, "path": path, "catalog": catalog},
            job_id=job_id,                                                                    # 载荷带请求数与星表: 用户据此判断该改标识还是改星表
        )
    elif n < requested:
        # 部分命中: 部分 ID 在该星表不存在 — 数据本身可解释, 只 warn
        logger.warning("precise download partial: %d/%d ids found",  # 可解释的部分命中只 warn, 不阻断
                       n, requested)
        if task_log is not None:                                                               # 有日志才记告警: 部分命中是可解释事实, 不必升级
            task_log.log(job_id, "query",
                         f"partial result {n}/{requested}", level="warn")


__all__ = [                                                                                        # 公开面白名单: 少列会让星号导入静默丢能力
    "MAX_IDS_PER_QUERY",                                                                      # 单次标识上限: 站点文本域承载未经文档化, 超限即拒
    "PreciseDownloadJob",                                                                           # 任务对象: 精准下载的输入参数集
    "build_precise_form",                                                                           # 裸表单构造器: 给非钩子路径的调用方用
    "normalize_ids",                                                                                # 标识归一: 去空去重转字符串的唯一实现
    "precise_output_file",                                                                         # 输出名生成: 显式名优先, 否则带唯一后缀
    "run_precise_download",                                                                       # 执行入口: 走下载器的断点链, 三套设施俱享
]
