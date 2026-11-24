"""src.download_progress — 下载进度存储与回调 (CLI/GUI 同源事实源)。

能力边界: ProgressRecord (单任务进度快照) + ProgressStore (.progress/<job_id>.json
原子落盘, 崩溃可恢复) + on_progress 回调协议。边界: 只写进度不写数据; 文件为
唯一事实源, CLI 文本条与 GUI 都读它; 回调可选订阅 (双轨, 文件权威)。
白盒锚点: references/ALGORITHM-SPEC.md §2 (download_progress 锚点) / §3 (超参)。

进度文件协议 (GUI/CLI 消费契约):
  {"job_id","kind","status","total_bytes","done_bytes","total_pages","done_pages",
   "speed_bps","eta_sec","started_at","updated_at","error","hook":{...},"result":{...}}
status 枚举: queued / running / blocked (hook 拦截待用户决策) / done / failed / cancelled
"""

from __future__ import annotations

# 标准库: contextlib.suppress (尽力而为的清理与回调隔离, SIM105) / JSON (进度
# 文件载荷) / time (时间戳/节流) / 路径 / 类型标注 (回调协议)
import contextlib  # 尽力而为的清理与回调隔离 (下方两处 suppress)
import json  # 进度文件载荷: 落盘与读回共用同一套编码
import time  # epoch 时间戳 + 测速与落盘节流的时间基准
from pathlib import Path  # 目录与文件路径统一走 Path, 避免裸字符串拼路径
from typing import Any, Callable  # 载荷是弱类型 dict, 回调是单参可调用

# 本地: 目录锚定单点 — ProgressStore._path 的路径穿越防护委托它 (P3-6:
# 不再自制校验, 拒绝对路径/盘符/resolve 后逃逸);
# 原子写单点 — 落盘的原子性与 Windows 退避重试都在那里, 本模块只传退避序列
from src.scripts.guards import atomic_write_text, resolve_within  # 路径穿越校验 + 原子写 (含退避重试), 均为全仓单点

# 进度文件目录 (gitignored, 与 .checkpoints 同级的运行时状态)
DEFAULT_PROGRESS_DIR = ".progress"  # 运行时状态目录, 不入库 (文件是唯一事实源)

# 状态机枚举 (GUI/CLI 渲染分支的唯一依据; blocked = hook 拦截待用户决策,
# 三种 TERMINAL_STATUSES 之后不再迁移)
STATUS_QUEUED = "queued"        # 构造即落盘的初始态, 与"已起跑"严格区分
STATUS_RUNNING = "running"      # 真正在下载; 只有 start() 才迁移过来
STATUS_BLOCKED = "blocked"      # hook 拦截待决策: 非终态, 仍可被收口
STATUS_DONE = "done"            # 成功终态: result 已落盘, eta 已归零
STATUS_FAILED = "failed"        # 失败终态: error 必非空, 供重启后复盘
STATUS_CANCELLED = "cancelled"  # 取消终态: 刻意不写 error (主动放弃非故障)
TERMINAL_STATUSES = (STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED)  # 之后不再迁移, 消费者据此停轮询

# 进度回调协议: 收 to_dict() 载荷 (双轨订阅 — 文件是权威, 回调只是加速)
ProgressCallback = Callable[[dict[str, Any]], None]  # 单参: 直接吃载荷, 订阅方无需再解包

# 原子替换的重试退避序列 (秒): Windows 上 os.replace 的目标文件被并发读者
# (GUI 轮询 / 编辑器 / 杀软扫描) 持有时会抛 PermissionError (WinError 5)。
# 这类竞争是瞬时的 — 读者只占几十毫秒, 而进度落盘位于下载线程的业务路径
# 中段 (页码回调里), 让一次瞬时竞争杀死整个任务是过度反应。三次退避合计
# 最坏 170ms, 对 2Hz 节流的落盘无感知; 仍失败才向上抛, 异常类型保持
# OSError 不变, 上层语义不受影响。
REPLACE_RETRY_DELAYS = (0.02, 0.05, 0.1)  # 合计最坏 170ms: 瞬时竞争值得重试, 永久失败不必


class ProgressRecord:
    """单个下载任务的进度快照 (可序列化, GUI/CLI 直接消费)。

    职责: 承载一个任务在某一时刻的**全部**进度字段, 是进度文件与
    进度回调共用的载荷形态 (``to_dict`` 是唯一出口)。

    设计约束: 用 ``__slots__`` 固定键集, 因此新增字段必须同步进
    ``__slots__`` 与构造函数, 否则不进进度文件、GUI 永远看不到 ——
    这是刻意的"加字段必显式"设计, 而非遗漏。

    与 ``ProgressStore`` 的分工: 本类只管数据, 落盘/原子替换/节流
    全在 store 与 tracker 里, 保证同一份快照能被多处复用。
    """

    # __slots__: 进度记录每页都要序列化落盘, 去掉实例 __dict__ 省内存也
    # 让 to_dict 的键集固定 (新增字段必须同步加进来, 否则不进进度文件)
    __slots__ = ("job_id", "kind", "status", "total_bytes", "done_bytes",  # 键集 = 进度文件协议, 加字段必须同步这里
                 "total_pages", "done_pages", "speed_bps", "eta_sec",
                 "started_at", "updated_at", "error", "hook", "result")

    def __init__(
        self,
        job_id: str,
        kind: str = "region",
        status: str = STATUS_QUEUED,
        total_bytes: int = 0,
        done_bytes: int = 0,
        total_pages: int = 0,
        done_pages: int = 0,
        speed_bps: float = 0.0,
        eta_sec: float | None = None,
        started_at: float | None = None,
        updated_at: float | None = None,
        error: str | None = None,
        hook: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        """构造一条进度快照 (字段即进度文件协议, GUI/CLI 直接消费)。

        字段含义:
            job_id: 任务标识 (与进度文件名、checkpoint 键同源)
            kind: 任务类型 (region/sqlid/file/precise, GUI 图标与文案分支)
            status: 状态机当前值 (见模块级 STATUS_* 枚举)
            total_bytes/done_bytes: 字节级进度 (FileJob 的 Content-Length
                已知时填; 分页下载不填, 回落到页级)
            total_pages/done_pages: 页级进度 (分页下载按
                max_rows/page_size 估算总量, 每成功一页 +1)
            speed_bps: 滑动平均速率 (字节/秒; 只有字节进度有意义)
            eta_sec: 按当前速率推算的剩余秒数 (None = 未知/不适用)
            started_at/updated_at: epoch 秒 (启动时间 / 最后落盘时间)
            error: 失败原因 (仅 failed 状态非空)
            hook: hook 拦截的 ask 载荷 (仅 blocked 状态非空)
            result: 完成产物 ({"path": 落盘路径, "resume_spec": 续传参数})
        """
        self.job_id = job_id            # 任务标识与进度文件名同源, 跨进程续传靠它对齐
        self.kind = kind                # 任务类型仅供 GUI 图标/文案分支, 不参与进度计算
        self.status = status            # 状态机唯一可变字段, 落盘后由 GUI/CLI 读取
        self.total_bytes = total_bytes  # Content-Length 未知时留 0, fraction() 会回落到页级
        self.done_bytes = done_bytes    # 累加式: 每页回调只加增量, 调用方无需知道累计值
        self.total_pages = total_pages  # 分页下载按 max_rows/page_size 估算, 可能与实际不符
        self.done_pages = done_pages    # 仅在成功解析出该页后才 +1, 跳过的坏行不计入
        self.speed_bps = speed_bps      # 滑动窗口均值而非瞬时值; 页级下载恒为 0
        self.eta_sec = eta_sec          # None 表示未知/不适用, 渲染时干脆不显示
        self.started_at = started_at    # start() 会重置, 构造值只覆盖 queued 阶段
        self.updated_at = updated_at    # 每次 save() 由 store 统一盖戳, 调用方填的作废
        self.error = error              # 仅 failed 非空; 取消不写以免污染失败率统计
        self.hook = hook                # hook 拦截的 ask 载荷原样存, GUI 靠它渲染确认框
        self.result = result            # 产物描述原样存, 续传时读它拿 resume_spec

    def to_dict(self) -> dict[str, Any]:
        """快照转 dict (进度文件/回调的统一载荷形态)。

        Returns:
            键集与 ``__slots__`` 完全一致的新字典。值是**引用**不做
            深拷贝, 故调用方不得就地改 ``hook``/``result`` 子字典 ——
            那是记录自身状态, 改了就等于篡改进度事实。
        """
        # 按 __slots__ 推导而非手写字典: 少一处不同步的可能, 键序
        # 也随之确定, 进度文件因此逐字节可比对。
        return {name: getattr(self, name) for name in self.__slots__}  # 按 __slots__ 推导, 键序确定 → 进度文件逐字节可比对

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProgressRecord":
        """从 dict 还原快照 (未知键忽略, 容忍旧文件)。

        Args:
            data: 进度文件读回的字典, 允许缺键 (进度文件按任务类型
                省略不适用字段) 与多余键 (旧版残留)。

        Returns:
            还原出的记录; 缺字段取构造函数默认值, 因此跨版本读取
            不会因字段增删而整体失败。
        """
        # 只取 slots 内的键再展开: 直接 cls(**data) 会被旧文件里的
        # 未知键炸成 TypeError, 而宽容读取正是这里的目的。
        known = {k: data.get(k) for k in cls.__slots__ if k in data}  # 只取已知键: 旧文件的残留键会炸成 TypeError
        return cls(**known)  # type: ignore[arg-type]

    def fraction(self) -> float:
        """完成度 (0..1): 有 total_bytes 按字节, 否则按页, 都无回 0。"""
        if self.total_bytes > 0:                                                                   # 总字节已知才给百分比: 否则进度条只能空转
            return min(max(self.done_bytes / self.total_bytes, 0.0), 1.0)  # 钳到 [0,1]: 估算总量偏小时进度条会溢出
        if self.total_pages > 0:                                                                    # 总页数同理, 否则页码进度会显示 0/0
            return min(max(self.done_pages / self.total_pages, 0.0), 1.0)  # 页级同口径钳制, 否则两处百分比会打架
        return 0.0  # 总量未知: 报"未知"而不是猜一个假进度


class ProgressStore:
    """进度文件存储: 每任务一个 JSON, 原子写 (tmp + os.replace)。"""

    def __init__(self, progress_dir: str | Path = DEFAULT_PROGRESS_DIR) -> None:
        """打开 (必要时创建) 进度文件目录。

        Args:
            progress_dir: 进度目录 (默认 ``.progress``, gitignored 的
                运行时状态)。目录在此处创建, 之后 ``_path`` 依赖它已存在。

        构造不抛异常 (除非目录创建被文件系统拒绝); 目录锚定的
        路径穿越防护在每次 ``_path`` 调用时重新做, 不缓存结果。
        """
        self.progress_dir = Path(progress_dir)                                                     # 进度目录在此锚定一次: 跨线程共用同一个根
        # 目录惰性创建 (外部 IO): 与 .checkpoints 同级的运行时状态, gitignored
        self.progress_dir.mkdir(parents=True, exist_ok=True)  # 惰性建: tracker 独立可用时无需外部先建目录

    def _path(self, job_id: str) -> Path:
        """job_id -> 进度文件路径 (防路径穿越)。

        P3-6: 形态校验委托全仓单点 ``resolve_within`` (拒目录成分、绝对路径、
        盘符与 resolve 后逃逸) — 自制校验只查 ``pardir``/``/``/``\\`` 时不拒
        绝对路径与盘符, 绕过单点即路径安全双轨。校验与拼名分离: 先过
        单点校验 job_id 形态, 再按 progress_dir 原形态 (相对/绝对) 拼
        ``.json`` 后缀, 两种目录配置的行为不变。
        """
        # 单点校验 (越界即 ValueError); 返回值只用于校验, 不直接当路径 —
        # 后缀拼装必须留在本方法, 否则 .json 会丢
        resolve_within(self.progress_dir, job_id)  # 越界即 ValueError: 非法输入是调用方 bug, 不静默兜底
        return self.progress_dir / f"{job_id}.json"  # 后缀在此拼: 单点只管形态, 不管扩展名

    def save(self, record: ProgressRecord) -> str:
        """原子落盘一条进度记录 (走共享 atomic_write_text), 返回文件路径。

        读者 (GUI/CLI) 可能在任何时刻并发读 — 直接写目标文件会让它们看到
        半行 JSON; 先写同目录 .tmp 再 os.replace 保证读者只会看到旧完整
        版或新完整版。

        Windows 专项: 目标文件被并发读者持有时 os.replace 抛
        PermissionError (WinError 5)。这里按 REPLACE_RETRY_DELAYS 退避重试
        — 不退避重试的话, 该异常会穿过
        save -> _flush -> advance_pages 直达
        下载工作线程 (不在 _run 的 try 范围内), 一次瞬时竞争就杀死任务。
        重试耗尽后原类型抛出, 上层 except OSError 的行为不变。

        退避语义原先只存在于本方法的自带副本里, 而全包单点
        ``guards.atomic_write_text`` 没有 — 于是"全仓唯一实现"这条约定
        已经被违反, 且副本长出了主实现缺失的能力 (正是它 docstring 警告的
        "副本一旦漂移")。现在退避作为 ``retry_delays`` 参数收进单点, 两边
        共用同一份语义; 常量仍留在本模块, 调用点现读, 故按本模块名打桩的
        用例照旧生效。
        """
        path = self._path(record.job_id)  # 复用同一路径解析: 校验与拼名只有这一处
        record.updated_at = time.time()  # 落盘时刻由 store 统一盖戳, 调用方填的值一律作废
        # 外部 IO 调用点: 原子写 + 退避重试都归共享实现, 本模块不再自带副本
        atomic_write_text(  # 显式 utf-8 + 不转义: 产物含中文时仍可读且可逐字节比对
            path, json.dumps(record.to_dict(), ensure_ascii=False),
            encoding="utf-8", retry_delays=REPLACE_RETRY_DELAYS,
        )
        return str(path)  # 回传路径给调用方做日志/续传, 免得二次解析

    def load(self, job_id: str) -> ProgressRecord | None:
        """读进度记录; 文件缺失/损坏返回 None (BOM 兼容)。

        utf-8-sig 读入: 某些编辑器/工具给 JSON 加了 BOM, 纯 utf-8 解码会
        在首字符报错; 读取路径必须容忍, 否则 GUI 整个列表打不开。
        """
        path = self._path(job_id)  # 走同一条路径: 校验口径与 save 保持一致
        if not path.exists():                                                                      # 记录文件缺失即无进度可读, 不静默当 0%
            return None  # 缺失是常态(任务还没起跑), 返回 None 而非抛错
        try:
            with open(path, "r", encoding="utf-8-sig") as f:  # utf-8-sig: 容忍带 BOM 的进度文件, 否则整个列表打不开
                return ProgressRecord.from_dict(json.load(f))
        except (json.JSONDecodeError, OSError):
            return None  # 损坏即视为不存在: 读路径不该被单个坏文件搞崩

    def list_jobs(self) -> list[str]:
        """列出全部真正的进度文件任务 id (外部 IO: 扫描 *.json + 内容校验)。

        内容校验 (读回 JSON, 比对其 job_id 与文件名 stem): 若 output_dir
        与 progress_dir 配成同一目录 (边缘配置), 下载产物的 provenance
        sidecar (``<name>.json.provenance.json``) 甚至普通 JSON 产物本身
        也匹配 *.json — 只按后缀 glob 会把它们扫成伪 job_id,
        list_jobs/status() 对幽灵 id 返回 None 记录, CLI download list
        出现查不到的任务。真正的进度文件由 ProgressStore.save 写出, 其
        job_id 必与文件名一致; sidecar/产物 JSON 没有 job_id 键, 自然被
        排除。损坏的 .json 同样跳过 — 列举是人工复核面, 不该被单个坏文件
        搞崩 (与 DownloadCheckpoint.list_jobs 的容错口径一致)。
        """
        out: list[str] = []  # 只收内容自证为进度文件者, 不按后缀盲收
        for p in sorted(self.progress_dir.glob("*.json")):  # 排序只为列举顺序稳定, 便于人工比对两次快照
            try:
                # 外部 IO 调用点: 读回候选文件判别真伪; utf-8-sig 与 load()
                # 同口径 (容忍带 BOM 的进度文件)
                data = json.loads(p.read_text(encoding="utf-8-sig"))  # 外部 IO: 核对 job_id 是否与文件名 stem 一致
            except (json.JSONDecodeError, OSError):
                continue  # 坏文件不当 job, 也不让列举失败
            if isinstance(data, dict) and data.get("job_id") == p.stem:  # save 的不变量; sidecar/产物 JSON 无此键, 自然被排除
                out.append(p.stem)  # 用文件名而非内容里的 id: 文件名才是消费者的寻址键
        return out

    def delete(self, job_id: str) -> bool:
        """删除进度文件 (任务终结后清理); 不存在回 False。

        Args:
            job_id: 待清理的任务标识。

        Returns:
            确实删掉了文件返回 True; 本来就没有返回 False。

        Raises:
            ValueError: ``job_id`` 形态非法 (经 ``_path`` 的
                ``resolve_within`` 校验), 此时**不**返回 False —
                非法输入是调用方 bug, 静默 False 会把它伪装成"已清理"。
        """
        path = self._path(job_id)  # 非法 job_id 在此抛 ValueError, 不伪装成"已清理"
        # exists + unlink 两步而非 unlink(missing_ok): 后者会吞掉
        # 权限/占用类 OSError, 让"删不掉"与"本来就没有"无法区分。
        if path.exists():  # 两步写法才能区分"删不掉"与"本来就没有"
            path.unlink()  # 权限/占用类 OSError 照抛: 那属真实故障, 不该被静默
            return True  # 确实删掉了才报 True
        return False


def _bar_chars() -> tuple[str, str]:
    """进度条字符: stdout 编码不支持块字符时回退 ASCII (Windows GBK 兼容)。"""
    # 延迟导入: 只在渲染文本条时才需要探 stdout 编码, 不进模块级依赖
    import sys  # 延迟导入: 只在渲染文本条时才探 stdout 编码
    enc = (getattr(sys.stdout, "encoding", None) or "utf-8")  # 拿不到编码时按 utf-8 试, 失败再退 ASCII
    try:
        # 探测性编码: 块字符在 GBK 代码页的 Windows 控制台会抛
        # UnicodeEncodeError, 直接让 CLI 崩溃; 提前试编码并回退 ASCII
        "█░".encode(enc)  # 探测而非查表: 代码页别名(utf8/UTF-8)只有试过才知支持
        return "█", "░"  # 支持则用块字符, 视觉上更接近 GUI 进度条
    except (UnicodeEncodeError, LookupError):
        return "#", "-"  # Windows GBK 回退: 宁可丑也不让 CLI 崩


def render_text_bar(record: dict[str, Any] | ProgressRecord, width: int = 40) -> str:
    """把进度记录渲染为单行文本条 (CLI 用; GUI 可改用图形渲染同源 JSON)。

    例: ``[job] running 62%|██████▌      | 6.2/10.0MB 1.2MB/s eta 3s``
    Windows GBK 控制台自动回退 ASCII 字符 (#/-), 不抛 UnicodeEncodeError。
    """
    if isinstance(record, ProgressRecord):                                                       # 调用方可能传 dict 或记录对象, 两种都收
        record = record.to_dict()  # 两种入参形态都收: tracker 内部传对象, GUI 传 dict
    # 渲染取字节优先、页次之: 与 fraction() 同一套优先级, 保证文本条与
    # GUI 百分比口径一致 (两处各写一套优先级就会漂移, 用户看到两个进度)
    frac = 0.0  # 总量未知时的缺省完成度, 与 fraction() 保持同口径
    total_bytes = record.get("total_bytes") or 0  # or 0: 键缺失与显式 null 同归为未知
    done_bytes = record.get("done_bytes") or 0    # or 0: 完成量同样把键缺失与显式 null 归为未知
    total_pages = record.get("total_pages") or 0  # 页级字段仅分页下载有值
    done_pages = record.get("done_pages") or 0  # 页级字段仅分页下载有值
    if total_bytes > 0:  # 字节优先: 与 fraction() 同优先级, 否则两处百分比打架
        frac = min(max(done_bytes / total_bytes, 0.0), 1.0)  # 钳制: 估算总量偏小会让进度条溢出
        amount = f"{done_bytes / 1e6:.1f}/{total_bytes / 1e6:.1f}MB"  # 用 1e6 而非 1024^2: 与 GUI 文案口径一致
    elif total_pages > 0:  # 无字节口径时回落页级 (分页下载常态)
        frac = min(max(done_pages / total_pages, 0.0), 1.0)  # 同样钳制, 页级估算也可能偏低
        amount = f"{done_pages}/{total_pages}页"
    else:
        amount = f"{done_bytes}B"  # 总量未知: 只报已收字节, 不猜百分比
    fill_ch, empty_ch = _bar_chars()  # 字符集在此统一选定, 渲染层不再关心编码
    filled = int(frac * width)  # int 截断: 满格留给 frac==1.0, 避免 99% 就画满
    bar = fill_ch * filled + empty_ch * (width - filled)  # 两段拼接长度恒为 width, 条宽不随完成度抖
    speed = record.get("speed_bps") or 0.0  # 页级下载速率恒 0, 显示 0 比省略更可预期
    eta = record.get("eta_sec")  # None = 未知/不适用, 不显示而不是显示 0
    eta_s = f" eta {eta:.0f}s" if eta else ""  # 0.0 也算假值, 完成后不残留倒计时
    status = record.get("status", "?")  # 缺 status 显示 ? 而不是 KeyError
    return (f"[{record.get('job_id', '?')}] {status} {frac * 100:3.0f}%|{bar}| "
            f"{amount} {speed / 1e3:.0f}KB/s{eta_s}")


class ProgressTracker:
    """任务内进度累加器: 页/字节增量 + 速度/ETA 推算, 变更即落盘 + 回调。

    线程安全由调用方 (DownloadManager 单任务单线程) 保证; 速度用滑动平均。
    """

    def __init__(
        self,
        store: ProgressStore,
        job_id: str,
        kind: str = "region",
        total_bytes: int = 0,
        total_pages: int = 0,
        callback: ProgressCallback | None = None,
        adopt: ProgressRecord | None = None,
    ) -> None:
        """构造任务内进度累加器。

        线程安全由调用方保证 (DownloadManager 一任务一线程, 不共享);
        速度用 0.5s 滑动平均窗口 (_refresh_speed), 落盘 2Hz 节流
        (_flush) — 页回调可能远快于 2Hz, 不限流会把磁盘 IO 打满并拖慢
        下载本身。

        Args:
            adopt: 续传/重入**既有**记录时, 传入 :meth:`ProgressStore.load`
                读回的旧记录: 进度与 ``result`` 沿用它, 且构造期**不落盘**。
                理由见下「为什么续传要传 adopt 而不是删掉构造期 save」。

        为什么续传要传 adopt (不是删掉构造期那次 save):
            构造期那次 save 是为「独立使用、无 Manager 代存」准备的 ——
            任务还没起跑, 订阅方就该在进度文件里看到 queued 那一条
            (:meth:`DownloadManager._spawn` 之后还会再显式 save 一次, 但
            standalone 用法只靠这一次)。删掉它等于拿 standalone 契约去
            换续传路径, 那是把一个 bug 换成另一个 bug。

            真正的病灶在续传侧**另起了一条全零记录**: 跨进程 resume 时
            内存注册表为空, 下载管理器按 job_id 重建 tracker, 而
            :class:`ProgressRecord` 构造出来的是 ``done_pages=0`` /
            ``result=None`` 的全零快照 —— 它一落盘就把上一轮的进度与
            ``resume_spec`` 抹掉。续传若随后失败, 盘上旧记录已无 spec,
            这个作业**永远续不回来** (fail-open: 数据被静默丢弃)。
            传 adopt 从源头堵住: 记录从旧快照长出来, 不是从零长出来。
        """
        self.store = store  # store 持有落盘与原子替换, tracker 只管累加
        self.callback = callback  # 可选订阅: 文件是权威, 回调只是加速通道
        # 种子记录: adopt 给出就用旧快照, 否则按显式入参现造一条空白。
        # 两者都只贡献「进度 + result」, status/error/hook 一律留新 ——
        # 那是本次运行的契约事件 (start/finish/fail), 续传不该继承上一轮的
        seed = adopt if adopt is not None else ProgressRecord(  # 空白种子: 与普通构造同参数, 下面的拷贝口径才唯一
            job_id=job_id, kind=kind, status=STATUS_QUEUED,
            total_bytes=total_bytes, total_pages=total_pages,
            started_at=time.time())
        self.record = ProgressRecord(  # 快照由 tracker 独占写, 避免多处改同一份进度事实
            job_id=job_id, kind=kind, status=STATUS_QUEUED,
            total_bytes=seed.total_bytes, total_pages=seed.total_pages,
            done_bytes=seed.done_bytes, done_pages=seed.done_pages,  # 上一轮实绩续着数: 归零即进度说谎
            result=seed.result,  # 含 resume_spec: 丢了它这个作业就再也续不回来
            started_at=time.time())
        # 节流状态: 上次落盘时刻 / 上次测速时的字节数与时刻
        self._last_emit = 0.0  # 取 0 而非当前时刻: 首调 _flush 必须真落盘一次
        self._last_bytes = seed.done_bytes  # 测速基线对齐当前实绩: 沿用 0 会把续传前的量算进速率
        self._last_time = time.time()  # 测速窗口的时间基线
        if adopt is None:
            # 构造即落盘 queued 记录: 独立使用 (无 Manager 代存) 时进度文件立即可见
            self.store.save(self.record)  # 外部 IO: 让订阅方在任务起跑前就看到它存在
        # adopt 路径刻意不落盘: 旧记录已在盘上且是权威, 这里再写一遍只会
        # 把它的 failed/cancelled 终态盖成 queued 做一次无意义的状态抖动
        # (内容相同, 只有 updated_at 变)。真正的落盘点是调用方紧接的
        # start() —— 那是 force 的契约事件, 一次就写到位。

    def start(self) -> None:
        """标记任务开始运行 (queued -> running, 强制落盘)。

        副作用: 改写 ``started_at`` 为本次时刻并立即落盘 (force=True),
        使 GUI/CLI 在任务刚起跑时就能看到 running 而非长时间 queued。
        本方法不抛异常 (落盘失败由 store 抛出, 属真实 IO 故障)。
        """
        self.record.status = STATUS_RUNNING  # 契约事件: 必须强制落盘, 订阅方立刻看到起跑
        # 重置 started_at 而非保留构造时刻: queued 阶段可能等了很久,
        # 用它算速率会把等待时间算进速度里。
        self.record.started_at = time.time()  # 重置: queued 的等待时长不该计入速率分母
        self._flush(force=True)  # force: 状态跃迁不能等节流窗口

    def advance_pages(self, pages: int = 1, bytes_delta: int = 0) -> None:
        """累加页/字节进度并刷新速度/ETA (节流落盘 + 回调)。

        Args:
            pages: 本次成功完成的页数增量。
            bytes_delta: 本次新增字节数 (分页下载一般传 0)。

        落盘走 2Hz 节流而非 force: 页回调可高频触发, 每页落盘会把
        磁盘 IO 打满反而拖慢下载; 状态跃迁才强制落盘。
        """
        self.record.done_pages += pages  # 累加而非赋值: 调用方只报增量, 无需知道累计值
        self.record.done_bytes += bytes_delta  # 分页下载一般传 0, 文件下载才带真实字节增量
        # 先测速再落盘: 速度/ETA 必须与本次增量同批写盘, 否则文件里
        # 会出现"页数已进、速度还停在上一批"的错位快照。
        self._refresh_speed()  # 顺序即不变量: 测速在前, 快照才不会页数已进而速率滞后
        self._flush()  # 不 force: 页回调可高频触发, 落盘走 2Hz 节流

    def set_total_bytes(self, total: int) -> None:
        """设置总字节数 (如 Content-Length 已知时), 强制落盘。

        总量到位会让 fraction()/ETA 从"未知"转为可算, 属用户可见的
        口径变化, 故绕过节流立即落盘。
        """
        self.record.total_bytes = total  # 总量到位让完成度从"未知"转为可算
        self._flush(force=True)  # 绕过节流: 口径切换是用户可见的变化, 该立刻反映

    def set_total_pages(self, total: int) -> None:
        """设置总页数 (按 max_rows/page_size 估算), 强制落盘。

        分页下载在拿到真实 total 之前用估算值占位; 估算可能与实际
        不符, 故 fraction() 对超过 1.0 的完成度做了钳制。
        """
        self.record.total_pages = total  # 估算值可能与实际不符, 钳制由 fraction() 侧兜住
        self._flush(force=True)  # 同上: 总量变化属用户可见的口径切换

    def block(self, hook_payload: dict[str, Any]) -> None:
        """hook 拦截: 状态转 blocked, ask 载荷入文件 (GUI/CLI 同源可见)。"""
        self.record.status = STATUS_BLOCKED  # 非终态: 等用户决策, 之后仍可收口成 done/failed/cancelled
        self.record.hook = hook_payload  # ask 载荷原样存, GUI 靠它渲染确认框
        self._flush(force=True)  # 阻塞必须立刻可见, 否则订阅方看不到待决策提示

    def finish(self, result: dict[str, Any]) -> None:
        """标记完成并附结果 (path/resume_spec), 强制落盘。

        Args:
            result: 产物描述 (约定含 ``path`` 与可选 ``resume_spec``),
                原样存入进度文件供续传/复盘读取。

        eta_sec 置 0 而非留旧值: 残留的估算 ETA 会让 GUI 在已完成
        任务上继续倒计时。
        """
        self.record.status = STATUS_DONE  # 成功终态: 进入 TERMINAL_STATUSES, 不再迁移
        self.record.result = result  # 产物描述原样存, 续传时读它拿 resume_spec
        self.record.eta_sec = 0.0  # 归零而非留旧值: 残留估算会让 GUI 在已完成任务上继续倒计时
        self._flush(force=True)  # force: 完成是契约事件, 订阅方须马上停止轮询

    def fail(self, error: str) -> None:
        """标记失败并记录原因, 强制落盘。

        ``error`` 与 ``status`` 一起落盘而非只记日志: 失败原因必须
        跟着进度文件走, 进程重启后 GUI 才读得到上次为何失败。
        """
        self.record.status = STATUS_FAILED  # 失败终态, 与取消严格区分
        self.record.error = error  # 原因跟着文件走, 进程重启后仍可复盘
        self._flush(force=True)  # force: 失败原因必须立刻可见, 不能等节流

    def cancel(self) -> None:
        """标记任务已取消, 强制落盘。

        取消**不**写 error 字段: 取消是用户主动行为而非故障, 与
        failed 混同会让失败率统计把主动放弃也算进去。
        """
        self.record.status = STATUS_CANCELLED  # 独立终态: 主动放弃不是故障, 故不写 error
        self._flush(force=True)  # force: 取消是用户已做的决定, 界面须立即反映

    def _refresh_speed(self) -> None:
        """滑动窗口测速与 ETA 推算 (窗口 0.5s, 与落盘节流同频)。

        速率 = 窗口内新增字节 / 窗口时长; ETA = 剩余字节 / 速率, 仅在
        "已知总字节且速率>0"时更新 — 总字节未知 (分页下载) 时 eta_sec
        保持 None, 文本条直接不显示 ETA, 而不是给一个假数字。
        """
        now = time.time()  # 单一时间基准: 前后各取一次会算出负窗口
        dt = now - self._last_time  # 距上次测速的窗口时长
        if dt >= 0.5:  # 0.5s 平滑窗口, 避免瞬时抖动 (与落盘节流同频)
            db = self.record.done_bytes - self._last_bytes  # 窗口内新增字节; 负值也会被下个窗口抹平
            self.record.speed_bps = db / dt if dt > 0 else 0.0  # dt>0 已由上面的 if 守住, 分支纯防御
            self._last_bytes = self.record.done_bytes  # 字节基线前移: 下一窗口从这里起量
            self._last_time = now  # 时间基线同步前移, 两者必须同批更新
            if self.record.speed_bps > 0 and self.record.total_bytes > 0:  # 总量未知则 ETA 无从算起, 保持 None
                remain = self.record.total_bytes - self.record.done_bytes  # 剩余可超 0 (超收), ETA 仍为负数显示
                self.record.eta_sec = remain / self.record.speed_bps  # 速率为除数前提, >0 已由上面的条件守住

    def _flush(self, force: bool = False) -> None:
        """落盘 + 回调 (默认 2Hz 节流; 状态跃迁必须 force)。

        节流理由: 进度文件是给"人眼/GUI"看的, 2Hz 已远够; 而页回调在
        小页 + 高速网络下可达每秒数十次, 不限流会把磁盘 IO 打满、拖慢
        下载本身。状态跃迁 (start/block/finish/fail/cancel) 用 force=True
        — 这些是契约事件, 必须立即可见, 不能等节流窗口。
        """
        now = time.time()  # 落盘节流的时间基准, 与测速窗口各取各的
        if not force and now - self._last_emit < 0.5:  # force 豁免节流: 状态跃迁属契约事件
            return  # 节流: 进度文件 2Hz 足够, 减少 IO
        self._last_emit = now  # 只在真落盘时推进节流窗口, 被节流的调用不占配额
        # 外部 IO 调用点: 进度记录原子落盘 (GUI/CLI 的事实源)
        self.store.save(self.record)  # 外部 IO: 落盘失败照抛, 那属真实 IO 故障
        if self.callback:  # 回调可选: 未订阅时这一段零开销
            # SIM105: 回调异常不得打断下载 (suppress 表达"吞掉但继续")
            with contextlib.suppress(Exception):  # 订阅方(渲染层)崩了不该杀死下载任务
                self.callback(self.record.to_dict())  # 传的是引用: 回调不得就地改记录, 见 to_dict 契约
