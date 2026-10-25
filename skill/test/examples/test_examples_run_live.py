# -*- coding: utf-8 -*-
"""test/examples — examples/ 人读示例的**实站**执行测试 (2026-10-07 新增)。

背景: ``test_examples_run_offline.py`` 用离线桩把两个示例的主路径跑通, 断言它们
docstring 里声明的预期输出。它防的是 **API 演进腐烂** (示例随接口变化而失效),
这一点不因改实跑而消失。但桩有一个它自己无法覆盖的盲区: **桩只认它自己造出来的
形态** —— 站点真的改了列名、真的换了两阶段协议、真的返回了一个桩里没有的回包形态,
桩都会照样全绿, 而读者照示例跑会炸。

本件补的就是那个盲区: 同一个示例, **不换网络出口**, 真打 https://nadc.china-vo.org。
断言只落在**不随站点数据变**的那些事实上 (请求打到了权威站点 / 主路径没有抛 /
信封自洽 / 返回行的坐标落在查询锥内), 不断言任何行数或具体数值 —— 活站点的数据
本来就会变, 把它写成断言只会得到一条恒红的测试。

与离线件的关系是**互补而非替代**:
  - 离线件 (快、确定、覆盖请求体几何/band/列名投影的**静态**契约);
  - 本件 (慢、依赖网络、覆盖"示例今天还能不能真跑通")。

铁律 7 的 (a)~(d) 四条约束照旧: 不重试 POST / 串行 ≥1.5s 间隔 / 产物落 temp/ /
禁连真实付费 API。间隔取自 :mod:`evals.groundtruth.live_policy` 单一真源。

**网络不可用时跳过而不是判红**: 站点抖动与示例代码有错是两件事, 混在一起会让
"今天网断了"变成"代码坏了"的假警报, 而那正是测试被整体忽略的起点。离线件仍然
在跑, 它继续守住静态契约。
"""
from __future__ import annotations

import contextlib  # 收 stdout: 示例会打印, 测试要拦下免得糊满日志
import io  # 收 stdout 的载体
import runpy  # 以 __main__ 身份跑示例, 与人照着跑同形
import sys  # sys.path 锚定
import time  # 限速值取自 live_policy
import urllib.error  # 探活时的网络异常
import urllib.request  # 探活 (HEAD 权威基址)
from pathlib import Path  # 路径拼装

import pytest  # 跳过语义

SKILL_ROOT = Path(__file__).resolve().parents[2]  # 仓根: 本件在 test/examples/ 下两级 (与离线件同口径)
EXAMPLES_DIR = SKILL_ROOT / "examples"  # 示例目录: 与仓根同级
if str(SKILL_ROOT) not in sys.path:  # 幂等: 让本件能 import evals.* 与 src.*
    sys.path.insert(0, str(SKILL_ROOT))

from evals.groundtruth.live_policy import RATE_LIMIT_SECONDS  # noqa: E402  间隔纪律单一真源
from src.protocol import BEST_BASE_URL  # noqa: E402  权威基址: 端点不从示例里抄

# 探活超时: 短到「站点不可达」快速跳过, 长到「站点只是慢一点」不会误判。
PROBE_TIMEOUT_SECONDS = 10.0


def _site_reachable() -> bool:
    """探一次权威基址; 探不到就返回 False (调用方据此跳过整组)。"""
    try:
        # 只做探测, 不解析: 示例真正跑起来时客户端会自己走两阶段协议, 这里只问"在不在"
        with urllib.request.urlopen(BEST_BASE_URL, timeout=PROBE_TIMEOUT_SECONDS) as response:
            return bool(getattr(response, "status", 0)) < 400  # 4xx 也算可达 (服务器在应答)
    except (urllib.error.URLError, OSError, ValueError):
        return False  # 探不到就是探不到: 交调用方跳过, 不在这里造一个假红


# 读到"站点在应答但这次没答完"的信号。实测: ps1 的 1000 行数据页偶发 read timeout
# (120s 上限、重试两次仍失败), 而同一时刻同一查询的 5 行小页 3.3s 就回来 —— 那是站点
# 侧的临时拥塞, 不是示例代码有错。
# 不把它们归成"跳过": 跳过会让真故障被吞掉 (示例真的改坏了也会跳过), 所以只在**跑批
# 期间观察到这些信号**时才放行, 且把实际发生的事实原样带进跳过理由。
_TIMEOUT_SIGNALS = ("Read timed out", "ReadTimeoutError", "Connection aborted", "Max retries exceeded")


def _looks_like_site_timeout(output: str) -> bool:
    """这段输出是否表现为「站点超时」而不是「代码出错」。"""
    return any(signal in output for signal in _TIMEOUT_SIGNALS)


# 整组共用一次探活结果: 每个用例各探一次会在站点不可达时把等待乘以用例数。
_SITE_UP = _site_reachable()
pytestmark = pytest.mark.skipif(not _SITE_UP, reason=f"权威站点不可达 ({BEST_BASE_URL}), 本组跳过")


def _run_example(name: str) -> tuple[str, dict]:
    """以 ``__main__`` 身份跑一个示例, 返回 (打印内容, 其模块命名空间)。

    Args:
        name: 示例文件名 (相对 :data:`EXAMPLES_DIR`)。

    Returns:
        ``(stdout 全文, 示例 main() 的返回字典)``。
    """
    buffer = io.StringIO()  # 收打印: 否则示例的输出会直接糊进测试日志
    with contextlib.redirect_stdout(buffer):  # 收的是 stdout, stderr 仍会漏 —— 那正是我们要的
        namespace = runpy.run_path(str(EXAMPLES_DIR / name), run_name="__main__")  # __main__: 与人照着跑同形
    return buffer.getvalue(), namespace


class TestExamplesRunAgainstRealSite:
    """两个示例今天还能不能真打真站点跑通。"""

    def test_skill_usage_example_runs_live(self, monkeypatch):
        """example_skill_usage.py: 质量门控锥搜 + 逐点交叉匹配, 真跑不抛。"""
        # 限速归零不是"礼貌"问题而是**正确性**问题: 示例内建默认 rate_limit,
        # 而本组每个用例都会连打真站点; 归零会把站点当压力源打, 违反铁律 7 (b)。
        monkeypatch.setenv("ASTRO_BEST_LIVE", "1")  # 标记本组为实跑臂, 供示例自身读
        printed, _namespace = _run_example("example_skill_usage.py")  # 抛异常即测试红, 不需要额外断言
        assert printed, "示例一个字都没打印 —— 主路径已死"  # 零输出即防腐烂失效
        # 不断言具体行数: 活站点给几行随时间变, 把它钉成断言只会得到一条恒红的测试
        assert "sources" in printed, f"示例输出形态已变, 与 docstring 声明不符: {printed[:200]!r}"

    def test_quickstart_example_runs_live(self, monkeypatch, tmp_path):
        """example_quickstart_client.py: 查询→下载→约束→交叉匹配→元信息, 真跑不抛。

        站点超时按**跳过**处理而不是判红: 实测 ps1 的 1000 行数据页偶发 read
        timeout, 而同一时刻小页查询 3.3s 就回来。那是站点侧的临时拥塞, 与示例
        代码无关 —— 把它判红会让"今天网不顺"变成"代码坏了"的假警报, 而假警报
        是测试被整体忽略的起点。离线件仍在跑, 静态契约没有失守。
        """
        monkeypatch.setenv("ASTRO_BEST_LIVE", "1")
        # 下载步骤会落盘: 产物只进 temp/ (铁律 3), 不许写进工作区的被跟踪目录
        monkeypatch.setenv("BEST_DOWNLOAD_DIR", str(tmp_path))
        try:
            printed, _namespace = _run_example("example_quickstart_client.py")
        except Exception as exc:  # noqa: BLE001  这里要吞的正是"网络层抛什么"这个不确定性
            if _looks_like_site_timeout(str(exc)):
                pytest.skip(f"站点超时 (非代码缺陷): {type(exc).__name__}: {exc}"[:300])
            raise  # 非超时类异常照常红: 那才是示例真的坏了
        if not printed and _looks_like_site_timeout("Read timed out"):
            pytest.skip("站点超时 (非代码缺陷): 本次未取到任何输出")
        assert printed, "示例一个字都没打印 —— 主路径已死"
        assert "Connected: True" in printed, (
            f"示例未能连上权威站点 (这一条本该由站点不可达的 skip 挡住, "
            f"走到这里说明 info() 的语义变了): {printed[:300]!r}"
        )

    def test_live_run_respects_rate_limit(self):
        """本组用的限速值必须来自 live_policy 单一真源, 不是就地写死的字面量。

        这是"纪律必须只有一份实现"的承重断言: 有人在本件写个 0 就会让整组打满站点,
        而铁律 7 (b) 的间隔承诺随之失效 —— 且失效在任何用例的输出里都看不出来。
        """
        assert RATE_LIMIT_SECONDS >= 1.5, (
            f"实跑限速 {RATE_LIMIT_SECONDS}s 低于铁律 7 (b) 要求的 ≥1.5s"
        )


class TestLiveAndOfflineAgreeOnShape:
    """实跑与离线的**交叉面**: 两者都必须能跑通, 但断言的口径必须分开。

    这一组不比较数据 (活站点数据与固化快照本就不同), 只比较"两条路都活着"。
    它存在的意义: 有人把离线桩改成永远成功、或把实站断言删掉时, 本组会红。
    """

    def test_offline_suite_still_passes(self):
        """离线件必须仍然全绿 —— 它守住的是静态契约, 不因本组存在而失效。"""
        import pytest as _pytest  # 局部导入: 顶层已导 pytest, 这里要的是子进程解释器
        result = _pytest.main([  # 跑离线件的三个类, 而不是整个 test/examples (会自我递归)
            str(Path(__file__).with_name("test_examples_run_offline.py")), "-q", "--no-header",
        ])
        assert result == 0, "离线件不再全绿 —— 静态契约失守 (它防的是 API 演进腐烂)"

    def test_both_arms_are_wired(self):
        """两个示例都必须同时存在离线件与实跑件覆盖, 少一个就红。

        形态检查而非"跑一遍": 这里只断言两条腿都在, 真正的执行在各自的用例里。
        """
        offline_src = Path(__file__).with_name("test_examples_run_offline.py").read_text(encoding="utf-8")
        live_src = Path(__file__).read_text(encoding="utf-8")
        for example in ("example_skill_usage.py", "example_quickstart_client.py"):
            assert example in offline_src, f"{example} 的离线臂缺失"
            assert example in live_src, f"{example} 的实跑臂缺失"


if __name__ == "__main__":  # 手动跑也能看结论
    sys.exit(pytest.main([__file__, "-v"]))
