"""src.download_hooks — 下载问题 hook 层 (分级策略 + ask 载荷)。

能力边界: HookPolicy (分级: 网络类自动重试, 严重类立即拦截) + HookInterrupt
(拦截异常, 载荷含原因/证据/建议方案, 供调用方 ask 用户) + DownloadHooks
(注册表 + 拦截点执行)。边界: 本层只判定与拦截, 不做用户交互 — ask 由调用方
(CLI/agent/GUI) 执行; 后台任务被拦截时置 blocked 并写进度文件 (fail-closed,
绝不静默继续)。
白盒锚点: references/ALGORITHM-SPEC.md §2 (download_hooks 锚点)。

分级策略 (经用户批准):
  network 类 (连接失败/超时/429/5xx): 指数退避自动重试 ≤ max_retries,
    仍失败才升级为 HookInterrupt;
  severe 类 (校验失败/磁盘写入失败/会话过期/分页不一致): 立即 HookInterrupt,
    不重试 (重试无意义或危险)。
每次 HookInterrupt 必须携带 ask 载荷 (reason + evidence + options),
调用方必须向用户 ask 一次 (说明原因 + 询问意见), 严禁静默跳过。

非幂等闭包的护栏 (``run_network(retry_guard=...)``): 闭包里含 POST 建会话
时, 调用方传一个"会话是否已落断点"的判据; 判据为假即**不重发**该闭包,
改走 :data:`POST_NOT_RETRIED` 拦截 (带真实状态码 + 可操作提示)。重发
phase-1 POST 会在服务端多建 sqlid 会话 (前一个成孤儿, 泄漏查询配额)。
"""

from __future__ import annotations

import logging  # 日志出口: 库内一律走模块 logger, 不污染 root
import time  # time.sleep 即指数退避的等待落点
from dataclasses import dataclass, field  # HookInterrupt / HookPolicy 的载体
from typing import Any, Callable  # 观察者回调的协议标注

import requests  # 只取异常层级: P2-4 起按类引用 + isinstance 覆盖全部子类

logger = logging.getLogger(__name__)  # hook 层的 warn/exception 都汇到这里

# ---- 问题分类 (hook 判据) ---------------------------------------------------

# 网络类: 瞬时/可重试 (P2-4: 类引用 + isinstance 判定, 不按类名字符串匹配)。
# 按类名字符串匹配会漏掉 ConnectTimeout (requests 中它同时继承
# ConnectionError+Timeout, 但类名不在元组里)、SSLError、ProxyError、
# RetryError, 最常见的网络故障反而不重试。
# 类引用 + isinstance 自动覆盖全部子类 (ConnectTimeout/ReadTimeout 等)。
NETWORK_ERRORS = (  # 元组内每个类都是一次重试的准入条件, 少一个就少一类重试
    requests.exceptions.ConnectionError,                                                            # 连接类异常: 可重试
    requests.exceptions.Timeout,                                                                    # 超时: 可重试
    requests.exceptions.ChunkedEncodingError,                                                       # 分块编码错: 传输层被截断, 重试有意义
    requests.exceptions.SSLError,                                                         # SSL 错: 通常是环境问题, 但交给策略层判定而非这里拍板
    requests.exceptions.ProxyError,                                                                 # 代理错
    requests.exceptions.RetryError,                                                                 # 重试耗尽: 交给策略层看还剩几次
)
RATE_LIMIT_STATUS = 429  # 只认 429 作限流: 503 留给真故障, 混用会失去区分度
SERVER_ERROR_RANGE = (500, 600)  # 半开区间, 免得 600+ 这类非标准码漏判


def extract_status_code(obj: Any) -> int | None:
    """从响应对象 / 异常实例里取真实 HTTP 状态码 (取不到给 None, 不猜)。

    存在的理由 (A3-04 实测): requests 的 ``HTTPError`` **没有**
    ``status_code`` 属性 —— ``getattr(exc, "status_code", None)`` 恒为
    None, 码挂在 ``exc.response.status_code`` 上。只查 ``.status_code``
    的话, 429/5xx 这两类最该分级的错误永远走"取不到码"分支, 退避与
    服务端错误分类形同虚设。

    Args:
        obj: 响应对象、异常实例, 或任何可能带状态码的返回值 (``fn()`` 的
            返回值也走这里: 有的封装不抛异常而是回一个带 ``status_code``
            的对象)。

    Returns:
        状态码整数; 四个来源 (自身 ``status_code`` / 自身 ``status`` /
        ``response.status_code`` / ``response.status``) 都取不到时返回
        ``None`` —— 调用方据此走"无状态码"分支, 绝不把 None 当 0 参与比较。
    """
    for holder in (obj, getattr(obj, "response", None)):  # 异常自身与它挂的 response 各试一轮
        if holder is None:  # 没有 response (纯超时等) 只剩自身一轮
            continue
        for attr in ("status_code", "status"):  # 两个名字都查: 自定义封装与替身用哪个的都有
            value = getattr(holder, attr, None)
            # bool 是 int 的子类, 排除掉: True 当状态码会让 5xx 判定失去意义
            if isinstance(value, int) and not isinstance(value, bool):
                return value
    return None  # 取不到就是取不到: 返回 None 让调用方走"无状态码"分支

# 严重类: 立即拦截 (重试无意义或有数据损坏风险)
SEVERE_CHECKSUM = "checksum_mismatch"  # 校验和不符: 产物已损坏, 重试前须处置半成品
SEVERE_DISK = "disk_write_failed"  # 落盘失败: 权限/空间/路径问题, 原样重试同样会失败
SEVERE_SESSION = "session_expired"  # 查询会话失效: 须重建 sqlid, 续用旧会话必失败
SEVERE_PAGINATION = "pagination_inconsistent"  # 分页口径前后不一致: 再拉只会拿到错数据
SEVERE_PATH = "path_traversal"  # 越出 skill 根: 安全问题, 绝不自动放行
SEVERE_EMPTY_PRECISE = "empty_precise_result"  # 精准下载零命中: 属输入问题, 不是站点故障
SEVERE_PRECISE_TOO_LARGE = "precise_id_list_too_large"  # ID 表超上限: 改分批或换通道

# 严重类白盒集合: severe() 只认这里的成员, 传别的即编程错误 (ValueError)
SEVERE_KINDS = (SEVERE_CHECKSUM, SEVERE_DISK, SEVERE_SESSION,
                SEVERE_PAGINATION, SEVERE_PATH, SEVERE_EMPTY_PRECISE,
                SEVERE_PRECISE_TOO_LARGE)

# 非幂等阶段失败: 不重发, 如实上报 (刻意**不**属 SEVERE_KINDS —— 它不是数据
# 损坏, 而是"该由用户决定何时再发一次"; 但同样必抛 HookInterrupt 走 ask,
# 绝不允许静默降级成一次自动重试或一次无声失败)。
POST_NOT_RETRIED = "post_not_retried"

# 精准下载 ID 上限提示值 (option 文案用; 真值在 src.download_precise,
# 此处只 import 失败时也要有合理文案 — 用字面量避免循环依赖)
MAX_PRECISE_IDS_HINT = 1000  # 字面量而非 import: 成环的是 download_precise 反向
    # import 本模块, 从这里 import 真值只会把环坐实


@dataclass
class HookInterrupt:
    """hook 拦截载荷 (ask 用户的结构化依据)。

    Attributes:
        kind: 问题类别 (SEVERE_* 或 "network_exhausted")
        reason: 人类可读原因 (一句话)
        evidence: 证据字典 (job_id/attempts/status_code/exception/checksum 等)
        options: 建议方案列表 (至少 2 个, 含推荐项)
        job_id: 关联任务
    """
    kind: str  # 命中 _OPTION_TEMPLATES 的键, 也是 ask 载荷的 id 后缀
    reason: str  # 面向用户的一句话, 让人不看日志也能判断该不该继续
    evidence: dict[str, Any] = field(default_factory=dict)  # 证据随载荷走, 不依赖调用方再查日志
    options: list[dict[str, Any]] = field(default_factory=list)  # 每类至少 2 个, 含推荐项
    job_id: str = ""  # 供进度文件/任务管理器把拦截对回具体任务

    def to_ask_payload(self) -> dict[str, Any]:
        """转为 ask_user_question 可直接消费的载荷 (id/question/options)。

        同时附 ``raw`` (HookInterrupt 原始字段), 供 result()/GUI 无损重建。
        """
        return {
            "id": f"hook_{self.kind}",  # 同一 kind 的两次 ask 会得到同一 id, 便于 UI 归并
            "question": f"[下载拦截:{self.kind}] {self.reason}\n证据:{self._fmt_evidence()}",
            "options": self.options or [  # 模板表没覆盖的 kind 才落到这份兜底选项
                {"label": "重试该任务", "description": "按原参数重试一次"},
                {"label": "跳过该任务", "description": "标记失败并继续其他任务"},
            ],
            "raw": {  # 无损通道: GUI/result 靠它重建对象, 不必反解 question 文本
                "kind": self.kind,
                "reason": self.reason,
                "evidence": self.evidence,
                "job_id": self.job_id,
            },
        }

    def _fmt_evidence(self) -> str:
        """证据字典压成单行 (每项截 80 字符, 防 ask 载荷过长刷屏)。

        Returns:
            ``k=v; k=v`` 形态的单行摘要; 证据为空时返回 ``"(无)"``
            占位而非空串, 免得 ask 载荷里出现"原因：原因为空"的空提示。
        """
        parts = []                                                                                  # 证据拼串
        for k, v in self.evidence.items():                                                          # 逐项
            s = str(v)                                                                              # 统一转字符串: 证据值可能是异常对象
            # 每项独立截断而非整串截断: 整串截会只留下第一个键的值,
            # 后面真正有诊断价值的信息全丢。
            parts.append(f"{k}={s[:80]}")
        return "; ".join(parts) if parts else "(无)"  # 空证据给占位符, 不给空串


class HookBlockedError(Exception):
    """hook 拦截异常 (前台调用方捕获后必须 ask 用户)。

    语义: 这是**控制流 + 用户决策**信号, 不是故障 — 任务数据本身
    完好, 停在这里等用户选方案。故它与 RuntimeError 分开: 上层
    对前者必须转成 ask 交互, 对后者只报失败。

    ``interrupt`` 属性保留原对象, 使 catch 到异常后仍能拿回完整
    kind/reason/evidence/options, 无需从异常消息里反解。
    """

    def __init__(self, interrupt: HookInterrupt) -> None:
        """包装 HookInterrupt 为异常 (interrupt 原样挂在实例上供重建)。"""
        self.interrupt = interrupt  # 挂原对象: 捕获方不必从消息文本反解字段
        super().__init__(f"hook blocked [{interrupt.kind}]: {interrupt.reason}")


@dataclass
class HookPolicy:
    """分级 hook 策略 (可配置)。

    Attributes:
        max_retries: 网络类自动重试上限 (默认 3, 指数退避 base*2^k)
        retry_base_sec: 退避基数 (默认 2.0, 尊重官网礼貌限速)
        ask_on_network_exhausted: 网络类重试耗尽后是否 ask (默认 True)
        ask_on_severe: 严重类是否 ask (默认 True; False 时直接 raise 普通异常)
    """
    max_retries: int = 3  # 退避总轮数上限, 不含首次尝试
    retry_base_sec: float = 2.0  # 基数: 官网礼貌限速, 不做成压测式紧循环
    ask_on_network_exhausted: bool = True  # 耗尽后是否 ask; False 时直接 RuntimeError
    ask_on_severe: bool = True  # 严重类是否 ask; False 时直接 RuntimeError

    def is_rate_limited(self, status_code: int) -> bool:
        """是否限流状态 (HTTP 429)。

        Args:
            status_code: HTTP 响应状态码。

        Returns:
            恰为 429 时 True。**只认 429**: 上游偶尔用 503 表达限流,
            但 503 同时是真实服务故障, 混入会让重试策略失去区分度。
        """
        return status_code == RATE_LIMIT_STATUS

    def is_server_error(self, status_code: int) -> bool:
        """是否服务端错误状态 (5xx)。

        Args:
            status_code: HTTP 响应状态码。

        Returns:
            落在半开区间 ``[500, 600)`` 时 True — 用半开区间而非
            闭区间 599, 免得 600+ 这类非标准码漏判。
        """
        return SERVER_ERROR_RANGE[0] <= status_code < SERVER_ERROR_RANGE[1]

    def is_network_error(self, exc: BaseException) -> bool:
        """是否网络类异常 (连接失败/超时/分块编码错误)。

        P2-4: isinstance 判定 (含子类) — ConnectTimeout 是
        ConnectionError+Timeout 的子类, 按类名匹配会漏掉它。
        """
        return isinstance(exc, NETWORK_ERRORS)


DEFAULT_POLICY = HookPolicy()  # 缺省分级策略: 网络类指数退避重试, 严重类即拦即 ask

# 建议方案模板 (按 kind 给出可操作选项, 调用方可覆盖)
_OPTION_TEMPLATES: dict[str, list[dict[str, Any]]] = {  # 每类 severe 至少 2 项, 供 ask 呈现
    SEVERE_CHECKSUM: [
        {"label": "重新下载该任务", "description": "丢弃半成品, 从第 1 页重新拉取"},
        {"label": "保留半成品并标记 failed", "description": "文件留在磁盘供检查, 任务记失败"},
    ],
    SEVERE_DISK: [
        {"label": "清理空间后重试", "description": "释放磁盘空间 (含旧 .progress/.checkpoints) 后重试"},
        {"label": "更换输出目录重试", "description": "指定其它 output_dir 重新提交"},
    ],
    SEVERE_SESSION: [
        {"label": "重建查询会话", "description": "重新 POST /q 取新 sqlid 后续传"},
        {"label": "终止任务", "description": "放弃该任务, 记录原因"},
    ],
    SEVERE_PAGINATION: [
        {"label": "从断点页重试", "description": "按 checkpoint 的 next_page 继续"},
        {"label": "整任务重下", "description": "丢弃 checkpoint 从第 1 页开始"},
    ],
    SEVERE_PATH: [
        {"label": "更换合法文件名", "description": "使用不含目录成分的文件名重试"},
        # 每类 severe 至少 2 个建议方案是 ask 铁律 (文档与 HookInterrupt
        # docstring 同承诺): 少于 2 个时 ask 无从让用户做选择。
        {"label": "改用系统自动命名", "description": "不指定文件名, 由下载栈按 (星表,天区,半径,格式) 生成确定性唯一名"},
    ],
    SEVERE_EMPTY_PRECISE: [
        {"label": "核对 ID 与星表", "description": "确认 source_id 属于该星表 (如 gaia_dr3_18 而非 gaia_dr3), 修正后重试"},
        {"label": "改用坐标 proximity 上传", "description": "有坐标列表时改用服务端批量坐标匹配, 不依赖 ID 精确匹配"},
    ],
    SEVERE_PRECISE_TOO_LARGE: [
        {"label": "分批精准下载", "description": f"按 ≤{MAX_PRECISE_IDS_HINT} 个 ID 分批提交, 分别落盘后合并"},
        {"label": "改用 proximity 坐标上传", "description": "ID 过多时改用坐标列表服务端匹配 (单文件建议 <1000 万源)"},
    ],
    "network_exhausted": [
        {"label": "退避后重试", "description": "等待更长时间 (rate_limit*2^k) 后重试"},
        {"label": "稍后手动重试", "description": "任务记 failed, 稍后 resume"},
    ],
    POST_NOT_RETRIED: [
        {"label": "稍后手动重试", "description": "等站点限流窗口过去后重新提交 (本层不会自动重发, 避免多建孤儿会话)"},
        {"label": "终止任务", "description": "放弃该任务, 状态码与证据已留在进度文件与任务日志里"},
    ],
}


class DownloadHooks:
    """下载 hook 注册表: 分级判定 + 拦截 + ask 载荷构造。

    用法:
        hooks = DownloadHooks(policy=HookPolicy(max_retries=3))
        try:
            hooks.run_network(lambda: client.fetch_page(...), job_id="j1")
        except HookBlockedError as e:
            ask(e.interrupt.to_ask_payload())   # 调用方必须 ask
    """

    def __init__(self, policy: HookPolicy | None = None) -> None:
        """构造 hook 注册表 (策略缺省用 DEFAULT_POLICY)。

        Args:
            policy: 分级策略; None 时用模块级 :data:`DEFAULT_POLICY`
                (网络类退避重试、严重类即拦即 ask)。

        观察者列表初始为空 — 须经 :meth:`on_interrupt` 显式注册,
        刻意不提供默认观察者, 避免构造就产生隐式副作用。
        """
        self.policy = policy or DEFAULT_POLICY  # 传 None 才用模块级缺省策略
        self._on_interrupt: list[Callable[[HookInterrupt], None]] = []  # 只增不删, 无注销句柄

    def on_interrupt(self, callback: Callable[[HookInterrupt], None]) -> None:
        """注册拦截观察者 (如进度追踪器置 blocked、管理器记 warn 日志)。

        Args:
            callback: 接收 :class:`HookInterrupt` 的可调用。

        只增不删、**不**去重也不返回注销句柄: 观察者数量是常数级
        (管理器两三个), 为此维护生命周期协议不值得; 观察者自身
        抛异常由 :meth:`_emit` 隔离, 注册方无需防御。
        """
        self._on_interrupt.append(callback)  # 顺序即广播顺序, 进度类观察者先注册即可先收到

    def _emit(self, interrupt: HookInterrupt) -> None:
        """广播拦截给全部观察者 (单个观察者炸掉不掩盖拦截本身)。

        Args:
            interrupt: 刚构造的拦截对象, 原样传给每个观察者。

        每个观察者独立 try/except: 记日志的观察者崩了不能连带
        置 blocked 的那个失效, 否则任务状态会永远停在 running。
        """
        for cb in self._on_interrupt:                                                               # 逐个回调通知中断
            try:
                cb(interrupt)                                                                      # 回调签名只有 interrupt 一个参数
            except Exception:  # noqa: BLE001 观察者异常不掩盖拦截
                logger.exception("hook observer failed")

    def _interrupt(self, kind: str, reason: str, evidence: dict[str, Any],
                   job_id: str) -> None:
        """分级出口: 先广播观察者, 再按策略决定抛什么 — 必抛, 不返回。

        顺序有讲究: 观察者先收到 (进度文件置 blocked、任务日志记 warn),
        调用方后拿到异常 — 反过来则 ask 载荷还没落盘, GUI 已经读不到。
        策略开关 (ask_on_severe / ask_on_network_exhausted) 只决定抛
        HookBlockedError (调用方必须 ask) 还是裸 RuntimeError (直接失败)。
        """
        interrupt = HookInterrupt(                                                                  # 中断对象: 一次性把上下文装齐
            kind=kind, reason=reason, evidence=evidence, job_id=job_id,                             # 种类/原因/证据/作业 id 都在这里
            options=[dict(o) for o in _OPTION_TEMPLATES.get(kind, [])],  # 浅拷贝: 模板可被调用方改
        )
        logger.warning("hook interrupt [%s] %s (%s)", kind, reason, job_id)  # 落 warn 级审计标记
        self._emit(interrupt)  # 先广播: 让进度文件先落 blocked 再抛
        if kind in SEVERE_KINDS and not self.policy.ask_on_severe:                                  # 严重级别且策略要求询问时, 才真的中断
            raise RuntimeError(f"download blocked [{kind}]: {reason}")  # 策略关掉 ask 就直接失败
        if kind == "network_exhausted" and not self.policy.ask_on_network_exhausted:
            raise RuntimeError(f"download failed [network]: {reason}")  # 网络类同口径降级
        if kind == POST_NOT_RETRIED and not self.policy.ask_on_network_exhausted:
            # 非幂等失败同口径降级: 关掉 ask 的调用方拿裸 RuntimeError, 但
            # 绝不因此改成"自动重发一次" —— 降级只降呈现, 不降礼仪约束。
            raise RuntimeError(f"download failed [post_not_retried]: {reason}")
        raise HookBlockedError(interrupt)  # 常态出口: 调用方捕获后必须 ask

    def run_network(self, fn: Callable[[], Any], job_id: str = "",
                    context: dict[str, Any] | None = None,
                    retry_guard: Callable[[], bool] | None = None) -> Any:
        """网络类操作: 指数退避重试, 耗尽才拦截。

        Args:
            fn: 执行网络操作的可调用 (抛 requests.RequestException 或返回
                带 status_code 的对象均可)
            job_id: 关联任务 (进 ask 载荷)
            context: 额外证据 (如 url)
            retry_guard: 非幂等闭包的护栏 —— 无参可调用, 返回 True 才允许
                再调一次 ``fn``; 返回 False 表示"重发这个闭包会重复执行非
                幂等请求", 此时**不重试**, 直接走 :data:`POST_NOT_RETRIED`
                拦截 (带真实状态码 + 可操作提示, 由调用方 ask 用户)。
                闭包纯幂等 (只发 GET) 时不给本参数, 退避重试照旧。

        Returns:
            fn() 的返回值

        Raises:
            HookBlockedError: 重试耗尽且策略要求 ask; 或护栏判定不可重发
        """
        attempts = 0                                                                                # 重试计数从零起
        last_exc: BaseException | None = None                                               # 最后一次异常: 耗尽重试时要抛它, 而不是抛一个泛化错误
        while attempts <= self.policy.max_retries:  # 上界含 max_retries 那一轮
            try:
                result = fn()                                                                       # 真正调用被包裹的函数
                # 有的网络封装不抛异常而是返回带 status_code 的对象:
                # 5xx/429 在此统一升级为 _StatusError, 走同一条重试分级
                status = extract_status_code(result)
                if status is not None and self.policy.is_server_error(status):                      # 服务端错误可重试
                    raise _StatusError(status)  # 5xx: 归一成异常才进统一 except
                if status is not None and self.policy.is_rate_limited(status):                      # 限流可重试
                    raise _StatusError(status)  # 429: 同样归一, 不另开分支
                return result
            except Exception as exc:  # noqa: BLE001 统一分级判定
                last_exc = exc                                                                      # 记住异常
                status = extract_status_code(exc)                                                 # 真实状态码: requests 的码在 .response 上
                # 可重试判定: requests 网络类异常, 或状态码 429/5xx —
                # 与 NETWORK_ERRORS/RATE_LIMIT_STATUS/SERVER_ERROR_RANGE 口径一致
                retryable = (                                                                       # 可重试判定: 网络错或限流/服务端错误
                    self.policy.is_network_error(exc)                                               # 网络类
                    or (status is not None and (                                                    # 有状态码时
                        self.policy.is_rate_limited(status)                                         # 限流
                        or self.policy.is_server_error(status)))                                    # 服务端错误
                )
                if not retryable:                                                                 # 不可重试就立刻抛: 无意义的重试只会拖慢失败
                    # 非网络类异常 (编程错误/控制流异常如 JobCancelledError/
                    # 严重类 hook) 原样穿透, 不包装成 network ask — 调用方
                    # 按自身语义处理。取消异常正是靠这条通道到达 _run 的。
                    raise
                if retry_guard is not None and not retry_guard():                                   # 护栏判否: 重发会重复非幂等请求
                    # 顺序在"配额用尽"之前: 哪怕还有重试次数, 护栏判否也一律
                    # 不重发 —— 少一次重试远好过服务端多一个孤儿会话。
                    self._interrupt(                                                                # 必抛: 走 ask 让用户决定何时手动重试
                        POST_NOT_RETRIED,
                        "非幂等请求 (建查询会话的 POST) 失败, 不自动重发以免在服务端"
                        "留下孤儿会话; 请稍后手动重试",
                        {"job_id": job_id, "attempts": attempts + 1,  # +1: 首轮也要计进证据
                         "status_code": status,  # 真实状态码: 取不到时为 None, 不填 0 冒充
                         "exception": f"{type(last_exc).__name__}: {last_exc}",
                         **(context or {})},
                        job_id,
                    )
                if attempts >= self.policy.max_retries:                                             # 超过上限即放弃
                    break  # 配额用尽: 跳出循环走 network_exhausted 拦截
                # 指数退避 base*2^k: 尊重官网礼貌限速, 也避免重试风暴
                # 把已经过载的服务端打得更死
                wait = self.policy.retry_base_sec * (2 ** attempts)                                 # 指数退避: 每次翻倍, 避免把站点打挂
                logger.info("network retry %d/%d after %.1fs (%s)",
                            attempts + 1, self.policy.max_retries, wait, exc)                   # 重试前先记一笔: 事后能看出重试了几次、等了多久
                time.sleep(wait)  # 真等待: 让服务端先缓过来再试
                attempts += 1                                                                       # 计数前进
        # 重试耗尽: 升级为 HookInterrupt (network_exhausted), 带 attempts
        # 与最后一次异常做证据 — _interrupt 必抛, 下行 AssertionError 不可达
        self._interrupt(                                                                            # 按策略决定是否中断作业
            "network_exhausted",
            f"网络操作重试 {self.policy.max_retries} 次后仍失败",
            {"job_id": job_id, "attempts": attempts + 1,  # +1: 首轮也要计进证据
             "status_code": extract_status_code(last_exc),  # 真实状态码 (可为空): 让 ask 载荷能直接答"服务端回了什么"
             "exception": f"{type(last_exc).__name__}: {last_exc}",
             **(context or {})},  # 调用方额外证据 (如 url) 合并进同一载荷
            job_id,                                                                                 # 作业 id 一并带上
        )
        raise AssertionError("unreachable")  # _interrupt 必抛

    def severe(self, kind: str, reason: str, evidence: dict[str, Any],
               job_id: str = "") -> None:
        """严重类问题: 立即拦截 (不重试 — 重试无意义或有数据损坏风险)。

        调用方捕获 HookBlockedError 后必须 ask 用户 (载荷见
        HookInterrupt.to_ask_payload)。kind 必须是 SEVERE_KINDS 成员,
        否则是编程错误, 抛 ValueError。
        """
        if kind not in SEVERE_KINDS:                                                                # 非严重级别不中断
            raise ValueError(f"unknown severe kind: {kind!r}")  # 早失败: 错 kind 不进 ask
        self._interrupt(kind, reason, evidence, job_id)  # 交给分级出口决定抛哪种


class _StatusError(Exception):
    """内部: 把非 2xx 状态码包装成可分级判定的异常。

    存在理由: 上层 (run_network) 的重试决策完全按**状态码**分支,
    而 requests 的异常对象取状态码要再翻一次 response, 且不同封装
    抛出的异常类型不一 (HTTPError/SSLError/自定义)。统一包一层后
    分级逻辑只认这一个类型, 不必解析异常消息文本。
    """

    def __init__(self, status_code: int) -> None:
        """用 HTTP 状态码构造内部异常, 供上层按状态码分级决策。

        Args:
            status_code: 触发的非 2xx 状态码 (如 404/416/500)。

        Note:
            单独包一层而不是直接抛 ``requests.HTTPError``: 上层只想按状态码
            分支 (404 记 not_found、416 判 Range 失效), 不想解析异常消息文本。
        """
        self.status_code = status_code  # 上层只读这个属性做分级, 不解析消息文本
        super().__init__(f"HTTP {status_code}")
