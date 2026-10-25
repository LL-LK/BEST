"""src.task_log — 任务日志管理器 (快速定位问题)。

能力边界: TaskLogger: append-only JSONL 任务事件流 (.logs/task_log.jsonl,
原子行追加) + 查询/尾随/按任务聚合。边界: 只记事件不记数据; 与 .progress/
(进度快照) 分工 — 日志答"发生了什么", 进度答"到哪了"; 行截断防护 (单行
上限, 超长载荷只留摘要)。
白盒锚点: references/ALGORITHM-SPEC.md §2 (task_log 锚点)。

事件模型 (一行一事件):
  {"ts","task_id","event","level","message","data"{...}}
event 枚举: submit/start/page/done/blocked/failed/cancelled/hook/ask/query/
  resume/info — level: info/warn/error。
"""

from __future__ import annotations

# 标准库: JSON (事件序列化) / threading.Lock (行级写锁) / time (时间戳) /
# 路径 / 类型标注
import json
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Optional

DEFAULT_LOG_DIR = ".logs"  # 与 .progress/ 同级的运行时状态目录, 构造时建一次
DEFAULT_LOG_NAME = "task_log.jsonl"  # 固定文件名: 换名即换一条独立事件流, 不做按天分文件
MAX_LINE_CHARS = 4000  # 单行截断防护: 超长载荷只留摘要, 防日志爆盘

# 事件枚举 (查询过滤用)
EVENT_SUBMIT = "submit"                                                                             # 提交事件: 任务入队的事实标记
EVENT_START = "start"                                                                             # 开始事件: 与提交分开记, 才看得出排队时长
EVENT_PAGE = "page"                                                                                 # 逐页事件: 长任务的进度靠它数已取页数
EVENT_DONE = "done"                                                                                 # 完成事件: 正常收尾的唯一定位点
EVENT_BLOCKED = "blocked"                                                                          # 阻塞事件: 等待外部输入, 与失败严格分开
EVENT_FAILED = "failed"                                                                             # 失败事件: 带异常文本的那一类
EVENT_CANCELLED = "cancelled"                                                                       # 取消事件: 取消是主动中止, 不是失败
EVENT_HOOK = "hook"                                                                                 # 钩子事件: 任务内挂载点的触发记录
EVENT_ASK = "ask"                                                                               # 询问事件: 向用户提问, 排障要能看出卡在提问上
EVENT_QUERY = "query"                                                                            # 查询事件: 打上游的那一步, 用于核对往返次数
EVENT_RESUME = "resume"                                                                             # 续传事件: 断点续跑的边界标记
EVENT_INFO = "info"                                                                                 # 信息事件: 兜底等级, 不承载状态转移


def _clip(text: str, limit: int = MAX_LINE_CHARS) -> str:
    """超长字符串截断加省略标记 (防单行爆盘)。

    Args:
        text: 待裁剪文本 (调用方已保证是 ``str``)。
        limit: 字符上限; 超过则保留前缀并追加省略标记。

    Returns:
        长度不超过 ``limit + 标记长度`` 的字符串。**静默截断**是刻意
        契约: 日志不是数据通道, 丢尾部优于让整行写不出去。
    """
    return text if len(text) <= limit else text[:limit] + f"...<+{len(text) - limit}chars>"  # 标记带丢弃字数: 静默截断要让人知道丢了多少


class TaskLogger:
    """任务日志记录器: 进程内单例式使用, 多线程安全 (行级锁)。

    职责: 把任务生命周期事件写成 append-only JSONL, 并提供 tail/tasks/
    summarize/problems 四个只读视图。与 ``.progress/`` 的进度快照**分开**:
    本类答"发生了什么", 进度答"到哪了"。

    Args:
        log_dir: 日志目录, 构造时惰性创建 (默认 ``.logs``)。
        name: JSONL 文件名; 换名即换一条独立事件流。

    已知边界: 读路径是全量顺序读后内存过滤, 不做索引; 日志规模按
    单次运行有界, 换取四个视图共用一份实现。
    """

    def __init__(self, log_dir: str | Path = DEFAULT_LOG_DIR,
                 name: str = DEFAULT_LOG_NAME) -> None:                                             # 日志文件名: 换名即换一条独立事件流
        """打开 (必要时创建) 日志文件 (append-only JSONL)。

        Args:
            log_dir: 日志目录 (缺省 .logs, gitignored 运行时状态)
            name: 日志文件名 (缺省 task_log.jsonl)
        """
        self.log_dir = Path(log_dir)                                                              # 规整成路径对象: 四个只读视图都靠它定位文件
        # 目录惰性创建 (外部 IO): 与 .progress/.checkpoints 同级的运行时状态
        self.log_dir.mkdir(parents=True, exist_ok=True)  # 构造时建目录而非首次写入: 读路径 (tail) 也能依赖它存在
        self.path = self.log_dir / name  # 路径一次算好: 每条事件不再重拼
        # 行级锁: 线程池多个 worker 会并发 append — 不持锁打开文件,
        # 两行的字节会交错, 读回时整行 JSON 解析失败 (半行污染后续全部)
        self._lock = threading.Lock()  # 行级锁而非文件级: 多 worker append 不串行化会整行交错

    def log(self, task_id: str, event: str, message: str = "",
            level: str = "info", **data: Any) -> dict[str, Any]:
        """追加一条任务事件 (返回该事件 dict)。

        Args:
            task_id: 任务标识; 聚合视图 (summarize/tasks) 按它分组。
            event: 事件枚举 (见本模块 EVENT_* 常量), 供 tail 过滤。
            message: 人类可读描述, 内部再按 500 字符截断。
            level: ``info``/``warn``/``error``; 只有 warn/error 会进
                problems 视图, 等级写错等于事件被静默埋没。
            **data: 结构化载荷; 超长时降级为 ``_clipped`` 摘要字典。

        Returns:
            实际写入的那条记录 dict (``ts`` 已填), 调用方可直接回显。

        本方法不抛异常: 日志写失败不得反过来中断被记录的下载任务
        (default=str 已覆盖不可序列化对象的情形)。
        """
        # 空 kwargs 归一为 None 而非 {}: 事件模型约定"无载荷"用 null,
        # 读侧 problems/fmt_record 靠 falsy 判断省略该字段。
        payload: Any = data or None  # 空 kwargs 归一为 None: 事件模型约定"无载荷"用 null
        if payload is not None:                                                                     # 有载荷才量长度: 空载荷无需序列化与裁剪
            # 先序列化再量长度: 量的是**落盘字节量**而非字符数,
            # 中文载荷下两者差一个 utf-8 编码倍数。
            serialized = json.dumps(payload, ensure_ascii=False, default=str)  # 先序列化再量: 中文载荷下字节数与字符数差一个编码倍数
            if len(serialized) > MAX_LINE_CHARS:                                                   # 按落盘字节量判定: 中文载荷下字符数会低估
                # 超长载荷降级为摘要串 (防单行爆盘), 键名保留供定位
                payload = {"_clipped": True,  # 降级成摘要而非丢弃: 保留键名才定位得到是哪个载荷超长
                           "keys": sorted(payload.keys()),
                           "preview": serialized[:500]}
        record = {  # 字段顺序即事件模型顺序: 人工直接读 JSONL 也认得
            "ts": time.time(),
            "task_id": task_id,
            "event": event,
            "level": level,
            "message": _clip(str(message), 500),
            "data": payload,
        }
        line = json.dumps(record, ensure_ascii=False, default=str)  # default=str 兜住不可序列化对象: 日志写失败不能反过来搞崩下载任务
        # default=str: 载荷里混进 datetime/Path 等不可序列化对象时降级为
        # 字符串 — 日志记录失败绝不能反过来搞崩下载任务本身。
        # SIM117: 单条 with 合并锁与文件句柄 (退出序: 先文件后锁, 与嵌套
        # with 的语义一致)
        with self._lock, open(self.path, "a", encoding="utf-8") as f:  # 锁与句柄同一句 with: 退出序先文件后锁, 与嵌套 with 语义一致
            # 外部 IO 调用点: append 模式追加一行 (持行级锁; "a" 模式在
            # Windows 上不截断, 多 writer 只要串行化就不会互相覆盖)
            f.write(line + "\n")  # append 模式在 Windows 不截断, 多 writer 只要串行化就不互相覆盖
        return record

    # ---- 查询 ---------------------------------------------------------------

    def tail(self, n: int = 20, task_id: Optional[str] = None,
             event: Optional[str] = None, level: Optional[str] = None                               # 两个过滤条件可空: 空串即不过滤
             ) -> list[dict[str, Any]]:
        """读最近 n 条事件 (可按任务/事件/级别过滤)。

        实现是"全量顺序读 + 内存过滤" (外部 IO): 日志按天/按任务规模
        有界, 换来 tail/tasks/summarize/problems 四个视图同一份简单实现;
        n=0 表示不限条数 (供聚合视图消费)。
        """
        if not self.path.exists():  # 文件不存在是正常初始态: 首次运行就属这条, 不算错误
            return []
        rows: list[dict[str, Any]] = []                                                             # 结果容器: 全量读进内存后在内存里过滤
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:                                                                          # 逐行读: 读路径是全量顺序读, 不建索引
                line = line.strip()                                                                 # 去行尾换行: 追加时每行都带换行符
                if not line:                                                                        # 空行跳过: 崩溃残留可能留下空行
                    continue
                try:
                    rec = json.loads(line)                                                         # 解析失败不入此路径: 由下面的异常分支收口
                except json.JSONDecodeError:
                    continue  # 容忍半行 (崩溃残留)
                if task_id and rec.get("task_id") != task_id:
                    continue
                if event and rec.get("event") != event:
                    continue
                if level and rec.get("level") != level:
                    continue
                rows.append(rec)                                                                    # 通过全部过滤才入库: 三个条件是并列的与
        return rows[-n:] if n > 0 else rows  # n=0 表"不限": 聚合视图靠它拿全量, 省掉另一套读盘

    def tasks(self) -> list[str]:
        """列出日志中出现过的全部任务 id (排序稳定)。

        Returns:
            去重后的 task_id 列表, 按字典序排序 — 排序稳定才能让
            CLI 的任务清单两次运行输出可比对。
        """
        # 用 list 而非 set 判重: 保持首次出现顺序便于排错, 最终再排序。
        seen: list[str] = []  # list 判重而非 set: 保持首次出现顺序便于排错, 最终才排序
        for rec in self.tail(n=0):                                                                 # 复用全量视图: 四个视图的过滤口径必须一致
            tid = rec.get("task_id", "")
            if tid and tid not in seen:                                                             # 非空且未出现过: 两个条件缺一不可
                seen.append(tid)                                                                   # 追加而非入集合: 保持首次出现顺序便于排错
        return sorted(seen)  # 排序而非保持插入序: 两次运行的清单要能逐行 diff

    def summarize(self, task_id: str) -> dict[str, Any]:
        """单任务聚合: 事件数/首末时间/是否异常 (快速定位问题入口)。

        Args:
            task_id: 要聚合的任务标识。

        Returns:
            聚合字典; 任务不存在时返回 ``found=False`` 且**不抛异常** —
            CLI 查一个跑完就被清日志的任务是正常操作。
            命中时含 levels/event_counts 直方图与 has_error 布尔位。
        """
        # 复用 tail(n=0) 全量视图, 不另写一套读盘逻辑: 四个视图的
        # 过滤口径必须一致, 各写一份迟早会漂移。
        rows = [r for r in self.tail(n=0) if r.get("task_id") == task_id]  # 复用同一份全量读: 各视图各写一套读盘逻辑迟早漂移
        if not rows:                                                                            # 未命中不是错误: 查一个已清日志的任务是正常操作
            return {"task_id": task_id, "events": 0, "found": False}
        # 两张直方图手工累加而不用 Counter: 需要保持键序确定,
        # 便于 E2 快照逐字节比对。
        levels: dict[str, int] = {}  # 手工累加不用 Counter: 键序要确定, 供快照逐字节比对
        events: dict[str, int] = {}                                                             # 事件直方图: 手工累加保键序, 供快照逐字节比对
        for r in rows:                                                                              # 逐条累加两张直方图: 键序由出现顺序决定
            levels[r.get("level", "info")] = levels.get(r.get("level", "info"), 0) + 1
            events[r.get("event", "?")] = events.get(r.get("event", "?"), 0) + 1
        return {
            "task_id": task_id,
            "found": True,
            "events": len(rows),
            "first_ts": rows[0]["ts"],
            "last_ts": rows[-1]["ts"],
            "levels": levels,
            "event_counts": events,
            "has_error": levels.get("error", 0) > 0,
            "last_message": rows[-1].get("message", ""),
        }

    def problems(self, n: int = 20) -> list[dict[str, Any]]:
        """全部 warn/error 事件按时间序 (问题定位第一视图)。

        Args:
            n: 只回最后 n 条; ``0`` 表示不限 (供下游全量消费)。

        Returns:
            事件 dict 列表, 按文件追加序 (= 时间序)。**不抛异常**:
            这是排障入口, 自身出错会让排障路径也断掉。
        """
        # 白名单两个等级而非 "level != info": 将来新增 debug 级时
        # 不会把海量调试噪声卷进问题视图。
        rows = [r for r in self.tail(n=0) if r.get("level") in ("warn", "error")]  # 白名单两等级: 将来新增 debug 级不会把噪声卷进问题视图
        return rows[-n:] if n > 0 else rows


def fmt_record(rec: dict[str, Any]) -> str:
    """单条事件的人类可读行 (CLI 用)。

    Args:
        rec: :meth:`TaskLogger.log` 返回或读回的事件字典; 缺字段一律
            用默认值兜底, 半行残留也能渲染出可读行。

    Returns:
        单行字符串 (不含换行符)。字段定宽对齐, 是为了让 ``tail``
        在终端里能竖着扫读。
    """
    # 只显示时分秒: 排障关心的是同一次运行内的相对顺序, 跨日对比
    # 交给日志文件本身的时间戳。
    ts = time.strftime("%H:%M:%S", time.localtime(rec.get("ts", 0)))  # 只显示时分秒: 排障关心的是同一次运行内的相对顺序
    data = rec.get("data")
    if isinstance(data, dict):                                                                      # 字典载荷走结构化渲染: 键名要能一眼看出
        data_s = " " + json.dumps(data, ensure_ascii=False, default=str)[:120]
    else:
        data_s = f" {data[:120]}" if data else ""
    return (f"{ts} [{rec.get('level', 'info'):5s}] {rec.get('task_id', '?'):28s} "
            f"{rec.get('event', '?'):10s} {rec.get('message', '')}{data_s}")


def fmt_records(rows: Iterable[dict[str, Any]]) -> str:
    """多行渲染 (CLI log 子命令)。

    Args:
        rows: 事件字典的可迭代对象 (通常是 tail/problems 的返回)。

    Returns:
        以换行拼接的多行字符串; **空输入返回空串** (不产生孤零零的
        换行), CLI 侧因此不会多打一个空行。
    """
    return "\n".join(fmt_record(r) for r in rows)  # 空输入得空串而非单个换行: CLI 不会因此多打一个空行
