"""src.tap.jobs — SQLite 支撑的 UWS 作业存储与执行。

能力边界: TAP 异步作业 (UWS) 的持久化与有界并发执行: PENDING→QUEUED→EXECUTING
→COMPLETED/ERROR/ABORTED 原子相位迁移 (compare-and-set), 每 principal 的并发/
 pending 配额, 结果文件原子落盘 + SHA-256 校验和 + MAXREC 截断位落库 (结果面靠它
挂 X-TAP-Overflow, 不落库则截断结果被当全集交付); 网关重启把在跑作业收敛为 ERROR。
边界: 只跑本仓 executor (BEST 两阶段协议), 不引入外部队列; SQL 标识符仅来自
本地白名单, 外部值一律绑定参数。
白盒锚点: references/ALGORITHM-SPEC.md §6 (TAP 适配层锚点)。

历史来源: pybest 打包产物 (git 6f00efeb^〔本仓历史已无此对象〕〔本仓历史已无此对象〕) ``pybest/tap/jobs.py`` (git 6f00efeb^〔本仓历史已无此对象〕), 迁入 src/tap/
并改引 src.tap.*。UWS: ivo://ivoa.net/xml/UWS/v1.0 (规范引用, 无 DOI)。

SQLite 支撑的 UWS 作业存储与有界并发执行。
"""
from __future__ import annotations

import hashlib  # 标准库: 结果文件 SHA-256 校验和
import os  # 标准库: 建库所在目录
import sqlite3  # 标准库: 作业表持久化 (零外部数据库依赖)
import threading  # 标准库: 跨线程写库的互斥锁
import uuid  # 标准库: 作业 ID 随机生成
from concurrent.futures import ThreadPoolExecutor  # 标准库: 有界本地工作线程池 (不引外部队列)
from contextlib import contextmanager  # 标准库: _db 助手的上下文管理器装饰器
from datetime import datetime, timezone  # 标准库: UTC 时间戳 (UWS creationTime)
from pathlib import Path  # 标准库: 结果目录/文件路径锚定
from typing import Any  # 标准库: 作业行/更新值的任意类型标注

# 本地导入: 权威列名键集 — 序列化时的兜底列清单 (跨协议层能力边界)
from src.protocol import CATALOG_ALIASES, CATALOG_COLUMNS

# 本地导入: ADQL 解析入口 — 作业执行前先过白名单解析 (跨解析能力边界)
from src.tap.adql import parse_adql

# 本地导入: 执行器 — 作业线程里跑两阶段 BEST 查询 (跨执行能力边界)
from src.tap.executor import TapExecutor

# 本地导入: 序列化 — 结果文件字节的生成 (跨序列化能力边界)
from src.tap.formats import serialize_result


class TapJobError(RuntimeError):
    """UWS 作业操作失败 (找不到作业/相位不允许/删除失败等)。"""


class TapQuotaError(TapJobError):
    """并发或 pending 配额超限; service 层转 HTTP 429。"""


class TapJobStore:
    """持久化 TAP 作业并在有界本地线程池里运行它们 (UWS 状态机宿主)。"""

    ACTIVE_PHASES = ("QUEUED", "EXECUTING")  # 这两态即"活跃": 并发配额计数与重启收敛都按它判

    def __init__(
        self,
        db_path: str,
        output_dir: str,
        executor: TapExecutor,
        *,
        anonymous_concurrency: int = 1,
        authenticated_concurrency: int = 3,
        anonymous_pending: int = 5,
        authenticated_pending: int = 20,
    ) -> None:
        """建存储: 解析库/结果目录路径, 建线程池, 初始化作业表。

        Args:
            db_path: SQLite 库文件路径 (resolve 后锚定, 避免相对路径漂移)。
            output_dir: 结果根目录; 实际落盘在其下 ``tap-results`` 子目录,
                与其他产物隔离。
            executor: 作业线程共用的查询执行器。
            anonymous_concurrency: 匿名 principal 同时在跑 (QUEUED/EXECUTING) 上限。
            authenticated_concurrency: 认证 principal 同时在跑上限。
            anonymous_pending: 匿名 principal 的 PENDING 排队上限。
            authenticated_pending: 认证 principal 的 PENDING 排队上限。

        线程池大小取认证/匿名并发上限的较大值: 同一进程内两种 principal 共享
        池子, 但计数按 principal 分别钳制。
        """
        self.db_path = str(Path(db_path).resolve())  # resolve 锚定: 换工作目录后仍指向同一个库文件
        self.output_dir = Path(output_dir).resolve() / "tap-results"  # 专用子目录: 可整目录清理, 不误伤用户文件
        self.output_dir.mkdir(parents=True, exist_ok=True)  # exist_ok: 重启时目录已在, 建库不该因"已存在"失败
        self.executor = executor                                                          # 执行器由外部注入: 本模块只管作业编排与配额, 不自己建连接
        self.anonymous_concurrency = max(1, int(anonymous_concurrency))    # 配 0 视为 1: 想禁用异步该用 db_path=None, 不是配 0
        self.authenticated_concurrency = max(1, int(authenticated_concurrency))  # 认证并发上限高于匿名: 防匿名洪水占满全局池
        self.anonymous_pending = max(1, int(anonymous_pending))            # 匿名排队深度浅: 逼客户端自己退避而非无限堆积
        self.authenticated_pending = max(1, int(authenticated_pending))    # 认证排队深度深: 换取更快的执行体验
        self._lock = threading.RLock()  # RLock 而非 Lock: _db 临界区里会再调走同锁的方法, Lock 会自死锁
        self._pool = ThreadPoolExecutor(                                                           # 线程池: 并发上限在这里落地, 不用信号量
            max_workers=max(self.anonymous_concurrency, self.authenticated_concurrency),  # 池是进程级共享的, 取小值会卡住配额更高的那类
            thread_name_prefix="astro-best-tap",  # 线程名带前缀: 现场抓栈能一眼分辨 TAP 作业线程
        )
        self._init_db()  # 建表 + 重启收敛在此刻完成: 之后任何 submit 都查得到表

    def _connect(self) -> sqlite3.Connection:
        """开一条 SQLite 连接 (timeout 抗写锁竞争, Row 工厂便于 dict 化)。"""
        conn = sqlite3.connect(self.db_path, timeout=30)  # timeout=30: 并发写库短暂锁库时不抛 "database is locked"
        conn.row_factory = sqlite3.Row  # 上层一律按 dict 消费作业行, 免去到处写 dict(row)
        return conn

    @contextmanager
    def _db(self):
        """锁 + 连接 + 提交 + 关闭的单一入口 (P2-11)。

        不得写成 ``with self._lock, self._connect() as conn:`` ——
        ``sqlite3.Connection.__exit__`` 只提交事务、不关闭连接, 那样每次作业操作
        都建连即弃: 句柄累积, ``database is locked`` 概率随之上升,
        ``close()`` 也没有任何连接可关。这里把"拿锁 -> 开连 -> 用 -> 提交 ->
        关连"收成单点: 成功路径显式 ``commit()`` (``close()`` 对未提交事务是
        回滚, 不是提交), 异常路径直接关闭即回滚, 事务语义与 ``with conn:`` 一致。
        """
        with self._lock:                                                                     # 配额检查与占位必须在同一把锁内: 否则并发下会超卖配额
            conn = self._connect()  # 每次操作即开即关: Connection.__exit__ 只提交不关闭, 会漏句柄
            try:
                yield conn  # 锁在 yield 期间一直持有, 故块内不得做长阻塞 IO
                conn.commit()  # 只在成功路径提交: 半途而废的写不落库
            finally:
                conn.close()  # 关闭即回滚未提交事务: 异常路径靠它撤销

    def _init_db(self) -> None:
        """建作业表 (IF NOT EXISTS) 并把上次遗留的在跑作业收敛为 ERROR。

        重启收敛的理由: 进程退出后没有任何线程会来迁移这些作业的相位, 若不
        主动置 ERROR, 客户端轮询会永远停在 QUEUED/EXECUTING。
        """
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)  # 先建目录再建表: 首次启动时目录可能还不存在
        with self._db() as conn:                                                           # 所有状态读写都走同一个连接工厂: 免得各处自开连接忘了提交
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tap_jobs (
                    id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    authenticated INTEGER NOT NULL DEFAULT 0,
                    query TEXT NOT NULL,
                    output_format TEXT NOT NULL,
                    maxrec INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    error TEXT,
                    result_path TEXT,
                    media_type TEXT,
                    checksum TEXT,
                    size INTEGER,
                    overflow INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)  # IF NOT EXISTS: 每次网关启动都跑这段, 建表必须幂等
            self._add_overflow_column(conn)  # 老库缺列要补: 缺了就静默丢截断信号, 与不落库等价
            conn.execute(  # 重启收敛: 进程退出后没有线程会迁移在跑相位, 不置 ERROR 客户端会永远轮询
                "UPDATE tap_jobs SET phase='ERROR', "
                "error='Gateway restarted while the job was running', updated_at=? "
                "WHERE phase IN ('QUEUED','EXECUTING')",
                (self._now(),),
            )

    @staticmethod
    def _add_overflow_column(conn: sqlite3.Connection) -> None:
        """给缺 ``overflow`` 列的既有作业表补列 (老库建于截断信号落库之前)。

        CREATE TABLE IF NOT EXISTS 只保证表在, 不保证列齐: 老库少了这一列时
        ``get_job`` 返回的行里压根没有溢出位, 结果响应便挂不出
        X-TAP-Overflow —— 截断结果被当全集交付, 与本列不存在同一种故障。
        故启动时按 ``PRAGMA table_info`` 实探一次, 缺则补, 默认 0 表示"未截断"。
        """
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(tap_jobs)")}  # 实探列名: 不靠"改过没有"的猜测
        if "overflow" not in columns:  # 缺列才 ALTER: 列已存在时再补会直接报 duplicate column
            conn.execute("ALTER TABLE tap_jobs ADD COLUMN overflow INTEGER NOT NULL DEFAULT 0")  # 迁移: 存量行按未截断处理

    @staticmethod
    def _now() -> str:
        """当前 UTC 时间戳 (微秒精度, 带 Z 后缀 — UWS creationTime 契约)。"""
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def create_job(
        self,
        query: str,
        output_format: str,
        maxrec: int,
        *,
        owner_key: str = "anonymous",
        authenticated: bool = False,
    ) -> dict[str, Any]:
        """建一个 PENDING 作业 (pending 配额按 principal 钳制)。

        Raises:
            TapQuotaError: 该 principal 的 PENDING 作业数已达上限。

        Returns:
            dict[str, Any]: 新建作业的完整行。
        """
        job_id = uuid.uuid4().hex  # ID 兼作结果文件名与轮询句柄, 故用 uuid4 而不复用计数器
        now = self._now()  # created_at 与 updated_at 同刻: 建单这一刻两者本就相等
        with self._db() as conn:                                                                    # 查在途作业数
            # 配额按 principal 分档: 认证用户额度高于匿名, 防止匿名洪水
            # 占满全局池子把认证用户一起饿死
            pending_limit = self.authenticated_pending if authenticated else self.anonymous_pending  # 已认证与匿名用不同的在途上限: 匿名是未授权流量, 压得更狠
            pending = conn.execute(                                                                 # 数在途
                "SELECT COUNT(*) FROM tap_jobs WHERE owner_key=? AND phase='PENDING'",
                (owner_key,),                                                              # 按归属键统计 (同一 owner 的多作业算一个配额单元)
            ).fetchone()[0]
            if pending >= pending_limit:  # 计数与 INSERT 同锁: 分开做会双双通过检查, 配额形同虚设
                raise TapQuotaError(f"Pending TAP job limit reached ({pending_limit})")  # 抛而非排队: 超配额是调用方节奏问题
            conn.execute(  # phase 硬编码 PENDING: 建单态唯一, 自选初始相位会绕过状态机
                "INSERT INTO tap_jobs "
                "(id,owner_key,authenticated,query,output_format,maxrec,phase,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,'PENDING',?,?)",
                (job_id, owner_key, int(authenticated), query, output_format, int(maxrec), now, now),
            )
        return self.get_job(job_id) or {}  # 回读而非手搓 dict: 权威形态来自库, 免得两处字段漂移

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """按 ID 取一行作业 (dict 化), 不存在返回 None。"""
        with self._db() as conn:                                                                    # 纯读: 相位迁移的唯一写入口是 _transition
            row = conn.execute("SELECT * FROM tap_jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def start_job(self, job_id: str) -> None:
        """把 PENDING 作业排进线程池 (并发配额按 principal 钳制)。

        先在同一把锁内完成"相位必须是 PENDING + 活跃数未超限 + 置 QUEUED",
        再 ``submit``: 顺序反过来的话两个并发请求可能同时通过配额检查, 超卖
        并发额度。

        Raises:
            TapJobError: 作业不存在或相位不是 PENDING。
            TapQuotaError: 该 principal 的活跃作业数已达上限。
        """
        with self._db() as conn:                                                                    # 取作业
            job = conn.execute("SELECT * FROM tap_jobs WHERE id=?", (job_id,)).fetchone()
            if not job:                                                                 # 作业不存在即 None: 调用方据此返回 404 而不是 500
                raise TapJobError("TAP job not found")
            if job["phase"] != "PENDING":  # 相位必须恰为 PENDING: 已被排队的作业再排一次会双跑
                raise TapJobError(f"Cannot run a job in phase {job['phase']}")
            limit = (                                                                               # 并发上限按身份分档
                self.authenticated_concurrency                                                      # 已认证的可放宽
                if job["authenticated"]
                else self.anonymous_concurrency                                                     # 匿名的收紧
            )
            active = conn.execute(  # 活跃口径 QUEUED+EXECUTING: 只数 PENDING 会让实际并发突破上限
                "SELECT COUNT(*) FROM tap_jobs WHERE owner_key=? AND phase IN ('QUEUED','EXECUTING')",
                (job["owner_key"],),
            ).fetchone()[0]
            if active >= limit:                                                                 # 达上限即拒绝: 排队不如早失败, 免得用户等半天
                raise TapQuotaError(f"Concurrent TAP job limit reached ({limit})")  # 抛 429 而非阻塞: 超并发不该被藏成慢响应
            conn.execute(                                                                           # 把作业标为排队态
                "UPDATE tap_jobs SET phase='QUEUED', updated_at=? WHERE id=?",  # 置 QUEUED 与配额检查同锁: 反序会被并发双双通过
                (self._now(), job_id),                                                              # 记入在途
            )
        self._pool.submit(self._run_job, job_id)  # submit 必须在锁外: 作业线程一启动就要抢同一把锁

    def _run_job(self, job_id: str) -> None:
        """工作线程体: QUEUED→EXECUTING→COMPLETED/ERROR/ABORTED 的相位迁移。

        流程: 解析 ADQL → 执行 (带溢出探测) → 序列化 → 结果先写 ``.tmp`` 再
        replace 原子落盘 → 记 SHA-256 与大小并迁移 COMPLETED。任何异常都清理
        半成品文件并把相位迁到 ERROR (错误原文写入 error 列, 客户端可见)。
        若 COMPLETED 迁移本身没抢到 (作业已被并发 abort), 删除刚落的文件,
        不留孤儿产物。
        """
        if not self._transition(  # CAS 门: 抢不到相位 (已被并发 ABORT) 就直接返回, 不覆盖他人决策
            job_id,                                                                                 # 完成态的关键字
            expected_phases={"QUEUED"},
            phase="EXECUTING",
            error=None,                                                                             # 成功时错误为空
        ):
            return
        job = self.get_job(job_id)  # 相位迁移后重读: 执行要用的 maxrec/format 都存在库里
        if not job:                                                                                 # 作业不存在即无事可做
            return
        final_path: Path | None = None  # 先置 None: except 路径靠它判断"是否已落过盘"
        temporary: Path | None = None  # 同理: 不预置就无法清理"写了一半"的 .tmp
        try:
            plan = parse_adql(job["query"])  # 先过白名单解析: SQL 标识符只许来自本地表, 其余走绑定参数
            rows, overflow = self.executor.execute_with_overflow(  # 多取一行探测溢出: 少取就说不清结果被 maxrec 截断
                plan,                                                                               # 执行计划: 解析层产物, 只在本调用内用, 不落库 (tap_jobs 无 plan 列)
                max_rows=job["maxrec"],
            )
            result = serialize_result(  # 列清单兜底: ADQL 未写 SELECT 列时按星表别名回退权威列集
                rows,                                                                               # 行数据落库
                job["output_format"],
                columns=plan.columns or CATALOG_COLUMNS.get(                                    # 列名缺失时回退到该星表的列清单 (先过别名归一)
                    CATALOG_ALIASES.get(plan.catalog, plan.catalog), ()),                           # 别名归一必须在取表之前
                overflow=overflow,                                                                  # 截断标记一并落库
            )
            final_path = self.output_dir / f"{job_id}{result.extension}"  # 带 job_id: 并发作业互不覆盖, 也能反查来源
            temporary = final_path.with_suffix(final_path.suffix + ".tmp")  # 同目录 .tmp: 跨目录 replace 会退化成复制
            temporary.write_bytes(result.body)  # 先写 .tmp: 客户端可能在 COMPLETED 后立刻就来取
            temporary.replace(final_path)  # 原子改名: 读方要么看不到, 要么看到完整文件
            committed = self._transition(  # 校验和取迁移前的 body: 重读多一次 IO, 并发删除下还可能读不到
                job_id,                                                                             # 终态的关键字
                expected_phases={"EXECUTING"},
                phase="COMPLETED",
                error=None,                                                                         # 成功时错误为空
                result_path=str(final_path),                                                        # 结果落盘路径
                media_type=result.media_type,                                                       # 媒体类型
                checksum=hashlib.sha256(result.body).hexdigest(),                                   # 校验和: 供后续人工复核
                size=len(result.body),                                                              # 字节数
                overflow=int(overflow),                                                             # 截断位落库: 结果文件要经"落盘 → 客户端来取"才发出, 位不存就出不了网关
            )
            if not committed:  # 没抢到 = 已被并发 abort: 删掉刚落盘的文件, 不留孤儿结果
                final_path.unlink(missing_ok=True)                                            # 替换失败时把半成品先删: 免得留下半个文件被当成结果
        except Exception as exc:  # 宽捕获: 任何失败都要收敛成 ERROR, 不能让线程静默死
            if temporary is not None:  # 半成品一律清: 留在结果目录的 .tmp 会被下游当合法产物
                temporary.unlink(missing_ok=True)                                                   # 临时文件清理
            if final_path is not None:  # replace 之后也要删: 迁移失败时 final 已落盘
                final_path.unlink(missing_ok=True)                                                  # 正式文件清理
            self._transition(  # 错误原文入 error 列: 客户端在 errorSummary 里直接看到失败原因
                job_id,                                                                             # 失败态的关键字
                expected_phases={"EXECUTING"},
                phase="ERROR",
                error=str(exc),                                                                  # 异常原文入库: 排障靠它, 不能只记 "失败"
            )

    def abort_job(self, job_id: str) -> None:
        """中止尚未终结的作业 (COMPLETED/ERROR 等终相位一律拒绝)。

        Raises:
            TapJobError: 作业不存在、已处终相位, 或迁移没抢到 (相位在检查后
                被并发改写)。
        """
        job = self.get_job(job_id)  # 先读相位再判: 中止是幂等操作, 抢不到相位由 CAS 兜底报错
        if not job:                                                                                 # 查作业
            raise TapJobError("TAP job not found")
        if job["phase"] in {"COMPLETED", "ERROR"}:  # 终态不可中止: 会把已交付的成功作业改写成失败, 结果无处回收
            raise TapJobError(f"Cannot abort a job in phase {job['phase']}")
        if not self._transition(  # expected 覆盖全部在途态: 检查与迁移之间的窗口由 CAS 兜住
            job_id,                                                                                 # 作业 id
            expected_phases={"PENDING", "QUEUED", "EXECUTING"},
            phase="ABORTED",
            error="Job aborted by user",
        ):
            current = self.get_job(job_id)                                                          # 取当前态用于状态机判定
            phase = current["phase"] if current else "missing"  # 回读真实相位再报错: 比笼统的"状态错乱"可查
            raise TapJobError(f"Cannot abort a job in phase {phase}")

    def delete_job(self, job_id: str) -> None:
        """删除作业行及其结果文件 (结果文件缺失时容忍, 幂等)。"""
        job = self.get_job(job_id)  # 删除前先取行: result_path 只存在于作业行里
        if not job:                                                                                 # 作业不存在即无事可做
            raise TapJobError("TAP job not found")
        if job.get("result_path"):  # 先删文件: 反序会留下指向不存在行的 result_path
            Path(job["result_path"]).unlink(missing_ok=True)  # missing_ok: 幂等删除是 UWS 对 DELETE 的要求
        with self._db() as conn:                                                                    # 写库
            conn.execute("DELETE FROM tap_jobs WHERE id=?", (job_id,))  # 删行放在文件之后: 行没了就查不到该删哪个文件

    def _update(self, job_id: str, **values: Any) -> None:
        """按白名单列更新作业行 (仅 phase/error/result_path/media_type/checksum/size/overflow)。"""
        allowed = {"phase", "error", "result_path", "media_type", "checksum", "size", "overflow"}  # 白名单: 不过滤等于允许改 id/owner_key
        updates = {key: value for key, value in values.items() if key in allowed}  # **kwargs 来源, 列名必须自证
        updates["updated_at"] = self._now()  # 恒由本层写死: 调用方无权决定"何时变动"
        assignments = ", ".join(f"{key}=?" for key in updates)  # 列名只来自上方白名单, 不接外部输入
        with self._db() as conn:                                                                    # 按条件更新
            conn.execute(                                                                           # 更新语句
                # 列名仅来自上方硬编码白名单, 不接收外部输入; 全部值走 ? 绑定
                f"UPDATE tap_jobs SET {assignments} WHERE id=?",  # nosec B608  # noqa: S608
                (*updates.values(), job_id),                                                        # 按 job_id 定位
            )

    def _transition(
        self,
        job_id: str,
        *,
        expected_phases: set[str],
        **values: Any,
    ) -> bool:
        """compare-and-set: 仅当作业仍处于期望相位集合时才原子更新。

        这是 UWS 相位迁移的唯一写入口: 用 ``WHERE id=? AND phase IN (...)``
        把"检查 + 改写"压成一条语句: 分成"先查后改"两条会让 abort 与完成互相
        覆盖, 竞态下把已 ABORT 的作业写成 COMPLETED。

        Returns:
            bool: 是否恰好更新一行 (False 表示相位已被他人改掉)。
        """
        allowed = {"phase", "error", "result_path", "media_type", "checksum", "size", "overflow"}  # 同一白名单: _transition 也要挡掉改 id/owner_key
        updates = {key: value for key, value in values.items() if key in allowed}  # 过滤后才拼 SQL, 顺序与 values 一致
        updates["updated_at"] = self._now()  # 每次迁移都刷新: 客户端靠它判断作业是否还活着
        assignments = ", ".join(f"{key}=?" for key in updates)  # 占位符与 values 同序, 少一个就整体错位
        phases = tuple(sorted(expected_phases))  # 排序只为 SQL 文本稳定, 便于回归比对, 语义无差别
        if not phases:  # 空集合直接 False: "phase IN ()" 永假, 早退比发这条死 SQL 清楚
            return False
        placeholders = ",".join("?" for _ in phases)  # 个数与 phases 等长: 少一个绑定就错位
        with self._db() as conn:                                                              # 带前置相位约束的更新: 防止乱序更新把已完成态打回去
            cursor = conn.execute(                                                                  # 执行更新
                # 标识符/占位符均由本地白名单生成; 一切外部影响的值仍是绑定参数
                f"UPDATE tap_jobs SET {assignments} WHERE id=? AND phase IN ({placeholders})",  # nosec B608  # noqa: S608
                (*updates.values(), job_id, *phases),                                               # 相位也要进 WHERE
            )
            return cursor.rowcount == 1  # 恰好更新一行才是抢到相位的证明, 0 行=已被他人迁移

    def close(self) -> None:
        """关闭线程池 (已在排队的任务取消, 不等待在跑任务)。

        P2-11: 数据库连接自 ``_db()`` 上线后改为"每次操作即开即关",
        不存在常驻连接需要在这里收; 本方法只负责线程池。调用方 (TAP service)
        必须在关闭 HTTP 服务前调用它, 否则工作线程与数据库句柄随进程悬挂。
        """
        self._pool.shutdown(wait=False, cancel_futures=True)  # 不等待在跑作业: 关闭在停机路径上, 阻塞会拖成分钟级
