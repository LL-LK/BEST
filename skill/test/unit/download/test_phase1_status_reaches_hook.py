"""阶段 1 的真实状态码必须到达钩子分类层 (H6-01 / A3-04 跨文件残留)。

守的不变量: ``BestClient._submit_query_for_sqlid`` 在 POST 失败时**原异常上抛**,
不把它压成裸字符串。requests 把状态码挂在 ``exc.response.status_code`` 上, 一旦
压成 ``f"POST form to {path} failed: {e}"``, 信息通道即断 ——
``extract_status_code`` 恒得 ``None``, 429/5xx 永远判不到, 钩子只能走
``failed`` 分支: 有如实报错, **没有 ask 载荷** (用户无从得知"服务端限流")。

与 ``test_hook_status_and_post_guard.py`` 的分工: 那份用**替身客户端**证明钩子
侧就绪 (A3-04); 本份用**真实 BestClient** 钉住客户端侧不再压平 —— 两段合起来
才是端到端真通。两份都过而链路仍断, 正是"各自都绿"的典型盲区。

铁律 7a 一并守住: phase-1 POST 是非幂等建会话请求, 失败后**绝不重发**
(重发即在服务端多造一个孤儿会话并泄漏查询配额)。判据是次数断言, 不是意图声明。

离线: 桩只落在 ``session.post`` 上, 真实客户端 + 真实钩子 + 真实线程池 +
真实断点/进度/落盘链全在被测链内, 全程零真实网络请求。
"""
from __future__ import annotations

# 标准库: 路径断言 (done 才说明整段真的收尾了) / 替身签名标注
from typing import Any  # 替身方法与真实客户端签名不同构, 入参一律收 *args/**kwargs

# 测试框架: raises 断言拦截必抛
import pytest  # 拦截断言全靠它: 恒抛才算契约兑现

# 第三方: requests 异常 (被测链路的失败形态就是它真实的属性布局)
import requests  # 只取异常与 Response: 不发任何请求

# 本地: 生产客户端 (本文件的核心被测对象 — 它的失败传递方式就是要守的东西)
from src.client import BestClient

# 本地: 钩子注册表 / 拦截异常 / 非幂等失败 kind / 分级策略 / 状态码抽取器
from src.download_hooks import (  # 被测单元: 状态码通道 + 护栏的接线都在这一层
    POST_NOT_RETRIED,  # 非幂等失败的 kind: 载荷与断言都按它取值
    DownloadHooks,  # 钩子注册表: run_network 在此
    HookBlockedError,  # 拦截异常: 分类命中后必抛它, 调用方据此 ask
    HookPolicy,  # 退避策略: 基数归零, 用例不必真等
    extract_status_code,  # 状态码信息通道本身
)

# 本地: 后台下载管理器 (phase-1 POST 所在的重试闭包) 与任务描述
from src.download_manager import DownloadManager, RegionJob  # 真实线程池 + 真实 hook 接线


def _http_error(status: int) -> requests.exceptions.HTTPError:
    """造一个带 Response 的 requests 异常 (复刻 ``raise_for_status`` 的真实形态)。"""
    response = requests.Response()  # 真实 Response 对象: 码挂它身上, 异常自身没有 status_code
    response.status_code = status  # 只设码: 门禁要判的就是它
    return requests.exceptions.HTTPError(f"{status} Client Error", response=response)  # 形如站点真回的 4xx/5xx


class _CountingPost:
    """把 ``session.post`` 换成"计次 + 按注入状态码失败"的桩。

    刻意桩在 **session 层**而不是客户端层: 客户端的表单构造、节流、
    ``raise_for_status`` 调用与异常传递全部照真实代码跑 —— 被验的正是
    "客户端拿到异常之后怎么处理", 桩在客户端边界上就等于把被验对象替掉了。
    """

    def __init__(self, status: int) -> None:
        """记下要抛的状态码, 后面断言证据里能对上号。"""
        self.status = status  # 429 与 503 各跑一遍: 限流与服务端故障必须同口径
        self.post_count = 0  # POST 计数: 铁律 7a 的判据就在这个数上

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """计一次 POST 并抛出真实形态的 requests 异常。"""
        self.post_count += 1  # 每进一次就是一次真实的建会话请求
        raise _http_error(self.status)  # 真实异常形态: 让状态码抽取走 .response 那条通道


def _manager(client: Any, tmp_path: Any) -> DownloadManager:
    """造一个锚定临时区的管理器 (退避基数归零, 用例不必真等)。"""
    return DownloadManager(  # 真实线程池 + 真实 hook 接线: 不替身任何一环
        client, output_dir=str(tmp_path / "out"), progress_dir=str(tmp_path / ".progress"),
        checkpoint_dir=str(tmp_path / ".ckpt"),
        # 给足重试次数: "没重发"才显出是护栏的力, 而不是压根没给重试机会
        policy=HookPolicy(max_retries=3, retry_base_sec=0.0),
    )


class TestPhase1StatusReachesHook:
    """真实客户端的 phase-1 失败必须让钩子拿到真状态码, 且只发一次 POST。"""

    def test_real_client_no_longer_flattens_the_exception(self):
        """客户端层: 传输失败原异常上抛, 状态码留在异常对象上没被压平。"""
        client = BestClient(rate_limit=0)  # 关礼貌限流: 桩在 session 层, 不该真等
        client.session.post = _CountingPost(429)  # 注入 429

        with pytest.raises(requests.exceptions.HTTPError) as excinfo:  # 原异常上抛, 不再是字符串信封
            client.submit_phase1("ps1", constraints=[])  # 走公开缝: 私有方法改了签名会被这里抓到

        # 状态码可从异常上取到 = 信息通道没断。这是"压成字符串"修掉前的红点:
        # 修复前这里拿到的是 (None, "POST form to ps1/q failed: 429 ..."), 不是异常。
        assert extract_status_code(excinfo.value) == 429, "状态码必须仍能从异常上取到, 否则分类层永远判不到"

    def test_query_layer_envelope_contract_is_preserved(self):
        """查询层契约不变: ``submit_query`` 仍回失败信封, 不把异常抛给调用方。"""
        client = BestClient(rate_limit=0)  # 关礼貌限流
        client.session.post = _CountingPost(503)  # 注入 5xx

        result = client.submit_query("ps1", constraints=[])  # 公开查询缝: 调用方按 success 分支即可

        assert result.success is False, "查询层仍须回失败信封: 抛异常会打断 ai_tools/crossmatch 的信封分流"
        assert result.error_code == "E_BACKEND", "传输故障应归后端不可达, 调用方按码分支而非匹配文案"

    @pytest.mark.parametrize("status", [429, 503])
    def test_injected_status_is_classified_and_post_sent_once(self, tmp_path, status):
        """端到端: 真实客户端 + 真实钩子, 分类命中且 POST 恰好发过一次。"""
        client = BestClient(rate_limit=0)  # 关礼貌限流
        poster = _CountingPost(status)  # 注入状态码并计 POST 次数
        client.session.post = poster  # 桩在 session 层: 客户端真实逻辑全跑
        mgr = _manager(client, tmp_path)  # 真实管理器
        job_id = mgr.submit(RegionJob(ra=180.0, dec=30.0, catalog="ps1", output_format="csv"))  # 真实提交链

        # result() 会等后台线程收尾并按终态分流: blocked 抛 HookBlockedError
        # (fail-closed 读侧), 用它取载荷而不是读一个可能还停在 queued 的记录
        with pytest.raises(HookBlockedError) as excinfo:  # blocked 必抛: 拿到的是载荷而不是空串
            mgr.result(job_id, timeout=30)  # 等收尾, 终态判定以进度文件为准

        interrupt = excinfo.value.interrupt  # 载荷原样挂异常上, 无需从消息文本反解
        assert interrupt.kind == POST_NOT_RETRIED, "非幂等失败要用专门的 kind, 不复用 network_exhausted"
        # 修复前这里是 None: 客户端把异常压成字符串, 钩子抽不到码, 只能报一句
        # "非幂等请求失败" 而用户不知道服务端到底回了什么。
        assert interrupt.evidence["status_code"] == status, "ask 载荷必须带真实状态码, 否则用户无从判断是限流还是故障"
        assert poster.post_count == 1, "铁律 7a: 绝不能因为限流/故障就把建会话的 POST 再发一遍"

    def test_reverted_client_would_fail_this_whole_file(self):
        """回归实证的锚: 若客户端改回压平成字符串, 上面三条会同时转红。

        这里断言的是**被验前提**而非被验行为: 客户端返回的必须是二元组
        ``(sqlid, error)``, 而不是异常对象。任何人把 ``raise`` 改回
        ``return None, f"...{e}"``, 下一行立刻红 —— 而不必等上面三条用例
        跑完整条下载链才发现。
        """
        client = BestClient(rate_limit=0)  # 关礼貌限流
        client.session.post = _CountingPost(429)  # 注入 429

        outcome: Any = None
        try:
            outcome = client.submit_phase1("ps1", constraints=[])  # 修复后: 这里抛异常
        except requests.exceptions.HTTPError as exc:  # 预期路径: 原异常上抛
            assert extract_status_code(exc) == 429  # 码仍在异常上
            return  # 前提成立: 客户端没有压平

        # 走到这里说明客户端返回了信封而不是抛异常 —— 即缺陷回归
        assert outcome is None or isinstance(outcome, tuple), (
            f"前提被破坏: submit_phase1 返回了 {type(outcome).__name__} 而非上抛异常, "
            "说明异常又被压平成了信封, 状态码通道已断"
        )
        pytest.fail("客户端未上抛异常: phase-1 失败又被压成字符串, 状态码到不了钩子分类层")


class TestHookStillSeesStatusFromRawException:
    """反向对照: 钩子侧的通道本身是通的 (证明红因在客户端而非钩子)。"""

    def test_hook_classifies_a_raw_status_bearing_exception(self):
        """裸异常进 ``run_network``: 护栏判否 → 带真码的 ``post_not_retried``。"""
        hooks = DownloadHooks(policy=HookPolicy(max_retries=3, retry_base_sec=0.0))  # 退避基数归零

        def _post() -> None:
            """模拟建会话的 POST 被限流 (每次调用都失败)。"""
            raise _http_error(429)  # 429: 可重试档, 但护栏判否就不许再打

        with pytest.raises(HookBlockedError) as excinfo:  # 护栏拦下即抛, 不静默
            hooks.run_network(_post, job_id="j-raw", retry_guard=lambda: False)  # 护栏判否
        assert excinfo.value.interrupt.evidence["status_code"] == 429  # 钩子侧通道本来就通
