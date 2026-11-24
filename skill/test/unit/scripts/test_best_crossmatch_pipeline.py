"""astro-best scripts.best_crossmatch_pipeline 共享 client 回归 (A1)。

钉住三件事: 三个公开入口缺省复用模块级惰性共享 client (与 best_cone_search
的 Q-18 修法同形态); 连续调用不重复构造 BestClient; 调用方显式注入的
client 原样生效。全部离线: BestClient/BestCrossMatch 在测试内被替身换掉,
不发任何网络请求。
"""
from __future__ import annotations

from typing import Any  # 标准库: 替身方法的参数与返回标注

import pytest  # 第三方: monkeypatch fixture 换模块级依赖, 用例后自动还原

from src.client import BestClient  # 本地: client 层类型, 惰性单例用例的 isinstance 判定
from src.scripts import best_crossmatch_pipeline as pipeline  # 本地: 被测模块, 三个公开交叉匹配入口


class _FakeSource:
    """匹配源替身: 只实现被入口消费的 to_dict。"""

    def to_dict(self) -> dict[str, Any]:
        """返回固定源 dict (FAKE 标记防真对象混入断言)。"""
        return {"source_id": "FAKE-1", "fake": True}  # fake 标记防真对象混进断言


class _FakeResult:
    """锥检索结果替身: 只带 success/sources 两个被入口读取的字段。"""

    def __init__(self) -> None:
        """构造"有 1 条匹配"的结果替身。"""
        self.success = True  # 入口只读这两个字段, 其余一律不带
        self.sources: list[_FakeSource] = [_FakeSource()]  # 固定 1 条, 够验字段消费即可


class _FakeClient:
    """BestClient 替身: cone_search 直接返回假结果 (零网络)。"""

    def cone_search(self, *args: Any, **kwargs: Any) -> _FakeResult:
        """锥检索替身: 不发 HTTP, 返回固定假结果。"""
        return _FakeResult()  # 零网络: 位置参数全吞, 不校验也不下发


class _FakeCrossMatch:
    """BestCrossMatch 替身: 记录收到的 client, 返回假结果 (零网络)。"""

    def __init__(self, client: Any) -> None:
        """持有 (记录) 构造时传入的 client 实例。"""
        self.client = client  # 记下收到的实例, 供断言"共享 client 确实传到了"

    def crossmatch_coords(
        self,
        ra_list: list[float],
        dec_list: list[float],
        catalog: str = "ps1",
        radius_arcsec: float = 3.0,
    ) -> _FakeResult:
        """批量交叉匹配替身: 不发 HTTP, 返回固定假结果。"""
        return _FakeResult()


@pytest.fixture
def offline_pipeline(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """把 pipeline 模块的 BestClient/BestCrossMatch 换成离线替身并记录构造。

    Returns:
        state dict: ``clients`` 记录每次 BestClient 构造出的实例,
        ``xms`` 记录每次 BestCrossMatch 构造时收到的 client。
    """
    state: dict[str, list[Any]] = {"clients": [], "xms": []}  # 两个计数器, 构造次数是本组断言主体

    class _CountingClient(_FakeClient):
        """计数的 BestClient 替身: 构造时把实例记进 state["clients"]。"""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            """构造计数 +1 (不建 requests.Session, 零网络零资源)。"""
            state["clients"].append(self)  # 构造计数 +1, 不建 requests.Session

    class _RecordingCrossMatch(_FakeCrossMatch):
        """记录的 BestCrossMatch 替身: 把自身记进 state["xms"]。"""

        def __init__(self, client: Any) -> None:
            """记录传入的 client, 供断言"共享实例确实传进了领域层"。"""
            super().__init__(client)  # 先让父类存下 client, 保持替身继承链完整
            state["xms"].append(self)  # 记下"领域层这次拿到了谁", 供同一性断言

    # monkeypatch: 换掉模块级依赖; 共享单例复位为 None, 构造计数从零算起
    # (raising=False: 单例属性被人删掉时用例以断言失败报"行为回归", 而不是
    #  在 fixture setup 阶段报 AttributeError — 失败信息要指向行为本身)
    monkeypatch.setattr(pipeline, "BestClient", _CountingClient)  # 换成计数替身, 免建真实会话
    monkeypatch.setattr(pipeline, "BestCrossMatch", _RecordingCrossMatch)  # 换成记录替身, 留 client 痕迹
    monkeypatch.setattr(pipeline, "_SHARED_CLIENT", None, raising=False)  # 惰性缓存必须从空开始算
    return state  # 把计数器 dict 交给用例断言


class TestSharedClientReuse:
    """A1 回归: 三个公开入口必须复用模块级共享 client, 不每次新建会话。"""

    def test_entries_reuse_one_shared_client(self, offline_pipeline):
        """三个入口各调一次, BestClient 只构造 1 次且传进领域层的就是它。

        验证的行为: crossmatch_coords/crossmatch_with_gaia/crossmatch_with_ps1
        连续调用, 构造计数 = 1, 模块级 _SHARED_CLIENT 即该实例, 且
        BestCrossMatch 收到的也是该实例。
        为什么重要: 每次新建 BestClient 都新开一个 requests.Session (连接池),
        公开入口被 agent 侧循环调用时会持续泄漏会话, 与 Q-18 "公开函数每次新建
        BestClient 会泄漏 session" 的结论直接矛盾。回归背景:
        docs/architecture/file-size-budget.md §6 A1。
        """
        pipeline.crossmatch_coords([180.0], [30.0])       # 入口 1: 批量坐标交叉匹配
        pipeline.crossmatch_with_gaia(180.0, 30.0)        # 入口 2: Gaia 交叉匹配
        pipeline.crossmatch_with_ps1(180.0, 30.0)         # 入口 3: PS1 交叉匹配
        assert len(offline_pipeline["clients"]) == 1      # 三个入口合起来只构造 1 次
        shared = offline_pipeline["clients"][0]           # 取那唯一实例作同一性基准
        assert pipeline._SHARED_CLIENT is shared          # 模块级单例就是它
        assert offline_pipeline["xms"][0].client is shared  # 且真传进了领域层, 不只缓存在模块里

    def test_repeated_calls_construct_client_once(self, offline_pipeline):
        """同一入口连续两次调用只构造 1 个 client (会话跨调用复用)。

        验证的行为: crossmatch_with_gaia 调两次, 构造计数仍为 1。
        为什么重要: 会话与限流时钟要跨调用保持, 循环调用时才既复用连接又
        不把 rate_limit 时钟重置 (每次新建等于把节流整个绕过)。
        """
        pipeline.crossmatch_with_gaia(10.0, 20.0)         # 第 1 次调用, 触发惰性构造
        pipeline.crossmatch_with_gaia(11.0, 21.0)         # 第 2 次位置不同, 但不该另建会话
        assert len(offline_pipeline["clients"]) == 1      # 计数仍为 1: 限流时钟也跨调用保持

    def test_explicit_client_injection_is_honoured(self, offline_pipeline):
        """显式注入 client 时原样使用: 不碰共享实例, 也不新构造。

        验证的行为: 带 client= 调用两个入口, 构造计数为 0, 返回值来自注入
        实例的 cone_search。为什么重要: 调用方需要自有会话 (认证态/限流/
        测试替身) 时必须能绕开共享单例, 否则共享实例会成为唯一入口。
        """
        mine = _FakeClient()                                      # 调用方自有会话的代表
        first = pipeline.crossmatch_with_gaia(10.0, 20.0, client=mine)  # 显式注入绕开单点入口
        second = pipeline.crossmatch_coords([180.0], [30.0], client=mine)  # 批量入口同样尊重注入
        assert offline_pipeline["clients"] == []      # 构造计数 0: 注入路径不许碰共享单例
        assert first == {"source_id": "FAKE-1", "fake": True}  # 返回值来自注入实例的 cone_search
        assert second.success is True                # 批量入口回结果对象, 不是裸 dict
        assert offline_pipeline["xms"][0].client is mine  # 领域层拿到的必须是注入的那个

    def test_shared_client_is_lazy_singleton(self, monkeypatch):
        """_shared_client 是惰性单例: 两次取用同一实例 (Q-18 形态守门)。

        与 test/unit/meta/test_phase4_wiring.py::test_public_cone_search_shares_client
        同形态; monkeypatch 把单例复位, 用例结束自动还原, 不向会话泄漏真实
        BestClient。
        """
        monkeypatch.setattr(pipeline, "_SHARED_CLIENT", None, raising=False)  # 本地复位, 不依赖 fixture
        first = pipeline._shared_client()   # 第一次取用触发惰性构造
        second = pipeline._shared_client()  # 第二次应命中缓存
        assert first is second  # 同一实例, 这就是惰性单例
        assert isinstance(first, BestClient)  # 且是真实 BestClient 类型, 替身没污染


class TestBatchCrossmatchChannels:
    """YZ-27: batch_crossmatch 的失败原因与查无此项必须分通道, 不能混成无类型 list[str]。"""

    def test_error_and_miss_are_separate_channels(self, offline_pipeline, monkeypatch):
        """一张表抛异常、另一张查无此项时, errors 只装异常, misses 只装星表名。"""
        class _FailingClient(_FakeClient):
            """按 catalog 分岔的替身: 一张表抛异常, 其余表正常命中。"""

            def __enter__(self) -> "_FailingClient":
                """进入上下文返回自身: 批级入口按上下文管理器建 client, 不接资源。"""
                return self

            def __exit__(self, *exc: Any) -> None:
                """退出不做清理: 替身没有资源可释放, 但 with 协议要求该方法存在。"""
                return

            def cone_search(self, *args: Any, **kwargs: Any) -> Any:
                """按 catalog 分岔: ``fail_cat`` 抛异常模拟网络故障, 其余表正常命中。

                分岔点是本用例的全部意义: 只有"一表抛异常 + 一表成功"同时出现,
                才能验出异常被分到 errors 而没混进 misses (只测一张坏表时,
                两种实现都能让 asserts 通过)。
                """
                cat = kwargs.get("catalog", "unknown")
                if cat == "fail_cat":
                    raise RuntimeError("simulated network fault")  # 模拟异常路径
                return _FakeResult()  # 其他表正常命中

        # batch_crossmatch 是批级入口, 内部自建 client —— 打模块级 BestClient
        monkeypatch.setattr(pipeline, "BestClient", lambda **kw: _FailingClient())  # 换批级 client 构造
        result = pipeline.batch_crossmatch(
            [(10.0, 20.0)],
            catalogs=("gaia_dr3", "fail_cat"),  # 先正常后异常
        )
        assert len(result) == 1
        record = result[0]
        assert record["errors"] == ["fail_cat: simulated network fault"]  # 异常进 errors
        assert record["misses"] == []  # 没有查无此项: 成功的那张表不miss
        assert "gaia_dr3" in record["matches"]  # 正常表命中

    def test_invalid_coord_appears_in_errors(self, offline_pipeline, monkeypatch):
        """坏坐标占位时, 异常与 misses 都空, 错误进 errors。"""
        class _CmClient(_FakeClient):
            """坏坐标场景的替身: 只补上下文管理器, 检索行为沿用基类。"""

            def __enter__(self) -> "_CmClient":
                """进入上下文返回自身: 与 :class:`_FailingClient` 同构, 只换名字不换行为。"""
                return self

            def __exit__(self, *exc: Any) -> None:
                """退出不做清理: 替身没有资源可释放, 但 with 协议要求该方法存在。"""
                return

        monkeypatch.setattr(pipeline, "BestClient", lambda **kw: _CmClient())  # 换批级 client 构造
        result = pipeline.batch_crossmatch(
            [("bad", None)],
            catalogs=("gaia_dr3",),
        )
        assert len(result) == 1
        assert result[0]["errors"] == ["invalid_coord"]
        assert result[0]["misses"] == []
        assert result[0]["matches"] == {}
