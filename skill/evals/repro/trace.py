# -*- coding: utf-8 -*-
"""evals.repro.trace — E6 端到端 trace 读写 / 脱敏 / 完整性校验 (一等产物)。

能力边界: 一条 trace = 一个 JSONL 文件 (一行一事件)。写入前强制脱敏
(凭据原文/URL token 参数 → 占位); 写后校验完整性 (seq 连续 / 事件配对 /
final_answer 必在 / 凭据复扫)。边界: 只记录不评判 — 归因是 attribution.py
的活; 事件 schema 的唯一权威是 trace.schema.json (与本文件同目录)。

白盒锚点: docs/eval-E6-reproducibility.md §4 (trace 规格/脱敏/归因);
trace.schema.json (event_header 必填字段与 payload_by_type)。

职责: E6 的一等产物 —— trace 的写入 (自动补事件头 + 强制脱敏)、读取与
  完整性校验, 让"这次运行为什么这么跑"变成可事后复核的证据链, 而不是
  只能靠重跑一次来猜。
所属实验: E6 可复现与效率 (32 任务 + R0 路实跑); 规格真值是
  docs/eval-E6-reproducibility.md §4, 字段级权威是同目录的
  trace.schema.json (本文件的必填清单是它的摘要, 不是第二套定义)。
对外接口: redact / payload_fingerprint 两个纯函数; TraceWriter (上下文
  管理器, .emit 写事件); read_trace 读回 JSONL; validate_trace 返回
  阻断项列表 (空列表 = 完整)。
依赖与数据流: 输入 = 被测链路的事件 (类型 + payload) 与一个 JSONL
  文件路径; 产物 = temp/ 下的 trace 文件 (gitignored) 与校验结论字符串,
  结论供 evals/repro/run_e6.py 汇总, 本模块自身不做判定。
关键契约与不变量: 脱敏在序列化**之前**强制执行且不可关闭 — 凭据原文一旦
  落盘就等于泄漏, 事后补救不可能; 校验只报不修, 同一份 trace 重复校验
  必须得到同一条阻断项列表, 这是评审对照的前提; 零跨实验 import, 上游
  只有标准库, 与其它实验的等价性由 evals/equivalence/ 的断言守护。
陷阱与边界: payload_fp 必须复算而不只看字段在不在 —— 写了指纹却不验,
  等于对纯内容篡改完全不设防 (D-2 修复)。成本一致性检查同理: 有工具
  调用却上报 http_requests=0, 不是"这个任务省了请求"而是成本造假
  (TI-4)。这两条都是"字段合法但语义荒谬"的挡箭牌, 别当成冗余。
"""
from __future__ import annotations

# 标准库: 时间 (utc/mono) / JSON / 正则 (脱敏) / 哈希 (payload_fp) / 路径
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# 脱敏红线词 (schema redaction.forbidden; 命中即阻断)
FORBIDDEN_TOKENS = ("BEST_API_TOKEN", "Authorization", "Cookie",  # 命中即抛, 不是替换
                    "access_token", "refresh_token")
_URL_TOKEN_RE = re.compile(r"([?&](?:token|api_key|apikey|access_token|auth)=)[^&]*", re.I)  # 只抹值, 留参数名
HEADER_REQUIRED = ("seq", "ts_utc", "ts_mono", "run_id", "task_id", "attempt",  # 必填事件头, 缺一即阻断
                   "parent_seq", "layer", "type", "payload", "payload_fp")
EVENT_TYPES = ("run_start", "model_request", "model_response", "tool_call",  # 封闭类型集, 集外的名字拒写
               "tool_result", "error", "retry", "clarification",
               "final_answer", "run_end")
PAYLOAD_REQUIRED = {  # 每类事件的必填载荷字段 (schema 摘要, 非第二套定义)
    "run_start": ("manifest",),
    "model_request": ("model_id", "temperature", "seed", "prompt_fp", "messages_fp", "schema_fp"),
    "model_response": ("raw_fp", "latency_s", "finish_reason"),
    "tool_call": ("tool", "args", "args_norm", "args_fp"),
    "tool_result": ("envelope_fp", "status", "cost", "provenance"),
    "error": ("layer", "error_code", "is_retryable"),
    "retry": ("retry_of_seq", "reason", "strategy_changed"),
    "clarification": ("missing_dims", "options", "turn_index"),
    "final_answer": ("answer_fp", "conclusion_card"),
    "run_end": ("total_requests", "total_elapsed_s", "outcome"),
}


def redact(text: Any) -> Any:
    """脱敏: 递归扫描字符串 — 凭据词出现即抛, URL token 参数值替换 ***。

    Args:
        text: 任意待脱敏对象 (字符串/字典/列表/标量, 递归处理)。

    Returns:
        结构与入参同形的新对象, 字符串里的 URL token 参数值已被替换。

    Raises:
        ValueError: 出现凭据原文 (脱敏红线, 写入即阻断)。
    """
    if isinstance(text, dict):  # 递归三形态: dict/list/str, 其余原样放行
        return {key: redact(value) for key, value in text.items()}
    if isinstance(text, list):                                                              # 列表与 dict 同走递归: 嵌套在数组里的凭据一样要拦
        return [redact(item) for item in text]
    if not isinstance(text, str):  # 标量 (int/bool/None) 没有可脱敏的字符
        return text
    # 凭据走"抛"而不是"替换": 替换后原文仍在调用方的内存里, 下一次落盘
    # 换个字段就可能绕过, 宁可当场失败也不给漏网的路径
    for token in FORBIDDEN_TOKENS:                                                           # 逐个凭据原文扫: 名单是封闭集, 命中即中止而不是替换
        if token in text:                                                               # 子串匹配就够: 凭据一旦出现就是红线, 不必判断它是不是独立字段
            raise ValueError(f"trace 脱敏红线: 出现凭据原文 {token}")  # 落盘前中止: 写进去就等于泄漏
    # token 类参数只替换值、保留参数名: 保留名字才能让读者看出"这里原本
    # 有个被抹掉的凭据", 整段抹掉会让缺失看起来像从未传过
    return _URL_TOKEN_RE.sub(r"\1***", text)


def payload_fingerprint(payload: dict) -> str:
    """规范化 payload 的内容指纹 (键排序 JSON 的 sha256, 跨 run 比对用)。

    作用: 给出与键序、空白无关的内容指纹。关键参数 payload 是已脱敏的
    事件载荷。Returns: "sha256:" 前缀的十六进制串。抛什么: 不抛,
    不可序列化对象由 default=str 兜底成字符串再算。
    """
    # sort_keys 是关键: 同一个 payload 由不同代码路径构造出的键序可能不同,
    # 不排序就会算出两个指纹, 跨 run 比对立刻失效
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)  # 键排序后序列化: 同一载荷由不同代码路径构造出的键序不同, 不排序会算出两个指纹
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()  # 前缀标出算法, 换算法时旧指纹不会混淆


class TraceWriter:
    """JSONL trace 写入器: 自动补 seq/时间戳/payload_fp, 落盘前脱敏。

    用法::

        with TraceWriter(path, run_id="run-001", task_id="REPRO-04") as tw:
            tw.emit("run_start", {"manifest": {...}}, layer="harness")
            tw.emit("tool_call", {...}, layer="tool")
    """

    def __init__(self, path: Path, run_id: str, task_id: str) -> None:
        """记住目标文件与运行标识 (seq 从 0 起, attempt 默认 1)。

        作用: 绑定一次运行的 trace 落点。关键参数 path/run_id/task_id 是
        目标文件与两个标识。Returns: None。抛什么: 不抛, 真正的建目录与
        开文件推迟到 __enter__。
        """
        self.path = Path(path)  # 只记路径: 建目录与开文件都推迟到 __enter__
        self.run_id = run_id                                                           # 原样保存: run_id 会进事件头, 被改写就分不清是哪一次运行
        self.task_id = task_id                                                          # 同理: task_id 是归因表的分组键, 不可在写入侧做规范化
        # seq 从 0 起且只增: 校验靠它判断号, 中途重置会让前半段轨迹永远
        # 看起来缺号
        self.seq = 0                                                                  # 从 0 起且只增: 校验靠它判号, 中途重置会让前半段永远看起来缺号
        # 单调钟基准: ts_mono 必须相对同一基准, 否则跨进程混写时
        # monotonic 的绝对值不可比
        self._t0 = time.monotonic()                                                   # 单调钟基准: ts_mono 全部相对它, 跨进程混写时绝对值不可比
        self._handle = None  # 未进上下文的标记: emit 据此报明确错而非 AttributeError

    def __enter__(self) -> "TraceWriter":
        """开文件 (UTF-8, 追加模式 — 轨迹只增不改)。

        作用: 建立写入通道。关键参数: 无。Returns: 自身, 供 with 绑定。
        抛什么: 路径不可写时由 open 自抛。
        """
        # 递归建目录: 运行器可能按 run_id/task_id 分多级目录落盘, 让调用方
        # 先建目录等于把目录布局知识外泄给每个调用点
        self.path.parent.mkdir(parents=True, exist_ok=True)                            # 递归建目录: 目录布局是运行器的知识, 推给每个调用点等于把它外泄
        # 追加而非覆盖: 同名文件已存在说明上一次运行没写完, 静默覆盖会
        # 让残缺的那次运行看起来是完整跑完的
        self._handle = self.path.open("a", encoding="utf-8")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """关文件 (异常继续向外传播 — 写坏一半好过静默丢)。

        作用: 释放句柄。关键参数 exc_type/exc_val/exc_tb 是 with 协议
        传入的异常三件套, 本实现刻意不消费它们, 只用来保证关完仍原样外抛。
        Returns: None (返回 None 即不吞异常)。抛什么: 不抛。
        """
        if self._handle is not None:                                                # 判空再关: 重复退出或未进入上下文时不该抛 AttributeError
            self._handle.close()  # 先关再置 None: 异常路径下重复 __exit__ 也不会二次 close
            self._handle = None                                                       # 关完置 None: 留着句柄会让二次退出重复 close 同一个句柄

    def emit(self, event_type: str, payload: dict, *, layer: str = "harness",
             attempt: int = 1, parent_seq: Optional[int] = None) -> dict:                # attempt 默认 1: 根事件本就无重试, 显式传入才覆盖
        """写一个事件 (自动补事件头五件套; 脱敏在序列化前强制执行)。

        Returns:
            实际写入的事件 dict (含自动补的头字段)。

        Raises:
            ValueError: 事件类型未知 / payload 缺必填 / 脱敏命中凭据。
        """
        if event_type not in EVENT_TYPES:  # 封闭集: 拼错的名字当场拒, 不进轨迹
            raise ValueError(f"未知事件类型: {event_type!r}")
        # 脱敏先于必填校验: 先校验字段再脱敏的话, 一次缺字段就绕过脱敏,
        # 缺字段事件里的凭据就会跟着异常堆栈进日志
        safe_payload = redact(payload)                                                  # 脱敏先于必填校验: 反过来会让缺字段事件里的凭据随异常堆栈进日志
        missing = [k for k in PAYLOAD_REQUIRED[event_type] if k not in safe_payload]  # 必填校验跑在脱敏之后
        if missing:                                                                    # 缺字段当场拒: 头字段与必填不齐的轨迹, 等到校验阶段才发现就太晚
            raise ValueError(f"{event_type} payload 缺必填字段: {missing}")
        # 事件头在此处补齐, 不要求调用方自己填: 手工填就会有人漏, 而漏掉的
        # 头字段只有等到 validate_trace 才被发现, 代价是整轮跑完才发现
        event = {                                                                         # 头字段在此补齐: 要求调用方自己填, 漏填要等整轮跑完才暴露
            "seq": self.seq,
            # UTC + 微秒 + Z: 带时区信息, 否则跨时区汇总时序会错位
            "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            # 相对基准的秒数, 保留 6 位小数: 时延指标 (EF7) 读的是它,
            # 舍掉尾数会在毫秒级调用上全变成 0
            "ts_mono": round(time.monotonic() - self._t0, 6),
            "run_id": self.run_id,
            "task_id": self.task_id,
            "attempt": attempt,
            "parent_seq": parent_seq,  # 可空: 根事件没有父, 校验不拿它当非空必填
            "layer": layer,
            "type": event_type,
            "payload": safe_payload,
            # 指纹算在脱敏之后: 校验侧复算用的也是脱敏后的载荷, 两边
            # 口径必须一致, 否则每次校验都会报不匹配
            "payload_fp": payload_fingerprint(safe_payload),
        }
        if self._handle is None:                                                 # 误用报明确错: AttributeError 会被当成内部故障, 掩盖真实原因
            # 明确报错优于 AttributeError: None 句柄是误用, 不是内部故障
            raise RuntimeError("TraceWriter 未进入上下文 (用 with 进入)")  # 误用要报得明确
        # 每事件一行 JSONL: 进程中途被杀时已写部分仍可读, 这是选 JSONL
        # 而非单个 JSON 数组的唯一理由
        self._handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        # 立即 flush: 崩溃后可读的代价是每事件一次写系统调用, 跑批规模
        # (32 任务 × N 次) 完全可以承受
        self._handle.flush()                                                        # 每事件 flush: 崩溃后已写部分仍可读, 代价是每事件一次写系统调用
        self.seq += 1  # 写成功才自增: 写失败时断号能被校验抓到
        return event


def read_trace(path: Path) -> list[dict]:
    """读一个 JSONL trace → 事件列表 (坏行即抛 — 不静默跳过)。

    作用: 把落盘的轨迹读回内存。关键参数 path 是 trace 文件路径。
    Returns: 事件字典列表; 空行被跳过。抛什么: 坏行时由 json.loads 抛
    JSONDecodeError —— 跳过坏行会让半截轨迹看起来完整, 那正是校验要拦的。
    """
    events = []  # 顺序即落盘顺序: 后续所有校验都按下标判定
    for line in Path(path).read_text(encoding="utf-8").splitlines():  # 整读: trace 规模在 MB 级
        # 只跳空行: 轨迹末尾的换行会被 splitlines 留下空串, 但任何非空的
        # 坏行都让读取直接失败
        if line.strip():                                                                 # 只跳空行: 末尾换行会留空串, 任何非空的坏行都让读取直接失败
            events.append(json.loads(line))                                             # 不容错解析: 跳过坏行会让半截轨迹看起来完整, 那正是校验要拦的
    return events


def validate_trace(events: list[dict]) -> list[str]:
    """trace 完整性校验; 返回阻断项列表 (空 = 完整)。

    阻断项 (文档 §8.2 #6/#7): 头字段缺失 / seq 断号 / tool_call 与
    tool_result 不配对 / 缺 final_answer / 凭据复扫命中 /
    **payload_fp 不复算一致** (写了指纹却不验 = 纯内容篡改漏检) /
    **成本字段与调用记录矛盾** (tool_call>0 却 http_requests=0 = 成本造假)。
    """
    problems: list[str] = []  # 只报不修: 改过的轨迹分不清原样与修好
    # 空轨迹单列一种阻断项而不是当"没数据"放过: 空文件说明这次运行没写出
    # 任何东西, 与"跑了但事件全是空壳"是两种完全不同的故障
    if not events:                                                                  # 空轨迹单列阻断项: 空文件与「事件全是空壳」是两种故障, 不能都当没数据
        return ["trace_empty"]
    for index, event in enumerate(events):  # 下标即期望的 seq: 不采信事件自称
        # 逐事件逐字段查, 不做整体 schema 校验: 阻断项要带 seq 才定位得到
        for field in HEADER_REQUIRED:                                           # 逐事件逐字段查: 阻断项要带 seq 才定位得到, 不做整体 schema 校验
            if field not in event:                                                        # 缺即报: 头字段是全部下游校验的地基, 缺一个后面全都不可信
                problems.append(f"header_missing:{event.get('seq', index)}:{field}")  # 带 seq 才定位得到
        # seq 必须严格等于行序: 断号意味着中间有事件没落盘, 轨迹已经不完整
        if event.get("seq") != index:
            problems.append(f"seq_gap:expected_{index}_got_{event.get('seq')}")  # 报双向差值: 缺行还是重号
        etype = event.get("type")
        if etype in PAYLOAD_REQUIRED:  # 未知类型不在表内: 由 emit 的封闭集兜住
            for field in PAYLOAD_REQUIRED[etype]:                                          # 按事件类型取必填表: 不同类型载荷不同, 统一一张表会误报
                if field not in (event.get("payload") or {}):
                    problems.append(f"payload_missing:{etype}:{field}")
        # payload_fp 复核: emit 时算的指纹必须能重算出来 (D-2 修复)
        if "payload_fp" in event and "payload" in event:  # 两者都在才复算, 缺的由上面那条报
            expected = payload_fingerprint(event["payload"])  # 用当前载荷重算, 不信任已存的指纹
            if expected != event["payload_fp"]:  # 键序无关的纯内容篡改也逃不掉
                problems.append(f"payload_fp_mismatch:{event.get('seq', index)}")
    calls = sum(1 for e in events if e.get("type") == "tool_call")  # 配对校验的两个输入
    results = sum(1 for e in events if e.get("type") == "tool_result")
    # 配对数不等 = 有调用没回包: 要么链路中断, 要么有人手工删了行, 两种
    # 都让"这次运行的结论"无从追溯
    if calls != results:                                                                  # 配对数不等即阻断: 有调用没回包, 这次运行的结论就无从追溯
        problems.append(f"tool_pairing:{calls}calls_vs_{results}results")
    if not any(e.get("type") == "final_answer" for e in events):  # 没给结论: 无从谈可用与可复现
        problems.append("final_answer_missing")
    # 成本字段一致性: 有工具调用却上报 0 请求 = 成本造假 (TI-4 的独立检测器;
    # cost 挂在 tool_result payload 上 — schema 的 required 字段)
    if calls > 0:                                                                      # 只在确有调用时查成本: 没有调用就不存在「报了 0 请求」这种谎报
        for event in events:                                                               # 全量扫回包: 成本挂在回包载荷上, 只看第一条会漏掉后面的
            if event.get("type") != "tool_result":
                continue
            reported = (event.get("payload") or {}).get("cost", {}).get("http_requests")  # cost 挂在回包载荷上
            # 只抓恰好为 0: 字段缺失 (缺省 None) 与"有值但为 0"是两回事 ——
            # 前者是没报成本, 由上面的 payload_missing 兜; 后者是谎报
            if reported == 0:                                                        # 只抓恰好为 0: 字段缺失是另一类问题, 由必填校验兜, 不在这里混报
                problems.append(                                                        # 报第一处即止: 同一现象会在每个回包重复出现, 全报会淹没真问题
                    f"cost_inconsistent:{event.get('seq')}:tool_calls_{calls}_but_requests_0")
                # 只报第一处: 同一现象会在每个 tool_result 上重复出现, 全报
                # 会把一条真问题淹没在几十条重复里
                break
    # 全量复扫凭据: 脱敏在写入侧已强制过一次, 这里是第二道 — 防有人绕过
    # TraceWriter 直接改文件, 也防写入侧规则日后被放宽
    try:
        redact(events)  # 第二道全量复扫: 绕开写入侧或规则被放宽都能抓住
    except ValueError as exc:
        problems.append(f"credential_leak:{exc}")  # 带上原异常: 泄漏哪个词必须可读
    return problems  # 空列表 = 完整; 非空即阻断, 顺序即发现顺序
