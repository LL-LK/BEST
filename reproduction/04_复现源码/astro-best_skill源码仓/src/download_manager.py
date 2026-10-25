"""src.download_manager — 后台/并行下载管理器 (线程池 + 进度 + hook + 续传)。

能力边界: DownloadManager: 提交即返回 (后台线程执行, 前台对话不阻塞), 多任务
并行 (默认 2 路, 礼貌限速), 每任务独立 checkpoint (页级续传) + progress 文件
(CLI/GUI 同源), hook 分级拦截 (网络类重试, 严重类即拦即 ask), 取消/恢复。
边界: 进程内线程模型 — 进程退出则未完成任务转 checkpoint 续存; 真 OS 级后台由
宿主 (CLI detach/ harness background job) 承载, 进度文件同源不变。
**阻塞口径的不对称**: submit 一律异步即返; resume 对 file/precise 异步, 对
region/sqlid 则在调用线程上同步跑完 (见 :meth:`DownloadManager.resume` 的
「阻塞语义」) —— 并发续传需调用方自己开线程。
白盒锚点: references/ALGORITHM-SPEC.md §2 (download_manager 锚点)。

任务类型 (submit/submit_all 实收四类, 原写三类):
  RegionJob           锥形/矩形天区下载 (download_region)
  SqlidJob            已有会话 id 下载 (download_sqlid)
  FileJob             单文件字节级下载 (Range 断点续传)
  PreciseDownloadJob  精确测光批量下载 (外部定义, _job_kind 单列为 "precise")
"""

from __future__ import annotations

# 标准库: 日志 / 线程原语 (Event 取消标志, Lock 保护注册表) / job_id 随机后缀 /
# 线程池与 Future (后台执行 + 等待结果) / dataclass (任务参数载体) /
# 路径 / 类型标注
import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 本地 src.*: 下载 hook 层 (分级重试/拦截与 ask 载荷) / 精准下载任务与执行器 /
# 进度存储与追踪器 (进度文件协议) / 任务日志 (事件流)
from src.download_hooks import (
    DEFAULT_POLICY,
    DownloadHooks,
    HookBlockedError,
    HookInterrupt,
    HookPolicy,
)
from src.download_precise import PreciseDownloadJob, run_precise_download
from src.download_progress import (
    STATUS_DONE,
    STATUS_QUEUED,
    STATUS_RUNNING,
    TERMINAL_STATUSES,
    ProgressStore,
    ProgressTracker,
)
from src.task_log import TaskLogger

logger = logging.getLogger(__name__)                                                      # 模块级 logger: 作业失败要留痕, 不能只留在返回值里

DEFAULT_MAX_WORKERS = 2  # 礼貌限速 2s/req 下的保守并发 (经用户批准)


@dataclass
class RegionJob:
    """天区下载任务 (锥形)。

    任务描述: 以 (ra, dec, radius_arcsec) 发起锥形检索并分页落盘。

    字段口径: ``radius_arcsec`` 默认 600 角秒 (10 弧分, 覆盖 PS1 典型
    视场); ``max_rows``/``page_size`` 同时决定总页数估算与请求粒度;
    ``bands`` 为 None 表示不收窄波段。``output_file`` 为 None 时由
    :meth:`DownloadManager._run_region` 按坐标生成确定性文件名。
    """
    ra: float                                                                                       # 天区中心 RA
    dec: float                                                                                      # 天区中心 Dec
    radius_arcsec: float = 600.0              # 600 角秒 = 10 弧分, 覆盖 PS1 典型视场
    catalog: str = "ps1"
    output_format: str = "csv"                # BEST 线上只发 csv; 留字段是为了与 sqlid 路径同构
    bands: list[str] | None = None            # None = 不收窄波段, 由服务端返回该表全部测光列
    output_file: str | None = None            # None 时由 _run_region 按坐标生成确定性文件名
    max_rows: int = 50000                     # 行数上限: 同时决定总页数估算与 truncated 标记
    page_size: int = 1000                     # 单次请求行数, 与 max_rows 一起算进度条总页数


@dataclass
class SqlidJob:
    """已有 sqlid 的下载任务。

    任务描述: 跳过 phase-1 表单提交, 直接用调用方已持有的 sqlid 走
    phase-2 分页 — 用于"先查后导"的交互式流程。

    与 :class:`RegionJob` 的差别只有数据入口: 无空间参数, 故产物名
    用 sqlid 而非坐标, 保证同一 sqlid 两次导出可复现同一文件名。
    """
    sqlid: str                                # phase-2 分页凭据: 跳过表单提交, 直接进入分页阶段
    catalog: str = "ps1"
    output_format: str = "csv"                # 与 RegionJob 同构, 便于统一后处理
    output_file: str | None = None            # None 时产物名用 sqlid, 保证同一 sqlid 两次导出同名
    max_rows: int = 50000                     # 与天区任务取同一上限, 两条路径的产物规模才可比
    page_size: int = 1000                     # 同一分页粒度: 让进度条与 checkpoint 键行为一致


@dataclass
class FileJob:
    """单文件字节级下载任务 (Range 断点续传)。

    任务描述: 直接 GET 一个 URL 落盘, 不经查询协议。

    断点续传靠 HTTP Range 头 + 已有字节数, 因此它**不**有
    max_rows/page_size 一类分页参数; ``filename`` 为 None 时由
    downloader 从 URL 末段推断。
    """
    url: str                                  # 直链: 不经查询协议, 断点续传靠 HTTP Range 头
    savedir: str = "./"                       # 相对路径按调用方 CWD 解析; 缺省不新建子目录
    filename: str | None = None               # None 时由 downloader 从 URL 末段推断


class JobCancelledError(Exception):
    """任务被取消 (控制流异常, 不是错误)。

    抛出点: 每页回调 (region/sqlid 的 _on_page, file 的字节级中断)。
    控制流语义: 该异常必须穿透三层 — client_paging.fetch_sqlid_data 的分页
    while 循环 (不按普通异常记录后继续)、download_hooks.run_network 的
    except 分级 (非网络类异常原样 raise, 不包装成 network ask)、最终被
    _run 捕获并把状态转 cancelled。任何一层把它吞掉, 取消都会静默失效
    (任务跑到自然结束)。
    """


class DownloadManager:
    """后台并行下载管理器。

    用法 (agent 前台不阻塞):
        mgr = DownloadManager(client)                 # 或 Best 实例
        job_id = mgr.submit(RegionJob(ra=180, dec=30, radius_arcsec=180))
        ... 继续对话 ...
        rec = mgr.status(job_id)                      # 或读 .progress/<job_id>.json
        if rec.status == "blocked":
            ask(rec.hook)                             # 必须 ask 用户
        path = mgr.result(job_id)                     # done 后取落盘路径
    """

    def __init__(
        self,
        client: Any,
        output_dir: str = "best_data",
        max_workers: int = DEFAULT_MAX_WORKERS,
        progress_dir: str = ".progress",
        checkpoint_dir: str = ".checkpoints",
        policy: HookPolicy | None = None,
        task_log: TaskLogger | None = None,
    ) -> None:
        """构造管理器。

        Args:
            client: BestClient (唯一生产客户端; 按契约注入即可, 不做
                isinstance 兜底与"自动取出 client"这类兼容分支)
            output_dir: 下载产物根目录
            max_workers: 线程池并发数 (默认 2, 礼貌限速下的保守值)
            progress_dir: 进度文件目录 (.progress, CLI/GUI 同源事实源)
            checkpoint_dir: 页级 checkpoint 目录 (与 resume 的键同源)
            policy: hook 分级策略 (None 用 DEFAULT_POLICY)
            task_log: 任务日志 (None 时自建, 目录与 checkpoint 同根的 .logs/)
        """
        self.client = client                                                    # 唯一生产客户端; 只按契约注入, 不查 isinstance
        self.output_dir = Path(output_dir)                                     # 统一成 Path: 后续拼路径不再手工分隔
        self.checkpoint_dir = Path(checkpoint_dir)                             # 页级 checkpoint 根; 显式传参免得落到 CWD
        self.max_workers = max(1, int(max_workers))                            # 下界 1: 传 0 会让 ThreadPoolExecutor 直接抛值错误
        self.hooks = DownloadHooks(policy or DEFAULT_POLICY)                   # 策略缺省走 DEFAULT_POLICY, 本层不复制默认表
        # 进度存储构造即建目录 (外部 IO): .progress 与 .checkpoints 同级的
        # 运行时状态, gitignored
        self.store = ProgressStore(progress_dir)                              # 跨进程同源: CLI/GUI 都只认这一份进度文件
        # 任务日志: 缺省与 checkpoint 同根的 .logs/ (gitignored); 可注入单例
        self.task_log = task_log or TaskLogger(                                # 事件流 append-only, 与进度文件互为两个视图
            log_dir=Path(checkpoint_dir).parent / ".logs")
        # hook 拦截 -> 任务日志 warn 事件 (问题定位第一视图)
        self.hooks.on_interrupt(self._on_hook_interrupt)                      # 观察者: 拦截事件当场留痕, 不依赖任务自己上报
        self._pool = ThreadPoolExecutor(                                       # 线程名带前缀: 栈与日志里能认出是下载 worker
            max_workers=self.max_workers, thread_name_prefix="astro-best-dl")
        self._futures: dict[str, Future] = {}                                 # job_id -> Future; 所有读写都必须过 _lock
        self._cancel_flags: dict[str, threading.Event] = {}                    # 每任务一个 Event: 取消只在页/字节边界检查
        self._trackers: dict[str, ProgressTracker] = {}                       # 进度累加器: 与进度文件同源, 不另设一套计数
        self._results: dict[str, str] = {}                                    # job_id -> 落盘路径; 省掉调用方一次读盘
        self._lock = threading.Lock()                                          # 非重入: 任何持锁路径都不得再次取这把锁
        self._downloader_instance: Any = None                                 # 懒建单例: 每管理器一个, 共享限流时钟

    def _on_hook_interrupt(self, interrupt: HookInterrupt) -> None:
        """hook 拦截观察者: 记任务日志 (level=warn, 供 log problems 视图)。"""
        self.task_log.log(interrupt.job_id or "-", "hook",  # 无主拦截也落 "-", 不让事件丢在空键下
                          f"[{interrupt.kind}] {interrupt.reason}",
                          level="warn", evidence=interrupt.evidence)

    # ---- 提交 (立即返回 job_id) -------------------------------------------

    def submit(self, job: RegionJob | SqlidJob | FileJob
               | PreciseDownloadJob) -> str:
        """提交下载任务到后台线程池, 立即返回 job_id (前台不阻塞)。

        提交即把 queued 进度记录落盘 — 任务尚未开始, 进度文件已可见
        (GUI/CLI 能立刻列出它)。
        """
        return self._spawn(self._new_job_id(job), job, "submit")  # 立即返回: 前台对话不阻塞在网络 IO 上

    def _spawn(self, job_id: str, job: Any, event: str) -> str:
        """把任务挂到后台线程池并返回 job_id (submit/resume 共用的接线单点)。

        Args:
            job_id: 任务标识 (submit 新生成; resume 原地续跑沿用原 id)。
            job: 任务载体 (RegionJob/SqlidJob/FileJob/PreciseDownloadJob)。
            event: 任务日志事件名 ("submit" 首投 / "resume" 原地续跑) —
                同一接线不同事件名, 日志里能区分首次提交与续跑。

        Note:
            resume_spec 在提交即落进进度记录 (不只是 finish 时): 任务中途
            被杀 (记录停在非终结态) 或失败后, resume 仍能凭原参数原地重跑
            — 只在 finish 时写 spec 的话, 失败/中断的任务永远 resume 不了
            (B4)。
        """
        kind = _job_kind(job)                                                            # 短标签: 进度文件名与日志里都靠它分类
        tracker = ProgressTracker(self.store, job_id, kind=kind)                         # 每个 job_id 一个累加器, 生命周期与任务同
        # 提交即落 resume_spec: 上面的 Note — 失败/中断任务的可续传性来源
        tracker.record.result = {"resume_spec": _job_spec(job)}                           # 此时任务还没跑, 失败也能凭它重跑
        # P1-8: 共享字典的写必须过锁 — _spawn 在主线程、_run 在 worker、
        # cancel/resume 可能在第三线程, 无锁复合操作会丢更新 (声明了
        # self._lock 却零使用, 只会制造"已加锁"的错觉)
        with self._lock:                                                                       # 状态变更与取消标志同锁: 否则取消可能撞上状态切换
            self._trackers[job_id] = tracker                                             # 注册表只认 job_id, 跨线程同一份
            # 每任务一个取消标志: 未启动/运行中/已终结三态都由它 + 进度状态区分;
            # resume 原地续跑必须换新标志 — 沿用上次被置位的标志会让重跑在第一
            # 个页边界立刻自我取消
            self._cancel_flags[job_id] = threading.Event()                               # 换新 Event 而非复用: 续跑不能继承旧取消意图
        # 外部 IO 调用点: queued 进度记录原子落盘 (提交即可见)
        self.store.save(tracker.record)                                                  # 先落盘再进池: 提交即可被 list_jobs 看到
        # 外部 IO 调用点: 事件追加进任务日志 (JSONL append-only)
        self.task_log.log(job_id, event, f"{kind} job {event}", kind=kind)                # 事件名区分首投与续跑
        # 后台线程执行: 前台对话不阻塞; worker 内一切异常都由 _run 收敛
        future = self._pool.submit(self._run, job_id, job, tracker)                       # 异常不进 Future, 全部在 _run 内收敛成状态
        with self._lock:                                                                            # 取空闲槽位也要加锁
            self._futures[job_id] = future                                               # 登记 Future: result() 靠它等任务收尾
        logger.info("%s %s job %s (workers=%d)", event, kind, job_id,                     # 并发数进日志: 限速争议时能核对
                    self.max_workers)                                                               # 槽位数由 max_workers 定
        return job_id

    def submit_all(self, jobs: list[RegionJob | SqlidJob | FileJob
                                    | PreciseDownloadJob]) -> list[str]:
        """并行提交多任务 (区域/星表级并行)。

        Args:
            jobs: 任意混合的任务列表; 并发上限由构造期的
                ``max_workers`` 决定, 本方法**不**额外排队。

        Returns:
            job_id 列表, 顺序与入参一一对应 (便于调用方按下标关联结果)。

        提交本身是即返的: 要等结果用 :meth:`result`, 要看中间态用
        :meth:`status` — 本方法不阻塞。
        """
        # 逐个 submit 而非批量进池: 单个任务的参数校验/落盘在 submit
        # 内完成, 批量路径下第 3 个任务失败会连带前两个的 id 丢失。
        return [self.submit(j) for j in jobs]  # 顺序与入参一一对应, 调用方按下标关联结果

    # ---- 查询/控制 ----------------------------------------------------------

    def status(self, job_id: str):
        """读单任务进度记录 (进度文件为权威源, 内存仅缓存 tracker)。

        返回 None 表示该 job_id 从未提交 (或进度文件已被清理)。
        """
        rec = self.store.load(job_id)  # 进度文件是权威源; 内存 tracker 只是写侧缓存
        return rec.to_dict() if rec else None  # None 同时表示"从未提交"与"记录已清理", 故意不细分

    def list_jobs(self) -> list[dict[str, Any]]:
        """列出全部有进度文件的任务记录 (CLI download list 消费)。

        枚举 .progress 目录下所有 *.json (不读线程池内部状态 — 跨进程/
        重启后任务仍在文件里可见), 逐个转 dict。
        """
        return [self.status(j) for j in self.store.list_jobs()]  # 走文件枚举, 跨进程/重启后任务依然可见

    def pending_asks(self) -> list[dict[str, Any]]:
        """所有 blocked 任务的 ask 载荷 (调用方必须逐条 ask 用户)。

        Returns:
            形如 ``{"job_id": ..., "question": ..., "options": [...]}``
            的载荷列表, 供前台逐条向用户征询。

        这是 fail-closed 的读侧出口: 被 hook 拦下的任务**不会**自行
        继续, 前台不消费本方法就会一直挂着 — 所以本方法只报告,
        绝不代替用户做决定。
        """
        asks = []  # 只报告不决策: 被 hook 拦下的任务绝不自行继续 (fail-closed 读侧)
        # 走 store 而非线程池内存态: blocked 可能发生在上一个进程里,
        # 进度文件才是跨重启的权威来源。
        for job_id in self.store.list_jobs():                                            # 重启后先把遗留作业捞回来: 进程内的 future 不会跨重启
            rec = self.store.load(job_id)  # 逐个读盘: blocked 判定只看落盘状态
            # hook 载荷存在才列: 有 blocked 态却无载荷属数据损坏,
            # 此时宁可漏报也不给用户一个空问题。
            if rec and rec.status == "blocked" and rec.hook:
                asks.append({"job_id": job_id, **rec.hook})  # job_id 前置展开: 载荷内的同名字段不得覆盖它
        return asks

    def result(self, job_id: str, timeout: float | None = None) -> str:
        """等待并取落盘路径 (done); 非 done 抛异常 (含 blocked 的 ask 载荷)。

        阻塞语义: 先等 Future (timeout=None 一直等); worker 内异常已被
        _run 收敛成进度状态, 所以真正的判定以进度文件为准。
        """
        future = self._futures.get(job_id)  # 跨进程提交的任务没有 Future, 只能读进度文件
        if future is not None:                                                                      # 拿不到 future 说明作业没在跑
            future.result(timeout=timeout)  # 先等收尾: timeout=None 一直等, 不设隐式超时
        rec = self.store.load(job_id)  # 终态判定以进度文件为准, 不采信 Future 的返回值
        if rec is None:                                                                             # 记录与 future 不一致即异常态
            raise FileNotFoundError(f"no progress record for {job_id}")  # 抛而非返回 None: 免得调用方漏判
        if rec.status == STATUS_DONE and rec.result:  # result 非空才算真有产物, 空 result 视同未完成
            return rec.result.get("path", "")  # 缺 path 落空串: 记录损坏时不编造路径
        if rec.status == "blocked" and rec.hook:  # fail-closed: 拦截态以异常上抛, 不返回空串冒充失败
            # hook 载荷含 raw 原始字段 (to_ask_payload 附带), 无损重建
            raw = rec.hook.get("raw") or {}  # 空 raw 时下面各字段退回问句, 载荷仍可读
            raise HookBlockedError(HookInterrupt(
                kind=raw.get("kind", "unknown"),
                reason=raw.get("reason", rec.hook.get("question", "")),
                evidence=raw.get("evidence", {}),
                options=rec.hook.get("options", []),
                job_id=raw.get("job_id", job_id),
            ))
        raise RuntimeError(f"job {job_id} not done: status={rec.status} "  # queued/running/failed 都走这里
                           f"error={rec.error}")  # 状态与错误一起带上, 调用方无需再读一次进度文件

    def cancel(self, job_id: str) -> bool:
        """取消任务: 未启动直接摘除; 运行中置取消标志 (下一页回调即终止)。

        返回 True = 取消请求已受理 (标志已置); 任务在下一个页边界真正停下,
        状态转 cancelled。已终结任务再取消返回 False。

        控制流: flag.set() 只是"意图" — 真正终止发生在 _on_page 回调里的
        _check_cancelled (抛 JobCancelledError), 因此取消不是瞬时的, 而是
        页边界生效 (文件下载是字节边界生效)。future.cancel() 只能摘除
        还没开始跑的任务; 已在跑的任务必须走标志位这条路径。

        P1-8: 标志/ future/ tracker 的复合查询-修改必须过锁 — 无锁时,
        cancel 与 worker 的 _check_cancelled 并发会读到半更新状态。
        """
        with self._lock:                                                     # 整段持锁: 判位-置位-摘除必须原子
            flag = self._cancel_flags.get(job_id)                            # 查标志与后续置位同锁, 不读到半更新状态
            if flag is None:                                                                        # 取取消标志
                # 从未提交过的 job_id: 无标志可置
                return False                                                 # False = 没有可取消的运行体, 不是取消失败
            rec = self.store.load(job_id)                                    # 终态也要看盘: 跨进程的记录内存里没有
            if rec and rec.status in TERMINAL_STATUSES:                      # done/failed/cancelled 三态都算已终结
                # 已终结 (done/failed/cancelled) 再取消无意义, 也不改写历史状态
                return False                                                 # 不改写历史: 终态记录是既成事实
            flag.set()                                                       # 只表达意图: 真正终止在页/字节边界
            future = self._futures.get(job_id)                               # 已排队未开跑的任务还能被直接摘除
            if future is not None and future.cancel():                       # 摘除成功 = 该任务尚未进入 worker
                # 还没开始执行: 直接从线程池摘除, 不等页边界
                tracker = self._trackers.get(job_id)                         # 摘除后要把状态推到 cancelled, 否则停在 queued
                if tracker:                                                                         # 有进度跟踪器才推进
                    tracker.cancel()                                         # 未开跑即取消: 无产物路径可记
        return True                                                          # True = 取消请求已受理, 终态稍后由页边界兑现

    def resume(self, job_id: str) -> str:
        """从 checkpoint 原地续传 (不重新提交查询, 返回原 job_id)。

        阻塞语义 (**region/sqlid 与 file/precise 两种, 刻意不对称**):
          - region/sqlid: **同步内联** — 本方法在**调用线程**上直接跑完整个
            断点续传 (委派 :meth:`BestDownloader.resume_job`), 返回时作业已
            到终态, 进度文件已写好。与 :meth:`submit` 的"提交即返回"不同:
            一个长任务续传会把调用线程堵住整个下载时长 (实测单任务数秒到
            数分钟), **产品不提供并发续传** —— 要同时续传多个作业, 调用方
            必须自己开线程/进程逐个调本方法 (实测: 调用线程被阻塞 4.3s/6.3s)。
            依据: 续传要走管理器自己的单例 downloader (共享限流时钟) 并把
            结果写回同一条进度记录, 而这两件事都在调用线程上同步完成才谈得
            上"原地"语义; 改成异步会改变"返回即终态"这一既有契约。
          - file/precise: **异步** — 走 :meth:`_spawn` 的 resume 通道进线程池,
            立即返回 job_id, 终态要经 :meth:`result` 等。

        region/sqlid: 页级 checkpoint 以同一 job_id 从断点页继续拉 (std 组
        任务的断点在 ``{job_id}_{member}`` 成员键下, 由组级 checkpoint 重入
        组展开)。续传期逐页回调照常接上 (进度累加 + 取消检查), 故同步阻塞
        期间进度文件是活的, 也仍可被 :meth:`cancel` 中止。

        file/precise: 没有页级 checkpoint, 按 resume_spec 以原参数、**同一
        job_id** 原地重跑 — 旧进度记录被新运行覆盖并推到新终态, 调用方跟踪
        旧 id 就能等到终态。不得改走 ``self.submit(job)`` 生成新 job_id:
        那样旧记录停留在非终结状态, 跟踪旧 id 的调用方永远等不到终态, 重复
        resume 还会无限新建任务 (B4)。

        幂等: 已 done (重跑无意义) 或仍在跑 (原地语义 = 等它自己跑完) 的
        记录, 重复 resume 直接返回原 job_id 而不重跑 — 第二次 resume 返回
        同一 job, 不产生第二个任务。该判定对**全部四类任务**生效
        (region/sqlid/file/precise): region/sqlid 成功后 checkpoint 已删,
        终态检查若排在断点续传之后, 已完成作业会被误报成"没有断点"。

        失败语义: 进度记录缺失或没有 resume_spec 时抛 FileNotFoundError/
        ValueError — 调用方应改走重新提交。region/sqlid 续传本体抛错
        (含续传期间被取消前的网络故障) 时异常照上抛, 但该条进度记录已被
        收口到 failed 终态, 不会停在 running 让人再也续不回来。
        """
        rec = self.store.load(job_id)                                        # 仍以进度文件为权威: 重启后内存注册表是空的
        if rec is None or not rec.result:                                                           # 没有结果就没法判成功
            raise FileNotFoundError(f"no resumable record for {job_id}")      # 抛而非静默新建: 调用方该改走重新提交
        if rec.status in (STATUS_DONE, STATUS_RUNNING, STATUS_QUEUED):        # 幂等判据, 必须排在断点委派之前
            # 已成功 (重跑无意义) 或仍在跑 (等它自己跑完): 直接返回原 id。
            # 必须排在断点续传委派之前 — region/sqlid 作业成功后 checkpoint
            # 已删 (成功即删), 先委派只会从 downloader.resume_job 拿到
            # FileNotFoundError, 把"已完成"误报成"没有断点" (Phase 8 观察项 ⑤:
            # GUI 的 resume 按钮对已完成任务必炸)。
            return job_id                                                   # 第二次 resume 返回同一 job, 不产生第二个任务
        spec = rec.result.get("resume_spec") or {}                           # 提交时落的原参数快照, 续跑按它重建 job
        kind = spec.get("kind")                                              # 决定走页级断点还是原地重跑两条不同的路
        if kind in ("region", "sqlid"):                                      # 有 checkpoint 的两类才谈得上断点
            # 断点续传: downloader 以同一 job_id 读 checkpoint 继续分页
            downloader = self._downloader()                                  # 单例: 续跑与首投共享同一个限流时钟
            tracker = self._trackers.get(job_id)                             # 内存里没有 tracker (跨进程) 时重建
            if tracker is None:
                # 跨进程/重启实例: 内存注册表为空, 但落库进度文件是权威 —— 按它
                # 就地重建收尾器。注意 ProgressTracker 的签名是 (store, job_id),
                # store 在前; 传反了构造期 self.store.save() 会直接 AttributeError。
                # kind 必须一起传: 漏了会回落到默认 "region", 把 sqlid 作业的
                # 记录在续传时改写成 region (GUI 图标与文案随之走错分支)。
                # adopt=rec 是数据保全的关键: 不传它则 tracker 会另起一条
                # done_pages=0 / result=None 的全零记录并在构造期落盘, 把盘上
                # 上一轮的进度与 resume_spec 抹掉 —— 续传若随后失败, 这个作业
                # 就永远续不回来 (fail-open, 详见 ProgressTracker.__init__)。
                tracker = ProgressTracker(self.store, job_id, kind=kind, adopt=rec)
                with self._lock:                                                                                        # 归位与换标志同锁: 与 worker/cancel 的读并发
                    self._trackers[job_id] = tracker                                                                     # 归位: 后续同进程再 resume 走内存那条
                    # resume 原地续跑必须换新标志 — 沿用上次被置位的标志会让重跑在
                    # 第一个页边界立刻自我取消 (与 _spawn 同一理由)
                    self._cancel_flags[job_id] = threading.Event()                                                        # 新 Event: 续跑不继承上次的取消意图
            else:
                with self._lock:                                                                                        # 同上: 内存命中时也要换新标志
                    self._cancel_flags[job_id] = threading.Event()                                                        # 新 Event: 续跑不继承上次的取消意图
            # 推到 running: 续传期间这条记录确实在跑。不推的话它仍停在
            # failed/cancelled 终态, cancel() 会按"已终结"直接返回 False ——
            # 标志连置都置不上, 取消在续传期第二次静默失效。
            tracker.start()
            task_log = self.task_log                                                                                    # 续跑事件与首跑同源: 同一份事件流里能看出这是 resume
            task_log.log(job_id, "resume", f"{kind} job resume (inline, blocking)")                                    # 显式记 inline: region/sqlid 的 resume 不进线程池

            def _on_page(page_num: int, page_sources: list) -> None:
                """续传页回调: 查取消 + 推进页进度 (与 _run_region/_run_sqlid 同一形态)。

                挂在 ``resume_job`` 的 on_page_observer 上: 缺了它, 续传期间既
                不累加进度也没人读取消标志 (二者都只住在这一个回调里)。
                """
                self._check_cancelled(job_id)                                                                           # 每页前查一次: 取消在页边界生效
                tracker.advance_pages(1)                                                                                # 推进页计数: 续传取回第 N 页, done_pages 就该到 N

            try:
                # 同一 job_id: 断点页之后的页继续拉; observer 必须转发 (缺它取消静默失效)
                path = downloader.resume_job(job_id, on_page_observer=_on_page)                                        # 续传入口
            except JobCancelledError:
                # 续传期取消走与 _run 同一的收敛: cancelled 终态, 不记 error
                tracker.cancel()                                                                                        # 取消不是失败: 独立终态
                task_log.log(job_id, "cancelled", "resume cancelled", level="warn")                                     # 留痕: 取消发生在续传窗口内
                return job_id                                                                                           # 返回原 id: 续传被取消也是同一个 job 的终态
            except Exception as exc:  # noqa: BLE001 续传失败要落终态, 但异常仍上抛给调用方
                # 不收口的话记录会永久停在 running — 之后重复 resume 被"仍在跑"
                # 判据挡成空操作, 这个作业再也续不回来。
                tracker.fail(f"{type(exc).__name__}: {exc}")                                                             # 类型+消息入状态
                raise
            # 续跑成果落回同一进度记录: 否则中断后旧记录永远停在
            # running, 调用方跟踪原 id 等不到终态 (B4)
            tracker.finish({"path": path, "resume_spec": spec})                                                          # 推到 done: 跟踪原 id 的调用方这才等得到终态
            with self._lock:                                                                                            # 收尾与状态落库同锁
                self._results[job_id] = path                                                                            # 与 _spawn 同键: 调用方不区分首投与续跑
            return job_id
        # 联合类型在此显式声明: 两条分支各是不同 dataclass, 不声明时 mypy 按首个
        # 赋值把 job 收窄成 FileJob, precise 分支即报不兼容赋值。
        job: FileJob | PreciseDownloadJob
        if kind == "file":
            job = FileJob(**{k: v for k, v in spec.items() if k != "kind"})  # kind 是元信息不是字段, 构造前剔掉
        elif kind == "precise":
            job = PreciseDownloadJob(**{k: v for k, v in spec.items()        # 同上: 按 dataclass 字段从 spec 重建
                                        if k != "kind"})
        else:
            raise ValueError(f"job {job_id} has no resumable spec")          # 未知 kind 宁可拒绝: 猜错会跑出一个假任务
        # file/precise 原地重跑: 同一 job_id, 旧记录被新运行推到新终态
        return self._spawn(job_id, job, "resume")                           # 复用原 id: 跟踪旧 id 即可, 不再新建任务

    def shutdown(self, wait: bool = True) -> None:
        """关闭线程池 (wait=True 等已提交任务跑完)。

        Args:
            wait: True 等已提交任务跑完再返回 (正常退出用);
                False 立即返回, 在途任务被取消。

        不抛异常: 线程池关闭是资源回收, 让它盖掉任务本身的失败
        会把真实错误埋掉。任务终态请先经 :meth:`result` 读取。
        """
        self._pool.shutdown(wait=wait)  # 资源回收: 不抛异常, 免得盖掉任务本身的真实失败

    # ---- 内部: 任务执行 ------------------------------------------------------

    def _new_job_id(self, job: Any) -> str:
        """生成 job_id: ``{kind}_{uuid4 前 12 位}`` (kind 前缀便于人读)。"""
        tag = _job_kind(job)  # kind 前缀: 进度目录里一眼分得出任务类型
        return f"{tag}_{uuid.uuid4().hex[:12]}"  # 截 12 位够短且碰撞可忽略; 全量 uuid 会撑爆文件名

    def _check_cancelled(self, job_id: str) -> None:
        """页边界取消检查: 标志已置即抛 JobCancelledError (穿透分页循环)。

        只在页回调里调用 — 取消因此是页粒度生效, 不会把一页拉一半的连接
        硬生生掐断。P1-8: 取标志与判位过同一把锁, 避免与 cancel() 的
        set() 并发时读到半更新状态。
        """
        with self._lock:                                                    # 取标志与判位同锁, 不与 cancel() 的 set() 交叉
            flag = self._cancel_flags.get(job_id)                            # 缺标志 = 未提交, 当作未取消放行
            if flag is not None and flag.is_set():                                                  # 取消标志置位即提前退出
                raise JobCancelledError(f"job {job_id} cancelled")           # 控制流异常: 须穿透分页循环直到 _run 收敛

    def _run(self, job_id: str, job: Any, tracker: ProgressTracker) -> None:
        """线程池 worker 入口: 任务生命周期 + 异常路由 (不拖垮线程池)。

        三条终止路径: JobCancelledError -> cancelled ( warn 级日志);
        HookBlockedError -> blocked + ask 载荷入进度文件 (fail-closed,
        前台必须 ask 用户); 其余异常 -> failed (记类型+消息)。任何异常
        都在本层消化, 线程池后续任务不受影响。
        """
        tracker.start()                                              # 推到 running: 与 queued 的分界就在这一行
        self.task_log.log(job_id, "start", "task running")           # 起点留痕: 事后能算出任务实际跑了多久
        try:
            self._check_cancelled(job_id)                            # 入 worker 先查一次: 排队期间可能已被取消
            if isinstance(job, RegionJob):                           # 四类任务分派, 每类各自的执行路径与异常语义
                path = self._run_region(job_id, job, tracker)                                       # 天区下载执行体
            elif isinstance(job, SqlidJob):
                path = self._run_sqlid(job_id, job, tracker)                                        # sqlid 下载执行体
            elif isinstance(job, FileJob):
                path = self._run_file(job_id, job, tracker)                                         # 单文件下载执行体
            elif isinstance(job, PreciseDownloadJob):
                path = self._run_precise(job_id, job, tracker)                                      # 精确测光下载执行体
            else:  # pragma: no cover - 防御
                raise TypeError(f"unknown job type: {type(job)!r}")  # 未知类型抛错: 静默跳过会留下永不终结的记录
            tracker.finish({"path": path, "resume_spec": _job_spec(job)})  # 终态同时留 spec, 便于查这次到底跑了什么
            # P1-8: worker 线程写共享结果表也要过锁 (与 cancel/resume 的读并发)
            with self._lock:                                                                        # 落终态时加锁
                self._results[job_id] = path                         # 共享结果表: 与 cancel/resume 的读并发
            self.task_log.log(job_id, "done", "task finished", path=path)  # 产物路径进日志, 免得只靠进度文件找
        except JobCancelledError:
            tracker.cancel()                                         # 取消不是失败: 单独终态, 不记 error
            self.task_log.log(job_id, "cancelled", "task cancelled",
                              level="warn")
        except HookBlockedError as exc:
            # 后台任务被 hook 拦截: 置 blocked + ask 载荷入进度文件 (fail-closed)
            tracker.block(exc.interrupt.to_ask_payload())            # 载荷落盘, 前台 pending_asks 才能读到并问用户
            self.task_log.log(job_id, "blocked",
                              f"[{exc.interrupt.kind}] {exc.interrupt.reason}",
                              level="warn", evidence=exc.interrupt.evidence)
        except Exception as exc:  # noqa: BLE001 任务失败不拖垮线程池
            logger.exception("job %s failed", job_id)                # 带栈: 失败原因不能只剩一行类型名
            tracker.fail(f"{type(exc).__name__}: {exc}")              # 类型+消息入状态, 供 result() 的 RuntimeError 透出
            self.task_log.log(job_id, "failed", f"{type(exc).__name__}: {exc}",
                              level="error")

    def _downloader(self) -> Any:
        """本管理器的共享 downloader (每管理器一个, 复用)。

        页级 checkpoint 必须落在管理器自己的 ``checkpoint_dir``;
        downloader 的缺省值是相对 CWD 的 ``.checkpoints``, 用它会把每一次
        测试和 CLI 运行的工作目录都污染一遍。

        P1-9: 每任务新建 ``BestClient`` 会让限流时钟 (实例级
        ``_last_request_time``/``_rate_limit_lock``) 不跨任务共享 —
        ``max_workers=2`` 时限流被静默降为 ~1.0, 正是该限流要防的上游
        封禁风险; 全部任务改走本单例后, 一个 client 一个时钟。
        P1-8: check-then-act 过锁, 两个 worker 竞争首建时不会各建一个。
        """
        with self._lock:                                                    # check-then-act 同锁: 两个 worker 不会各建一个
            if self._downloader_instance is None:                          # 懒建: 构造期不碰 IO, 首个任务才付出代价
                self._downloader_instance = self._make_downloader(None)     # 一个管理器一个 downloader = 一个限流时钟
            return self._downloader_instance                                # checkpoint_dir 由本管理器指定, 不落 CWD

    def _make_downloader(self, job: Any) -> Any:
        """造下载器 (BestDownloader 消费客户端契约: cone_search/fetch_page)。"""
        # 延迟导入 (打破导入环): src.downloader 在需要取 JobCancelledError 时
        # 会反向 import 本模块 (src.download_manager) — 模块级双向 import
        # 会循环; 放函数内后导入图保持单向, 环在运行时才按需闭合
        from src.downloader import BestDownloader

        # P1 合并: pybest 单类包装的 unwrap 分支随双副本删除移除 — 客户端
        # 契约 (cone_search/fetch_page 等) 由 BestDownloader 消费, 与
        # ToolBox 同一纪律: 不查 isinstance, 契约一致的替身按契约注入
        return BestDownloader(                                              # 只认客户端契约, 不做双副本 unwrap 分支
            self.client,                                                                            # 下载器按作业构造: 输出目录随作业走
            output_dir=str(self.output_dir),                                                        # 路径在此归一
            checkpoint_dir=str(self.checkpoint_dir),                       # 显式传参: downloader 缺省会落到 CWD 的 .checkpoints
        )

    def _phase1_session_recorded(self, job_id: str) -> bool:
        """重试护栏判据: 本作业的断点里是否已记下 phase-1 建好的 sqlid 会话。

        存在的理由 (铁律 7a): ``_run_region`` 的重试闭包**含 POST /q 建会话**。
        闭包整体重发时若会话尚未落断点, 服务端就会多出一个 sqlid 会话 ——
        前一个没人再引用即成孤儿, 泄漏服务端查询配额。断点是唯一能证明
        "POST 已成功、且会话 id 已在我方手上"的凭据: 有它则重入只会走
        phase-2 分页 (纯 GET, 幂等, 退避重试安全), 没有它则一律不重发。

        Args:
            job_id: 任务标识; 单表作业的断点键就是它本身。

        Returns:
            True = 会话已落断点 (允许重试); False = 没有凭据 (禁止重发)。

        Note:
            导航组 (``catalog="std"``) 的会话记在成员键 ``{job_id}_{成员}``
            下, 组级键只存展开参数, 所以按前缀一并扫成员键。
        """
        ckpt = self._downloader().checkpoint  # 复用管理器那份下载器的断点存储 (同一限流时钟/同一目录)
        state = ckpt.load(job_id) or {}  # 缺失即空状态: 没有凭据就是 False
        if state.get("sqlid"):
            return True
        # 组展开: 成员键带前缀, 组级键本身永远没有 sqlid
        return any((ckpt.load(key) or {}).get("sqlid")                       # 逐个成员断点找会话
                   for key in ckpt.list_jobs() if key.startswith(f"{job_id}_"))

    def _run_region(self, job_id: str, job: RegionJob,
                    tracker: ProgressTracker) -> str:
        """执行天区下载任务 (锥形, 断点路径 + 每页取消检查)。

        Args:
            job_id: 任务标识 (进度文件键 + 取消标志键)。
            job: 天区任务描述。
            tracker: 进度累加器, 页回调里推进。

        Returns:
            落盘产物路径。

        Raises:
            JobCancelledError: 页边界命中取消标志 (由 :meth:`_run` 转
                cancelled 终态, 不上抛给调用方)。
            HookBlockedError: 命中 hook 策略 (转 blocked + ask 载荷)。
        """
        # P1-9: 天区任务走管理器级单例 (共享 BestClient 与限流时钟) — 每任务
        # 新建 BestClient 时, 并发时限流被静默降级, 正是该限流要防的
        # 上游封禁风险; region/sqlid/precise 三条执行路径共用同一理由
        dl = self._downloader()                                            # 与 sqlid/precise 共用同一限流时钟, 不再每任务建 client
        tracker.set_total_pages(max(1, job.max_rows // job.page_size))     # 整除估算总页数; max(1,·) 防 0 页进度条
        # 并行安全: 未指定文件名时按 (星表, 天区, 半径, 格式) 生成确定性唯一名,
        # 避免两个并行任务自动同名 (best_ps1_c2.csv) 互相 os.replace 覆盖。
        output_file = job.output_file or (                                # 坐标进文件名: 同名任务因此不会互相覆盖
            f"best_{job.catalog}_ra{job.ra:.1f}_dec{job.dec:.1f}"
            f"_r{job.radius_arcsec:.0f}arcsec.{job.output_format}"
        )

        def _on_page(page_num: int, page_sources: list) -> None:
            """每页落地后的进度钩子 (区域下载): 查取消 + 推进分页进度。

            Args:
                page_num: 刚完成的页码 (从 1 起; 本实现只用它触发副作用)。
                page_sources: 该页解析出的源列表 (此处不落盘, 由调用方汇总)。

            Note:
                取消检查放在钩子首行: ``JobCancelledError`` 必须能穿透分页循环,
                否则取消指令要等整个下载跑完才生效。
            """
            # 每页: 取消检查 (取消即抛 JobCancelledError 穿透分页循环) + 进度累加
            self._check_cancelled(job_id)                                                  # 每页前查一次取消: 取消必须在页边界生效, 不能等整批跑完
            tracker.advance_pages(1)                                                                # 推进页计数

        # HTTP 调用点 (协议阶段一+二): download_region 内部 POST /q 取 sqlid
        # 再分页拉取; 包一层 hooks.run_network — 网络类失败指数退避重试,
        # 耗尽才升级为 HookInterrupt (blocked)。job_id=job_id 让 checkpoint
        # 键与进度文件同键, resume 才能凭 job_id 找回断点。
        # retry_guard: 闭包里含建会话的 POST, 只有断点已记下 sqlid (即重入
        # 只会走 phase-2 的 GET) 才允许重发; 否则不重试, 如实带状态码 ask。
        # RET504: 直接 return, 不落中间变量
        return self.hooks.run_network(
            lambda: dl.download_region(                                              # 真正的下载动作包在 lambda 里: 钩子要包住"一次可重试的调用"
                ra_center=job.ra, dec_center=job.dec,                                               # 天区中心与半径
                radius_arcsec=job.radius_arcsec, catalog=job.catalog,                               # 半径/星表/波段
                bands=job.bands, output_format=job.output_format,                                   # 输出格式与落盘名
                output_file=output_file, max_rows=job.max_rows,                                     # 行数上限与页大小
                page_size=job.page_size, job_id=job_id, resumable=True,                             # 可续: 断点文件由此派生
                on_page_observer=_on_page,                                                          # 页回调: 断点与进度都靠它
            ),
            job_id=job_id,                                                                          # 作业 id
            context={"catalog": job.catalog, "ra": job.ra, "dec": job.dec},  # context 进证据链: 拦截时能看出是哪片天区
            retry_guard=lambda: self._phase1_session_recorded(job_id),  # 护栏: 没有会话凭据就不重发 POST
        )

    def _run_sqlid(self, job_id: str, job: SqlidJob,
                   tracker: ProgressTracker) -> str:
        """执行已有 sqlid 的下载任务 (断点路径 + 每页取消检查)。

        Args:
            job_id: 任务标识 (进度文件键 + 取消标志键)。
            job: sqlid 任务描述, ``sqlid`` 必填。
            tracker: 进度累加器, 页回调里推进。

        Returns:
            落盘产物路径。异常语义与 :meth:`_run_region` 完全一致,
            两条路径共用 :meth:`_run` 的三分支异常路由。
        """
        # P1-9: sqlid 任务同样走单例 — 与天区任务共用同一个限流时钟,
        # 每任务新建 BestClient 会把 rate_limit 静默降级 (理由见 _run_region)
        dl = self._downloader()                                                                     # 取下载器
        tracker.set_total_pages(max(1, job.max_rows // job.page_size))                 # 总页数按行数与页大小估算 (至少 1, 否则进度条会显示 0/0)
        output_file = job.output_file or (                                                          # 显式给了输出名就用, 否则自动生成
            f"best_sqlid_{job.sqlid}.{job.output_format}")

        def _on_page(page_num: int, page_sources: list) -> None:
            """每页落地后的进度钩子 (sqlid 下载): 查取消 + 推进分页进度。

            Args:
                page_num: 刚完成的页码 (从 1 起)。
                page_sources: 该页解析出的源列表 (此处不落盘, 由调用方汇总)。

            Note:
                与区域下载的 ``_on_page`` 行为一致但数据来源不同 — 这里的页来自
                已取到的 sqlid, 不再发第一次 POST。
            """
            # 每页: 取消检查 (取消即抛 JobCancelledError 穿透分页循环) + 进度累加
            self._check_cancelled(job_id)                                                           # sqlid 路径同样在页边界查取消
            tracker.advance_pages(1)                                                                # 推进页计数

        # HTTP 调用点 (协议阶段二): 按 sqlid 分页拉取; 网络类失败由
        # run_network 指数退避重试, 耗尽才 blocked ask。
        # RET504: 直接 return, 不落中间变量
        return self.hooks.run_network(
            lambda: dl.download_sqlid(                                                              # 包在 lambda 里交给钩子
                sqlid=job.sqlid, catalog=job.catalog,                                               # sqlid 直接取, 不再走第一阶段
                output_format=job.output_format, output_file=output_file,                           # 格式与落盘名
                max_rows=job.max_rows, page_size=job.page_size,                                     # 行数与页大小
                job_id=job_id, resumable=True,                                                      # 可续
                on_page_observer=_on_page,                                                          # 页回调
            ),
            job_id=job_id, context={"sqlid": job.sqlid},
        )

    def _run_precise(self, job_id: str, job: PreciseDownloadJob,
                     tracker: ProgressTracker) -> str:
        """精准下载 (source_id 列表 in 约束); 0 行走 hook ask。"""
        # P1-9: 精准下载同样走单例 — 三类下载任务共享一个限流时钟,
        # 每任务新建 BestClient 会把 rate_limit 静默降级 (理由见 _run_region)
        dl = self._downloader()                                                                     # 取下载器
        tracker.set_total_pages(max(1, job.max_rows // job.page_size))                              # 总页数估算
        # 精准下载复用 downloader 的 checkpoint 链 (in 约束走 phase-1/二),
        # 0 行/超量在 download_precise 内部走 hook ask; 页回调累加进度、
        # 记日志并查取消标志 — cancel_check 与 region/sqlid 的 _on_page
        # 同一形态 (B1 修复前这里不挂取消检查, cancel() 后 precise 任务
        # 仍跑到自然结束, 终态记 done 而非 cancelled)
        return run_precise_download(
            dl, job, hooks=self.hooks, tracker=tracker,                                             # 精确测光走独立的编排层
            task_log=self.task_log, job_id=job_id,                                                  # 任务日志一并带上
            cancel_check=lambda: self._check_cancelled(job_id))                                     # 取消检查也传进去

    def _run_file(self, job_id: str, job: FileJob,
                  tracker: ProgressTracker) -> str:
        """执行单文件字节级下载 (HTTP Range 断点续传 + 字节级取消)。

        Args:
            job_id: 任务标识 (进度文件键 + 取消标志键)。
            job: 单文件任务描述 (URL + 落盘目录/文件名)。
            tracker: 进度累加器, 字节级增量进同一份进度文件。

        Returns:
            落盘产物路径。

        Raises:
            HookBlockedError: 网络类失败经退避重试耗尽 (转 blocked)。
            RuntimeError: 取消与非网络类失败的终态由 :meth:`_run` 统一
                收敛, 本方法只负责把异常路由出去。
        """
        # HTTP 调用点 (文件下载, 协议阶段: GET + Range 断点续传):
        # progress_tracker 让字节进度进同一份进度文件 (CLI/GUI 同源);
        # cancel_event 置位时 download_file 中止写盘并返回 None — 与网络失败
        # 的 None 同形态, 由下面的取消标志判别分流 (B2)。
        # P1 合并: 客户端统一为 BestClient (download_file 自 src.best_export
        # 薄壳委托, 注入本客户端的 _request — 限流/重试/软错误检查同源),
        # 不再需要 pybest 单类兜底构造第二个会话。
        path = self.hooks.run_network(                                                     # 单文件下载同样走钩子 (走的是 net 通道, 要计重试)
            lambda: self.client.download_file(                                                      # 真正的下载调用
                job.url, savedir=job.savedir,                                                       # 保存目录
                filename=job.filename, job_id=job_id,                                               # 文件名与作业 id
                progress_tracker=tracker, cancel_event=self._cancel_flags.get(job_id),              # 进度与取消都接上
            ),
            job_id=job_id, context={"url": job.url[:120]},
        )
        if path is None:                                                 # 取消与网络失败同返回 None, 故必须靠标志位分流
            # 取消与网络失败都返回 None (best_export.download_file 的语义):
            # 标志已置即取消 (JobCancelledError 走 _run 的 cancelled 分支),
            # 否则才是网络/IO 失败 (failed 且带错误信息) — 两者终态与错误
            # 信息因此可区分, 调用方不会把用户主动取消读成下载出错
            if self._cancel_flags.get(job_id) and self._cancel_flags[job_id].is_set():  # 标志已置 = 用户主动取消
                raise JobCancelledError(f"job {job_id} cancelled")       # 走 cancelled 终态, 不记 error
            raise RuntimeError(f"file download returned None: {job.url}")  # 标志未置: 真实失败, URL 进消息便于复现
        return path                                                     # 正常路径: 只有非 None 才到这里


def _job_kind(job: Any) -> str:
    """任务类型 -> 短标签 (PreciseDownloadJob -> precise, 其余去 Job 后缀)。"""
    name = type(job).__name__                                           # 按类名而非 isinstance: 免去四重类型导入
    if name == "PreciseDownloadJob":                                    # 该任务定义在别的模块, 只能按名字特判
        return "precise"
    return name.replace("Job", "").lower()                              # region/sqlid/file 三类共用这条去后缀规则


def _job_spec(job: Any) -> dict[str, Any]:
    """任务 dataclass -> 可 JSON 序列化的 resume spec (存入进度 result)。"""
    out: dict[str, Any] = {"kind": _job_kind(job)}                      # kind 随 spec 一起落盘, resume 靠它选路径
    for k, v in vars(job).items():                                      # dataclass 字段逐个抄: 快照而非引用
        out[k] = list(v) if isinstance(v, tuple) else v                 # tuple 转 list 才能过 json: 不可变序列不可序列化
    return out
