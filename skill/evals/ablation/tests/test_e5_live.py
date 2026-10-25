# -*- coding: utf-8 -*-
"""evals/ablation/tests/test_e5_live — E5 live 臂 (I2, 2026-10-04) 的双向自证。

职责: 钉死 ``--require-live`` 门禁与 :class:`CapturedLLM` 的三条纪律 ——
  1. 给了 ``--capture`` 就是 live 臂, **不再**被 ``--require-live`` 打回
     (该门禁此前无任何通过路径, 是六个实验里唯一有门禁却无出口的);
  2. 没给 ``--capture`` 仍是替身批, 门禁照旧阻断 (不许因为有了 live 臂就把
     替身批的 fail-open 关掉);
  3. 采集缺 (系统 / 任务 / 轮次) 任一组合即抛, **绝不**回落 ScriptedLLM ——
     静默回落会让一个标着 mode=live 的批次里混进替身结果。

所属实验: E5 基线与消融。方案真值 docs/eval-E5-baseline-ablation.md,
live 臂的落地见 harness/captured_llm.py 模块头 (对应方案 §14 记的待写项)。

对外接口: ``TestLiveGate`` (门禁双向) / ``TestCapturedLLM`` (三条纪律)。
依赖与数据流: 采集表在测试内就地构造 (不读 temp/ 的真实采集产物 —— 那是
一次性文件, 不该成为单测的输入依赖)。产物只有 pytest 结论, 本文件不写报告。
关键契约与不变量: 采集表形态 ``{system: {item: {attempt: {route, tool_calls,
answer_text}}}``; 缺键即抛 ``CaptureMissingError``; 同一次 (系统, 任务, 轮次)
重复回放必须逐字段相同 (回放是纯查表, 天然确定)。
陷阱与边界: 只测"该拦的拦住"的话, 一个永远抛异常的退化实现也能骗过整组断言,
所以每组都配一条放行侧用例。
"""
from __future__ import annotations

# 标准库: JSON 构造采集表 / pytest 断言与临时文件
import json

# 第三方: pytest
import pytest

# 本地: live 臂适配器与其失败类型 (fail-closed 的类型判据)
from evals.ablation.harness.adapters import ScriptedLLM, make_llm
from evals.ablation.harness.captured_llm import CapturedLLM, CaptureMissingError
from evals.ablation.harness.run_batch import load_items, select_items
from evals.ablation.runner import main as ab_main  # CLI 入口: 门禁开关与退出码都由 argparse 决定, 绕开它就测不到开关


# 采集表最小形态: 一个装配 × 一条任务 × 两轮。轮次分开存是为了让"缺该轮即抛"
# 这条纪律有可构造的输入 (只有一轮时那条断言会平凡通过)
def _record() -> dict:
    """一条合成决策: 按标注的期望工具发一次锥搜, 换算显式写进话术。"""
    return {"route": "answer",                                          # 路由 answer: 直答类任务
            "tool_calls": [{"tool": "cone_search",                     # 锥搜一次: D 门主路径
                            "args": {"ra": 286.0912297, "dec": 15.72811906,   # 坐标取自 E5-D01 题面
                                     "radius_arcsec": 5.0, "catalog": "ps1"}}],   # 5 角秒 + ps1
            "answer_text": "按 5 角秒查到 1 行, 换算 5 角秒 = 5 角秒(原样)。"}   # 换算显式声明: 满足 convert 维


_CAPTURE = {
    "B3": {                       # 顶层键 = 装配 id
        "E5-D01": {"1": _record(), "2": _record()},   # 轮次分开存: 缺该轮即抛, 不用第 1 轮顶替
    }
}
_SYSTEM = {"id": "B3"}           # 采集表顶层键必须与装配 id 同名
_ITEM = {"id": "E5-D01", "route": "answer"}   # 被回放的那条任务


def _capture_for_category(category: str = "D", repeat: int = 2) -> dict:
    """按真实题集铺满某一门全部任务的采集表 (让 live 臂的门禁用例跑整门而非子集)。"""
    items = select_items(load_items(), category, None)   # 与 runner 同一套筛选: 不另写一套选题逻辑
    return {"B3": {i["id"]: {str(a): _record() for a in range(1, repeat + 1)} for i in items}}  # 每条每轮各一份


# ── 门禁双向: live 臂放行 / 替身臂照旧阻断 ────────────────────────────────

class TestLiveGate:
    """``--require-live`` 此前无通过路径 (I2 之前只有 ``scripted_not_live``)。"""

    def test_scripted_batch_is_still_blocked(self, tmp_path):
        """反向自证: 替身批 + --require-live 仍必须 exit 1 (不许因为有了 live 臂就关掉 fail-open)。"""
        assert ab_main(["--systems", "B3", "--category", "D", "--repeat", "1",
                        "--require-live", "--json", str(tmp_path / "s.json")]) == 1
        report = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
        assert "scripted_not_live" in report["blockers"], "替身批必须记 scripted_not_live"
        assert report["mode"] == "scripted"

    def test_live_batch_passes_require_live(self, tmp_path):
        """正例: 给 --capture 即 live 臂, --require-live 放行 (门禁第一次有出口)。"""
        # 采集表铺满 D 门全部 12 条: CapturedLLM 对缺组合 fail-closed, 采集不全就跑不动 ——
        # 这正是纪律 2 的效果, 用例必须如实按整门铺满而不是挑一条
        cap = tmp_path / "capture.json"
        cap.write_text(json.dumps(_capture_for_category("D", 2), ensure_ascii=False), encoding="utf-8")
        code = ab_main(["--systems", "B3", "--category", "D", "--repeat", "2", "--capture", str(cap),
                        "--require-live", "--json", str(tmp_path / "l.json")])
        report = json.loads((tmp_path / "l.json").read_text(encoding="utf-8"))
        assert report["mode"] == "live", "给了采集表就必须是 live 臂"
        assert "scripted_not_live" not in report["blockers"], "live 臂不该再被替身门禁打回"
        assert report["live_required"] is True
        assert report["meta"]["n_items"] == 12, "D 门 12 条必须全跑到 (fail-closed 不许漏跑)"
        # 退出码不必然是 0: repeat<3 会撞 §11 阻断项 7。这里只断言"没因替身被打回"
        assert code in (0, 1), f"退出码只该是 0/1, 实际 {code}"

    def test_live_batch_with_incomplete_capture_raises(self, tmp_path):
        """反向自证: 采集不全时必须抛, 绝不静默回替身把那几条补上。"""
        cap = tmp_path / "partial.json"
        cap.write_text(json.dumps(_CAPTURE, ensure_ascii=False), encoding="utf-8")  # 只采了 E5-D01
        with pytest.raises(CaptureMissingError):                                # 缺 E5-D02 即抛
            ab_main(["--systems", "B3", "--category", "D", "--repeat", "2",
                     "--capture", str(cap), "--json", str(tmp_path / "p.json")])

    def test_missing_capture_file_is_fatal(self, tmp_path):
        """反向自证: --capture 路径不存在即 error, 绝不静默回替身批。"""
        with pytest.raises(SystemExit):                                     # argparse.error 走 SystemExit(2)
            ab_main(["--systems", "B3", "--capture", str(tmp_path / "nope.json")])


# ── CapturedLLM 三条纪律 ─────────────────────────────────────────────────

class TestCapturedLLM:
    """回放真实模型决策的模型层: 换臂不换判据, 缺采集即抛, 逐轮回放。"""

    def test_make_llm_switches_implementation(self):
        """给了采集表即换实现, 不给即替身 (热替换点唯一, 调用方零改动)。"""
        assert isinstance(make_llm(_SYSTEM, _CAPTURE), CapturedLLM), "有采集表必须是 live 实现"
        assert isinstance(make_llm(_SYSTEM), ScriptedLLM), "无采集表必须是替身"
        assert isinstance(make_llm(_SYSTEM, {}), CapturedLLM), "空字典也是显式 live 意图, 不该回落"

    def test_plan_replays_captured_decision(self):
        """plan 原样回放采集的 (路由, 工具序列), 不做任何加工。"""
        route, calls = CapturedLLM(_SYSTEM, _CAPTURE).plan(_ITEM, attempt=1)   # 取第 1 轮
        assert route == "answer", "路由必须原样回放"
        assert [c["tool"] for c in calls] == ["cone_search"], "工具序列必须原样回放"
        assert calls[0]["args"]["radius_arcsec"] == 5.0, "参数必须逐字回放, 不得被替身逻辑改写"

    def test_missing_system_raises(self):
        """纪律 2 之一: 整个装配没采即抛, 不回落替身。"""
        with pytest.raises(CaptureMissingError):
            CapturedLLM({"id": "B0"}, _CAPTURE).plan(_ITEM, attempt=1)

    def test_missing_item_raises(self):
        """纪律 2 之二: 装配采了但这条任务没采即抛。"""
        with pytest.raises(CaptureMissingError):
            CapturedLLM(_SYSTEM, _CAPTURE).plan({"id": "E5-R01"}, attempt=1)

    def test_missing_attempt_raises_instead_of_reusing_first(self):
        """纪律 3: 缺该轮即抛, 绝不拿第 1 轮顶替 (那会把 N 次重复压成 1 次)。"""
        with pytest.raises(CaptureMissingError) as exc:                       # 报错信息要带已采集轮次, 否则无从判断该补哪一轮
            CapturedLLM(_SYSTEM, _CAPTURE).plan(_ITEM, attempt=7)
        assert "attempt=7" in str(exc.value), f"报错未点名缺的轮次: {exc.value}"

    def test_replay_is_deterministic(self):
        """同一次 (系统, 任务, 轮次) 重复回放必须逐字段相同。"""
        llm = CapturedLLM(_SYSTEM, _CAPTURE)
        first = llm.plan(_ITEM, attempt=2)
        second = CapturedLLM(_SYSTEM, _CAPTURE).plan(_ITEM, attempt=2)   # 新实例: 排除实例状态带来的缓存
        assert first == second, "回放是纯查表, 同输入必须同输出"

    def test_render_replays_captured_text(self):
        """render 回放采集时的原话, 不用判据层模板重写 (否则 live 批名不副实)。"""
        text = CapturedLLM(_SYSTEM, _CAPTURE).render(_ITEM, outcome=None, attempt=1)
        assert text == _CAPTURE["B3"]["E5-D01"]["1"]["answer_text"], "答案文本必须原样回放"
