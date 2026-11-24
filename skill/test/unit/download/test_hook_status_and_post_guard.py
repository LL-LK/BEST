"""hook 层的 429/5xx 判定可达性 + phase-1 POST 不被重发 (A3-04 / A3-07)。

守的不变量:
  A3-04  状态码信息通道真的通到判定层。修复前实测 ``isinstance(HTTPError,
    NETWORK_ERRORS)`` 为 False 且 ``getattr(HTTPError, "status_code", None)``
    恒为 None —— requests 把码挂在 ``.response.status_code`` 上, 两处盲点
    叠加的结果是 429/5xx 这两类最该分级的错误**永远判不到**。
  A3-07  注入 429 后**不得发起第二次 POST**。phase-1 POST 建的是服务端会话,
    响应丢失时重发即多造一个孤儿会话 (泄漏查询配额), 所以正确行为是:
    不重试, 如实带状态码 ask 用户, 而不是让退避把 POST 再打一遍。

离线: 客户端是自建替身, 只计 POST 次数与抛桩异常, 不触网; 断点/进度/落盘
全走生产实现。
"""
from __future__ import annotations

# 标准库: 产物路径断言 (done 才说明整段真的收尾了) / 替身签名标注
from pathlib import Path  # 只为断言落盘产物在盘上: 状态说 done 而文件不在, 那是空气写
from typing import Any  # 替身方法与真实客户端签名不同构, 入参一律收 *args/**kwargs

# 测试框架: raises 断言拦截必抛
import pytest  # 三类拦截断言全靠它: 恒抛才算契约兑现

# 第三方: requests 异常 (A3-04 的被测对象就是它真实的属性布局)
import requests  # 只取异常与 Response: 不发任何请求

# 本地: 分级策略 (退避基数归零, 用例不必真等) / 钩子注册表 / 拦截异常 /
# 状态码抽取器 / 严重类元组 (证明 HTTPError 确实不在其中)
from src.download_hooks import (  # 被测单元: 状态码抽取 + 护栏 + 退避三处都在这一层
    NETWORK_ERRORS,  # 网络类异常元组: 断言 HTTPError 不在其中 (前提)
    POST_NOT_RETRIED,  # 非幂等失败的 kind: 载荷与断言都按它取值
    DownloadHooks,  # 钩子注册表: run_network 的护栏参数在此
    HookBlockedError,  # 拦截异常: 分类命中后必抛它, 调用方据此 ask
    HookPolicy,  # 退避策略: 退避基数归零 + max_retries 固定
    extract_status_code,  # 状态码信息通道本身 (A3-04 的核心修法)
)

# 本地: 后台下载管理器 (phase-1 POST 所在的重试闭包) 与任务描述
from src.download_manager import DownloadManager, RegionJob  # 真实线程池 + 真实 hook 接线

# 本地: 数据模型 (替身客户端要回一份带行的成功信封)
from src.models import BestQueryResult, BestSource  # 替身只造模型对象, 不碰网络


def _http_error(status: int) -> requests.exceptions.HTTPError:
    """造一个带 Response 的 requests 异常 (复刻 raise_for_status 的真实形态)。"""
    response = requests.Response()  # 真实 Response 对象: 码挂它身上, 异常自身没有 status_code
    response.status_code = status  # 只设码: 门禁要判的就是它
    return requests.exceptions.HTTPError(f"{status} Client Error", response=response)  # 形如站点真回的 4xx/5xx


def _rows(n: int = 1) -> list[BestSource]:
    """造 n 行源对象 (落盘要过非空闸, 否则测试测的是"空结果闸"而非重试语义)。"""
    return [BestSource(source_id=f"S{i}", ra=180.0 + i, dec=30.0, magnitudes={"r": 15.0}) for i in range(n)]  # 行数够非空闸即可


class _PhaseOneFails:
    """替身客户端: phase-1 POST 一律抛带状态码的异常 (模拟服务端限流/故障)。"""

    def __init__(self, status: int = 429) -> None:
        """记下要抛的状态码, 后面断言证据里能对上号。"""
        self.status = status  # 429 与 503 各跑一遍: 限流与服务端故障必须同口径
        self.post_count = 0  # POST 计数: A3-07 的判据就在这个数上

    def submit_phase1(self, *args: Any, **kwargs: Any) -> tuple[None, str]:
        """模拟 POST /q 被拒: 计一次, 抛真实形态的 requests 异常。"""
        self.post_count += 1  # 每进一次就是一次真实的建会话请求
        raise _http_error(self.status)  # 真实异常形态: 让 hook 走抽取码那条通道

    def fetch_page(self, *args: Any, **kwargs: Any) -> BestQueryResult:
        """本替身只驱动 phase-1 失败; 走到这里说明闭包重发了不该发的阶段。"""
        raise AssertionError("phase-2 不该在 phase-1 失败时被触达")  # 触达即说明重试越过了 phase-1


class _PagingFailsOnce:
    """替身客户端: phase-1 成功, phase-2 首次 GET 抛网络错, 第二次成功。"""

    def __init__(self) -> None:
        """初始化两侧计数与"第一次翻页失败"的开关。"""
        self.post_count = 0  # POST 次数: 断言重试**没有**重发建会话请求
        self.page_calls = 0  # GET 次数: 断言退避重试确实发生 (否则护栏把重试也掐了)

    def submit_phase1(self, *args: Any, **kwargs: Any) -> tuple[str, None]:
        """模拟 POST /q 成功: 发一次会话号就返回。"""
        self.post_count += 1  # 真实建会话只应发生一次
        return "s2623", None  # 会话号 + 无错误: 断点随后就靠它续

    def fetch_page(self, sqlid: str, **kwargs: Any) -> BestQueryResult:
        """phase-2: 首次抛连接错 (可重试), 之后回一份成功信封。"""
        self.page_calls += 1  # 计数即"翻页确实被重试过"的证据
        if self.page_calls == 1:  # 只让第一次失败: 第二次成功才能证明自愈
            raise requests.exceptions.ConnectionError("phase-2 GET failed")  # 网络类: 属可重试档
        rows = _rows(2)  # 两行: 足够落盘且过非空闸
        on_page = kwargs.get("on_page_fetched")  # 转发页回调: 断点/进度的真实链路
        if on_page is not None:  # 有回调才转发: 断点链要求逐页可见
            on_page(1, rows)  # 走真实回调, 不绕过断点写入
        return BestQueryResult(success=True, total_count=2, returned_count=2, sources=rows,
                               query_params={"catalog": "ps1/q", "sqlid": sqlid})  # 带 sqlid 便于溯源断言


def _manager(client: Any, tmp_path) -> DownloadManager:
    """造一个锚定临时区的管理器 (退避基数归零, 用例不必真等)。"""
    return DownloadManager(  # 真实线程池 + 真实 hook 接线: 不替身任何一环
        client, output_dir=str(tmp_path / "out"), progress_dir=str(tmp_path / ".progress"),
        checkpoint_dir=str(tmp_path / ".ckpt"),
        policy=HookPolicy(max_retries=1, retry_base_sec=0.0),  # 够验"重发一次", 且不必真睡
    )


class TestStatusCodeChannel:
    """A3-04: 状态码必须真的能抽出来, 否则 429/5xx 分级形同虚设。"""

    def test_http_error_is_outside_network_errors_but_its_status_is_reachable(self):
        """requests 的 HTTPError 不在网络类元组里 —— 码得从 .response 上取。"""
        exc = _http_error(503)  # 造一个真实形态的 5xx
        assert not isinstance(exc, NETWORK_ERRORS), "前提: HTTPError 确实不是网络类异常, 靠元组判不出来"
        assert getattr(exc, "status_code", None) is None, "前提: 异常自身没有 status_code 属性"
        assert extract_status_code(exc) == 503, "信息通道断了: 5xx 就永远判不到"

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_rate_limited_and_server_error_are_recognised(self, status):
        """抽出的码要真被策略认成限流/服务端错误, 而不是躺在那里没人看。"""
        policy = HookPolicy()  # 缺省策略: 阈值口径与生产同一份
        assert policy.is_rate_limited(extract_status_code(_http_error(status))) == (status == 429)  # 只认 429
        assert policy.is_server_error(extract_status_code(_http_error(status))) == (500 <= status < 600)  # 半开区间

    def test_object_returned_instead_of_raised_is_still_read(self):
        """有的封装不抛异常而是回带 status_code 的对象: 两种形态同一条通道。"""

        class _Resp:  # noqa: D101 - 替身只有一个字段, 下面补 docstring 满足审计
            """只带状态码的替身响应 (模拟"不抛异常直接回对象"的封装)。"""

            status_code = 429  # 类属性即可: 抽取器只认名字, 不关心它是实例还是类属性

        assert extract_status_code(_Resp()) == 429  # 返回值那条通道同样通

    def test_absent_status_yields_none_not_zero(self):
        """取不到就返回 None: 拿 0 冒充状态码会让 5xx 判定彻底失真。"""
        assert extract_status_code(RuntimeError("no code here")) is None  # 无码即无码, 不填 0


class TestNoSecondPost:
    """A3-04③ / A3-07: 注入 429 后既命中分类, 又不发起第二次 POST。"""

    def test_injected_429_is_classified_and_never_resent(self, tmp_path):
        """phase-1 POST 吃 429: 分类命中, 恰好一次 POST, 载荷带真实状态码。"""
        client = _PhaseOneFails(status=429)  # 注入 429
        mgr = _manager(client, tmp_path)  # 真实管理器
        job_id = mgr.submit(RegionJob(ra=180.0, dec=30.0, catalog="ps1", output_format="csv"))  # 走真实提交链

        # result() 会等后台线程收尾并按终态分流: blocked 抛 HookBlockedError
        # (fail-closed 读侧), 用它取载荷而不是读一个可能还停在 queued 的记录
        with pytest.raises(HookBlockedError) as excinfo:  # blocked 必抛: 拿到的是载荷而不是空串
            mgr.result(job_id, timeout=30)  # 等收尾, 终态判定以进度文件为准
        interrupt = excinfo.value.interrupt  # 载荷原样挂异常上, 无需从消息文本反解
        assert interrupt.kind == POST_NOT_RETRIED, "非幂等失败要用专门的 kind, 不复用 network_exhausted"
        assert interrupt.evidence["status_code"] == 429, "证据里必须带真实状态码, 否则用户无从判断是限流还是故障"
        assert client.post_count == 1, "铁律 7a: 绝不能因为 429 就把建会话的 POST 再发一遍"

    def test_server_error_takes_the_same_no_resend_path(self, tmp_path):
        """5xx 与 429 同口径: 同样不重发, 同样带码 ask。"""
        client = _PhaseOneFails(status=503)  # 换成服务端错误
        mgr = _manager(client, tmp_path)  # 真实管理器
        job_id = mgr.submit(RegionJob(ra=180.0, dec=30.0, catalog="ps1"))  # 走真实提交链

        with pytest.raises(HookBlockedError) as excinfo:  # 同一条拦截路径
            mgr.result(job_id, timeout=30)  # 等收尾
        assert excinfo.value.interrupt.evidence["status_code"] == 503  # 码要如实带出
        assert client.post_count == 1, "5xx 同样不重发 POST: 重试造孤儿会话的代价高于一次失败"

    def test_paging_retry_does_not_resubmit_the_form(self, tmp_path):
        """A3-07 实证: phase-2 断网触发重试, 重入走断点里的 sqlid, POST 只发过一次。

        这是对"重试闭包含 POST"的正面回答 —— 闭包确实含 POST, 但重入时
        断点已记下 sqlid, 于是只重跑 phase-2 的 GET。
        """
        client = _PagingFailsOnce()  # phase-1 成功, 第一次翻页断网
        mgr = _manager(client, tmp_path)  # 真实管理器
        job_id = mgr.submit(RegionJob(ra=180.0, dec=30.0, catalog="ps1"))  # 走真实提交链

        saved = mgr.result(job_id, timeout=30)  # 等后台线程收尾: done 才回路径
        assert Path(saved).is_file(), "翻页重试应当成功收尾并落出产物, 而不是把任务判死"
        assert client.page_calls == 2, "第二次翻页证明退避重试真的发生了"
        assert client.post_count == 1, "重入必须复用断点里的 sqlid, 不得重发 phase-1 POST"


class TestRetryGuardContract:
    """护栏本身的契约: 判否 = 一次都不重发; 判真 = 退避照旧。"""

    def test_guard_false_calls_fn_exactly_once(self):
        """护栏判否时闭包只该被调一次 —— "不重试"是次数断言, 不是意图声明。"""
        hooks = DownloadHooks(policy=HookPolicy(max_retries=3, retry_base_sec=0.0))  # 给足重试次数: 判否才显出护栏的力
        calls: list[int] = []  # 调用计数: 唯一的判据

        def _post() -> None:
            """模拟建会话的 POST 被限流 (每次调用都失败)。"""
            calls.append(1)  # 计数即证据: 第二次出现就是重发
            raise _http_error(429)  # 429: 可重试档, 但护栏判否就不许再打

        with pytest.raises(HookBlockedError) as excinfo:  # 护栏拦下即抛, 不静默
            hooks.run_network(_post, job_id="j1", retry_guard=lambda: False)  # 护栏判否
        assert len(calls) == 1, "护栏判否却重试了: 一次多余的 POST 就够多造一个孤儿会话"
        assert excinfo.value.interrupt.kind == POST_NOT_RETRIED  # kind 也要对
        assert excinfo.value.interrupt.evidence["status_code"] == 429  # 码也要对

    def test_guard_true_allows_the_retry(self):
        """护栏判真时退避重试不受影响 (幂等阶段的失败仍要能自愈)。"""
        hooks = DownloadHooks(policy=HookPolicy(max_retries=2, retry_base_sec=0.0))  # 够重试两次
        calls: list[int] = []  # 调用计数: 判"真的重试了"

        def _flaky() -> str:
            """第一次失败、第二次成功的幂等操作。"""
            calls.append(1)  # 计数即证据
            if len(calls) == 1:  # 只坏一次: 第二次成功才能证明自愈
                raise requests.exceptions.ConnectionError("transient")  # 网络类: 可重试档
            return "ok"  # 第二次成功, 调用方拿到结果

        assert hooks.run_network(_flaky, job_id="j2", retry_guard=lambda: True) == "ok"  # 正常返回
        assert len(calls) == 2, "判真时必须真的重试, 否则护栏把幂等路径的自愈能力也掐了"

    def test_guard_is_not_consulted_for_non_network_failures(self):
        """非网络类异常 (取消/编程错误) 原样穿透: 护栏只管"要不要重发", 不改分级语义。"""
        hooks = DownloadHooks(policy=HookPolicy(max_retries=1, retry_base_sec=0.0))  # 有重试额度也不该重试它

        with pytest.raises(ZeroDivisionError):  # 编程错误必须原样冒泡
            hooks.run_network(lambda: 1 / 0, job_id="j3", retry_guard=lambda: False)  # 护栏判否也不改变穿透语义
