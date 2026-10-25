# -*- coding: utf-8 -*-
r"""evals.groundtruth.live_policy — 实跑纪律的**唯一真源** (对站点的礼仪)。

能力边界: 只管"打真实站点时的行为准则"—— 请求间隔、错误重试边界、产物落盘位置。
不负责查询语义 (那是 ``src.protocol``)、不负责结果判定 (那是 ``metrics``)。

为什么要有这个模块: 实跑纪律原先散在 ``CLAUDE.md`` 铁律 7 的散文里, 各跑批件
(E1–E6) 各自理解一遍。四条约束一旦有第二份实现, 就会有一处漏掉串行间隔或
重试 POST —— 而那两种漏法的代价不对称:

- **漏串行间隔**: 把星表站点当压力源打, 是对他人资源的冒犯, 不可逆。
- **漏"不重试 POST"**: phase-1 的表单提交会在服务端创建 sqlid 会话, 重试一次
  就多一个孤儿会话并泄漏一份查询配额。
- **产物落错地方**: 写进被跟踪文件会让 ``code_fingerprint`` / 树门禁变红, 而这
  与被测行为无关, 属于评测自己弄脏工作区。

所以四条在这里各落一个函数, 消费方一律 import, 不许自己 ``time.sleep`` 或
``open("w")``。

对外接口: :data:`RATE_LIMIT_SECONDS` (客户端限速值) / :func:`pace` (场景之间的
额外间隔) / :func:`read_only_retryable` (哪些错误可以重试) / :data:`ARTIFACT_DIR`
(实跑产物落点) / :class:`CountingSession` (请求计数, 透传不伪造) /
:func:`accounted_calls` (按协议契约给请求轨迹分类, M7 诚实性的独立声明侧)。

依赖: 只用标准库 + ``requests`` (后者只在 :class:`CountingSession` 真正建会话时
用到, 构造本模块不触网)。不 import 被测代码, 不读配置 —— 纪律必须是硬编码的
常量, 配置化等于"可以被人关掉"。
"""
from __future__ import annotations

# 标准库: 环境变量 (取仓根用) / 路径 / 类型标注
import os
import time
from pathlib import Path
from typing import Any

# 第三方: 仅 CountingSession 兜底建会话时用到 (不 import 它本模块也不会触网)
import requests  # noqa: E402  放在 typing 之后: 第三方块与本地块分开是本仓注释规范

# 客户端限速器取值: 铁律 7 (b) 要求串行且强制间隔。取 1.5 秒 —— 比站点侧任何
# 合理限速都保守。**不再归零**: 归零是回放时代的遗产, 打到真站点上等于
# 以最快速度重复提交表单。
RATE_LIMIT_SECONDS = 1.5

# 场景之间的额外间隔: 与客户端限速**叠加**。客户端限速只管"两次请求之间"，
# 这里管"两个场景之间" —— 后者要留够时间让站点喘口气, 因为场景往往连续发
# 三到五次请求。
SCENARIO_GAP_SECONDS = 1.5

# 实跑产物落点: temp/ 是铁律 3 的临时区且 gitignored。写到别处会让门禁误判为
# 代码变更 (实测踩过: `make evals-all` 每次跑完写脏两个被跟踪的 REPORT.md)。
ARTIFACT_DIR = Path(os.environ.get("ASTRO_BEST_LIVE_ARTIFACTS", "temp/live_runs"))


def pace(what: str = "") -> None:
    """在两个场景之间睡一个强制间隔, 并把这次等待打到 stderr 上。

    刻意**每次都睡**而不是"按需睡": 判据是"上一次调用距今是否已够", 那需要跨
    模块保存时间戳, 而各跑批件的执行顺序各不相同, 共享状态比统一无条件睡更容易
    出错。1.5 秒 × 17 个场景 = 25 秒, 相对实跑本身的分钟级耗时可忽略。

    Args:
        what: 场景标识, 只进日志便于排查"卡在哪一步"。
    """
    time.sleep(SCENARIO_GAP_SECONDS)  # 无条件睡: 共享时间戳比统一等待更容易漏间隔
    if what:  # 非交互 CI 里 stderr 是唯一能看见"这批在动"的出口
        print(f"[live] 间隔 {SCENARIO_GAP_SECONDS}s 已过: {what}", flush=True)


def read_only_retryable(error: str) -> bool:
    """该错误是否**允许**重试。

    判据是方法的幂等性, 不是错误码本身: GET 可重试 (同一次读), POST 不可
    (phase-1 提交会在服务端建会话, 重试即泄漏)。所以这里不按错误名白名单 ——
    那种写法在新增错误码时必然漏, 而漏一次就是一次孤儿会话。

    Args:
        error: 错误标识 (由调用方从异常或失败码里提取)。

    Returns:
        True 表示调用方可以对该错误重试。
    """
    return False  # 默认全不重试: 宁可让一次失败暴露, 也不替调用方造孤儿会话


class CountingSession:
    """给真会话套一层**只计数、不改写**的代理 (M7 请求计数的事实来源)。

    为什么需要: 回放时代计数由 ``SnapshotTransport.call_count`` 提供, 快照删除后
    这个字段随之消失, 而 M7 (确定性) 判据需要一个"这次查询真的发了几次请求"。
    客户端自身不计数 (生产代码不该为评测塞计数器), 所以在这里加代理。

    与被它替代的东西**性质不同**, 这点必须讲清: ``SnapshotTransport`` 是
    "用假回包终结真实请求", 本类是 "真实请求一个不少地放行, 顺便数一下"。
    后者不产生任何假数据, 所以它不违反"剔除离线内容" —— 删掉它会让 M7 失去判据,
    留着它才是有意的可观测性。

    刻意不继承 ``requests.Session``: 继承会让 isinstance 检查误以为它是真会话,
    而被测代码里有按会话类型分支的地方。用 ``__getattr__`` 透传其余成员。
    """

    def __init__(self, inner: Any | None = None) -> None:
        """包一层真会话 (不给就自建)。"""
        self._inner = inner if inner is not None else requests.Session()
        self.call_count = 0  # 计数从零起: M7 比的是"实测 vs 声明", 两者同源时差值恒 0
        self.calls: list[tuple[str, str]] = []  # (方法, URL) 留痕: 报告要能指出多发的是哪一次

    def __getattr__(self, name: str) -> Any:
        """其余成员一律透传给真会话 (headers / cookies / mount / close …)。"""
        return getattr(self._inner, name)  # 透传而非包装: 少一层就能少一处口径分叉

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        """所有 HTTP 调用的汇入点: 计数后原样放行。"""
        self.call_count += 1  # 先自增: 抛异常的请求也算发过, 否则"少发"会被算成自洽
        self.calls.append((str(method).upper(), str(url)))  # 只记不判
        return self._inner.request(method, url, **kwargs)  # 原样放行: 本类不改写任何回包

    def get(self, url: str, **kwargs: Any) -> Any:
        """GET 转发 (走 :meth:`request`, 保证计数只有一处实现)。"""
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        """POST 转发 (走 :meth:`request`)。**不重试** —— 见 :func:`read_only_retryable`。"""
        return self.request("POST", url, **kwargs)


# ── M7 诚实性: 声明侧的独立算法 ──────────────────────────────────────────
#
# BC-05 的根因: 编排层曾把 ``declared_http_requests`` 与 ``observed_http_requests``
# 都赋成 ``transport.call_count``。两个字段同源 ⇒ 相减恒 0 ⇒ M7 恒真, 丧失对
# 未声明隐藏请求的检验效力 —— 一条恒真的判据比没有判据更坏, 它让人以为验过了。
#
# 修法不是换一个同样同源的计数器, 而是让两侧**来自不同的观测面**:
#
# - ``observed`` = 计数器说的「一共发了几次」 (真会话/回放层的唯一出口);
# - ``declared`` = 按 BEST 两阶段契约把请求**轨迹**逐条分类后, 数出「有据可依」
#   的那几次 (见 :func:`accounted_calls`)。
#
# 于是 M7 真正在问的是: **有没有发过契约解释不了的请求**。若被测代码偷偷多打一次
# 探针 (或漏报成本), 它的轨迹里就有一条落进 ``unaccounted``, 差值非 0, M7 转红。

# BEST 两阶段协议的合法请求形态 (真源 src/protocol.py 的 build_query_form /
# submit_query / getcount / fetch_page 四步)。POST 命中 ``/{catalog}/q`` 表单提交,
# GET 命中 ``getcount`` 计数、``sqlid`` 续页取数、``page=`` 分页翻页。
_PHASE1_SUFFIX = "/q"


def _is_accounted(method: str, url: str) -> bool:
    """这一次请求能否被 BEST 两阶段契约解释。

    Args:
        method: HTTP 方法 (大写)。
        url: 完整 URL。

    Returns:
        True 表示契约里有这一步; False 表示「发过但契约里没有」—— 那就是隐藏请求。
    """
    if method == "POST":
        # phase-1 表单提交: 路径以 /q 结尾 (…/{catalog}/q)
        return url.split("?", 1)[0].rstrip("/").endswith(_PHASE1_SUFFIX)
    if method != "GET":
        return False  # 契约里没有第三种方法: PUT/DELETE 一律算隐藏请求
    path = url.split("?", 1)[0].lower()
    # 根路径探针 (…/data/best/ps1 之类, 无子路径) 是客户端探测查询端点时的正常一步
    if "getcount" in path or "sqlid" in path or "page=" in url.lower():
        return True
    return not path.rstrip("/").rsplit("/", 1)[-1]  # 末段为空 ⇒ 根路径探针


def accounted_calls(calls: list[tuple[str, str]]) -> tuple[int, list[str]]:
    """把请求轨迹分成「有据可依」与「契约解释不了」两堆 (M7 声明侧)。

    Args:
        calls: ``(方法, URL)`` 序列 —— :class:`CountingSession` 与
            :class:`~evals.groundtruth.transport.SnapshotTransport` 都有同名同形的
            ``calls`` 字段, 故回放层与实跑层共用这一个分类器。

    Returns:
        ``(有据可依的条数, 解释不了的调用列表)``。解释不了的那几条原样返回,
        报告能直接指出「多发的是哪一次」, 而不是只报一个差值。
    """
    unaccounted = [f"{m} {u}" for m, u in calls if not _is_accounted(m, u)]
    return len(calls) - len(unaccounted), unaccounted
