"""下载 hook 层单元测试: 分级策略 + ask 载荷。

守两类回归:
  * network 类 (连接失败/超时/429/5xx) 必须指数退避重试, 耗尽后才升级拦截;
  * severe 类 (校验失败/磁盘写失败/会话过期) 必须**立即**拦截, 且每次拦截都
    要带上 ask 载荷 (reason + evidence + >=2 条 options) — 调用方据此向用户
    ask, 严禁静默跳过。
"""
from __future__ import annotations

# 测试框架: raises 断言拦截异常形态, parametrize 同一断言覆盖多种 severe kind
import pytest

try:
    # 被测单元: severe 类别名常量 (hook 判据的权威键集) + 策略/拦截异常/注册表
    from src.download_hooks import (
        NETWORK_ERRORS,
        SEVERE_CHECKSUM,
        SEVERE_DISK,
        SEVERE_EMPTY_PRECISE,
        SEVERE_PAGINATION,
        SEVERE_PATH,
        SEVERE_PRECISE_TOO_LARGE,
        SEVERE_SESSION,
        DownloadHooks,
        HookBlockedError,
        HookPolicy,
    )
except Exception as _legacy_err:  # legacy-import-guard
    # 源码树结构调整导致旧导入路径失效时整模块跳过, 不让收集期直接报错
    import pytest as _pytest  # 别名导入: 顶部 import 若已失败, 这里重新绑定
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)  # 模块级 skip

# 第三方: requests 异常层级 — 网络类判定的被测替身必须是生产栈真实抛出的类型
# (P2-4 前按类名字符串匹配, 内置 ConnectionError 也会被偶然算中; 类引用判定后,
# 替身与生产代码必须用同一个 requests 异常类, 否则测的不是同一条路)
import requests


def _fast_policy() -> HookPolicy:
    """构造"零退避"策略: 重试次数固定, 退避基数压到毫秒级。

    这些用例断言的是重试**次数**与耗尽后的拦截语义, 不是退避时长; 用真实
    秒级退避只会让套件无故变慢。
    """
    return HookPolicy(max_retries=2, retry_base_sec=0.001)  # 退避压到毫秒: 只断言次数不计时长


class TestNetworkErrorClassification:
    """P2-4: 网络类判定按类引用 + isinstance, 不漏最常见的故障类。"""

    @pytest.mark.parametrize(
        "exc",
        [
            requests.exceptions.ConnectionError("refused"),
            requests.exceptions.ConnectTimeout("timed out"),   # ConnectionError+Timeout 子类
            requests.exceptions.Timeout("slow"),
            requests.exceptions.ReadTimeout("stalled"),
            requests.exceptions.ChunkedEncodingError("truncated"),
            requests.exceptions.SSLError("bad cert"),
            requests.exceptions.ProxyError("proxy down"),
            requests.exceptions.RetryError("urllib3 gave up"),
        ],
    )
    def test_common_network_failures_are_retryable(self, exc):
        """最常见的网络故障必须判 network (可重试)。

        守的不变量: 按类名字符串匹配 (``type(exc).__name__ in``) 时,
        ConnectTimeout (类名不在元组) / SSLError / ProxyError / RetryError
        全部漏判 — 最常见的故障反而不重试, 直接冒泡成任务失败。故必须走类
        引用判定。
        """
        assert DownloadHooks(policy=_fast_policy()).policy.is_network_error(exc)  # 类引用判定, 非类名匹配

    def test_non_network_errors_are_not_retryable(self):
        """非网络类不得判 network (编程错误/严重类走即拦即 ask 的另一条路)。"""
        policy = DownloadHooks(policy=_fast_policy()).policy  # 只取策略, 不建钩子
        assert not policy.is_network_error(ValueError("bad input"))  # 编程错误不该重试
        assert not policy.is_network_error(OSError("disk"))  # 磁盘错也不属网络类


class TestHookSevere:
    """severe 类: 立即拦截 + ask 载荷要素齐全 (不重试, 不静默)。"""

    def test_severe_immediate_interrupt_with_ask_payload(self):
        """checksum 不匹配必须立即抛 HookBlockedError, 且载荷四要素齐全。

        守的回归: 拦截不能只抛一个裸异常 — reason 与 evidence 必须拼进
        question (用户要看得见 expected/actual), options 至少 2 条, 否则
        CLI/agent 无法向用户 ask, 只能静默失败。
        """
        hooks = DownloadHooks(policy=_fast_policy())  # 毫秒退避, 免得套件无故变慢
        with pytest.raises(HookBlockedError) as ei:  # severe 立即拦, 不进重试循环
            hooks.severe(SEVERE_CHECKSUM, "sha256 不匹配",
                         {"expected": "aa", "actual": "bb"}, job_id="j1")  # 带 evidence
        payload = ei.value.interrupt.to_ask_payload()  # 转成调用方能直接 ask 的载荷
        assert payload["id"] == "hook_checksum_mismatch"  # 稳定 id 供前端分类
        assert "sha256 不匹配" in payload["question"]  # reason 进 question
        assert "expected=aa" in payload["question"]  # 证据入 question
        assert len(payload["options"]) >= 2  # 必须带建议方案

    @pytest.mark.parametrize("kind", [SEVERE_CHECKSUM, SEVERE_DISK,
                                      SEVERE_SESSION, SEVERE_PAGINATION,
                                      SEVERE_PATH, SEVERE_EMPTY_PRECISE,
                                      SEVERE_PRECISE_TOO_LARGE])
    def test_each_severe_kind_has_options(self, kind):
        """每个 severe 类别都必须有 >=2 条建议方案 (新增 kind 不许漏配)。

        守的不变量: 新增 severe kind 时忘记在 _OPTION_TEMPLATES 登记, 会让
        ask 载荷退化成空 options, 用户只看到"出错"没有任何可执行选择。
        阈值是 >=2 而不是 >=1: "至少 2 个建议方案"是
        ask 铁律 (download-playbook §5 / HookInterrupt docstring 同承诺),
        path_traversal 若只配 1 条即属文档与代码双漂移, 模板已补足。
        """
        hooks = DownloadHooks(policy=_fast_policy())  # 逐 kind 复用同一钩子
        with pytest.raises(HookBlockedError) as ei:  # 每个 severe kind 都要能抛
            hooks.severe(kind, "x", {}, job_id="j")  # 无 evidence 也要带足 options
        options = ei.value.interrupt.options  # 取建议方案列表
        assert len(options) >= 2, f"{kind} 必须带 >=2 条建议方案 (现 {len(options)})"  # 附上下文便于定位

    def test_observer_notified_on_interrupt(self):
        """拦截必须广播给观察者 (进度追踪器据此置 blocked)。

        守的不变量: 拦截必须广播观察者, 否则后台任务的状态永远停在 running —
        GUI 显示"还在跑", 实际早已被 hook 拦死。
        """
        hooks = DownloadHooks(policy=_fast_policy())  # 注册观察者再触发拦截
        seen = []  # 记录收到的 kind, 验证广播真的发生
        hooks.on_interrupt(lambda it: seen.append(it.kind))  # 进度追踪器就靠这个回调
        with pytest.raises(HookBlockedError):  # 拦截本身照抛
            hooks.severe(SEVERE_SESSION, "sqlid 失效", {}, job_id="j")  # 会话过期属 severe
        assert seen == [SEVERE_SESSION]  # 广播一次, 且带的是同一 kind

    def test_ask_disabled_raises_plain_runtime(self):
        """ask_on_severe=False 时降级为普通 RuntimeError (不得抛 HookBlockedError)。

        守的回归: 调用方显式关掉 ask 表示"我不做用户交互", 此时再抛
        HookBlockedError 会让它按 ask 流程去取一个空载荷; 消息必须含
        "blocked" 以便日志检索。
        """
        hooks = DownloadHooks(policy=HookPolicy(ask_on_severe=False))  # 显式关掉用户交互
        with pytest.raises(RuntimeError, match="blocked"):  # 降级成普通异常
            hooks.severe(SEVERE_CHECKSUM, "x", {})  # 载荷要素此时不必齐全


class TestHookNetwork:
    """network 类: 可重试状态码/异常走退避重试, 耗尽才拦截, 非网络异常穿透。"""

    def test_retry_then_exhaust_interrupts(self):
        """连接失败重试 1+max_retries 次后耗尽, 升级为 HookBlockedError。

        守的回归: 重试次数必须是"首次 + max_retries", 且 evidence.attempts
        记真实尝试数 — 用户 ask 时要看得见"已经试过 3 次", 否则无法判断
        该重试还是该放弃。
        """
        hooks = DownloadHooks(policy=_fast_policy())  # 毫秒退避, 断言的是次数
        calls = {"n": 0}  # 真实尝试次数计数器

        def flaky():
            """恒定失败体: 每次都抛 requests ConnectionError, 耗尽重试额度。

            守的回归: 只有"每次都失败"才能测出真实尝试次数 — 若替身中途成功,
            attempts 记的是 1, "首次 + max_retries"这条契约就根本没被走到。
            P2-4: 替身必须抛 requests 异常 (生产栈真实类型), 不再用内置
            ConnectionError — 类引用判定后两者是不同的类。
            """
            calls["n"] += 1  # 每次被调用就 +1
            raise requests.exceptions.ConnectionError("boom")  # 生产栈真实类型

        with pytest.raises(HookBlockedError) as ei:  # 耗尽后升级成拦截
            hooks.run_network(flaky, job_id="j2")  # 首次 + 2 次重试
        assert calls["n"] == 3  # 1 次首试 + max_retries(2) 次重试
        assert ei.value.interrupt.kind == "network_exhausted"  # 稳定的 kind 供前端分类
        assert ei.value.interrupt.evidence["attempts"] == 3  # 用户 ask 时要看得见试过几次

    def test_success_returns_value_without_retry(self):
        """成功路径零重试, 原样透出 fn() 的返回值 (不包装/不改写)。"""
        hooks = DownloadHooks(policy=_fast_policy())  # 成功路径不该触发任何拦截
        assert hooks.run_network(lambda: "ok", job_id="j") == "ok"  # 原样透出, 不包装不改写

    def test_rate_limit_status_retried(self):
        """HTTP 429 限流必须重试 (限流是礼貌问题, 不是失败)。

        side_effect 序列模拟协议阶段: 429 (限流, 退避后重试) -> 429 -> 200
        (限流窗口过去, 拿到结果)。守的不变量: 429 是礼貌问题不是失败, 当
        普通异常直接抛会让批量任务在高峰期必挂。
        """
        hooks = DownloadHooks(policy=_fast_policy())  # 毫秒退避
        seq = iter([429, 429, 200])  # 限流两次后放行
        calls = {"n": 0}  # 计数用于证明真的重试了

        def flaky_status():
            """按 429 -> 429 -> 200 序列回包: 限流必须被重试而不是被当成失败。

            守的回归: 限流是上游的礼貌请求, 不是错误; 若把 429 当普通异常抛出,
            批量任务在高峰时段必挂, 而用户看到的只是"连接失败"。
            """
            calls["n"] += 1  # 每次尝试 +1
            code = next(seq)  # 按脚本取下一个状态码

            class _R:  # 最小 status_code 载体
                """只带 status_code 的响应替身 (run_network 只需要这一个字段)。"""

                status_code = code  # 闭包捕获当次的状态码

            return _R()  # 交回响应, 由 run_network 判是否重试

        result = hooks.run_network(flaky_status, job_id="j")  # 第三次拿到 200
        assert result.status_code == 200  # 限流窗口过去后正常返回
        assert calls["n"] == 3  # 两次限流各重试一次, 共三次尝试

    def test_server_error_retried_then_interrupt(self):
        """持续 5xx: 重试耗尽后必须拦截, 不得无限重试也不得静默成功。

        side_effect 模拟协议阶段: 每次都返回 HTTP 500 (服务端错误区间) —
        瞬时故障要重试, 持久故障要在 max_retries 后收敛成一次 ask。
        """
        hooks = DownloadHooks(policy=_fast_policy())  # 毫秒退避, 免得套件变慢

        def always_500():
            """恒定 5xx 响应替身: 持久服务端错误要在重试耗尽后收敛成一次拦截。

            守的回归: 瞬时故障该重试, 持久故障不能无限重试也不能静默成功 —
            否则后台任务永远转圈, 用户既拿不到数据也看不到任何提示。
            """

            class _R:
                """只带 status_code 的响应替身 (run_network 只需要这一个字段)。"""

                status_code = 500  # 恒定服务端错误区间

            return _R()  # 每次都回 5xx

        with pytest.raises(HookBlockedError):  # 耗尽后必须拦, 不许无限重试
            hooks.run_network(always_500, job_id="j")  # 也绝不能静默成功

    def test_non_retryable_raises_immediately(self):
        """非网络异常 (编程错误/严重问题) 必须原样穿透, 不进退避循环。

        守的不变量: 把所有异常统一当网络类重试的话, 一个 ValueError 被重试
        3 次后包装成 network ask — 调用方拿到的是错的问题分类, 且白白多跑
        两次。ValueError 必须立即抛出, 由调用方按自身语义处理。
        """
        hooks = DownloadHooks(policy=_fast_policy())  # 毫秒退避即可, 本例不重试
        with pytest.raises(ValueError):  # 非网络异常直接穿透, 不重试
            hooks.run_network(lambda: (_ for _ in ()).throw(ValueError("bad")),
                              job_id="j")  # 一次性抛出的 lambda 替身
