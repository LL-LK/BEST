# -*- coding: utf-8 -*-
"""E4 放行判据的承重测试: ``pass`` 与 ``warn`` 必须真的被用到。

**为什么这两条此前是"活的却逃逸"的 (N5/N6, 2026-10-07)**:

- ``robustness/graders.py`` 的 ``PASS_SCORE`` 定义在模块级、消费点在
  :func:`grade_case` 的 ``pass`` 位。把它放宽到 0.10, **9 道 audit 0 道判红、
  pytest 零 newfail** —— 因为 ``test_e4.py`` 全篇只调了两次 ``grade_case``,
  断言的是 ``weighted``/``scored``, ``["pass"]`` **零命中**。一条阈值完全逃逸的
  判据, 与一条阈值写错了的判据, 在门禁上长得一模一样。
- ``WARN_SCORE`` 更彻底: 它**零消费者**。常量上方写着「落在两者之间只报接近失效」,
  而函数根本不产 ``warn`` 这张脸 —— 注释承诺的行为不存在。

下面三条把两处都钉上, 手法是**改阈值看结论是否跟着变**: 一条判据若对输入不敏感,
  改它不该有任何可观测后果; 后果变了才说明它真的在判。
"""
from __future__ import annotations

# 标准库: 上下文管理器 (临时改模块常量后无条件还原)
from contextlib import contextmanager

# 第三方: pytest
import pytest

# 本地: E4 判定器 (阈值常量与 grade_case 同模块, 故按属性打补丁)
from evals.robustness import graders
from evals.robustness.graders import grade_case

# 本地: E4 题集装载 (与 test_e4.py 同一份 SSOT, 不另建一份夹具)
from evals.robustness.tests.test_e4 import load_items


@contextmanager
def _threshold(name: str, value: float):
    """临时把 ``graders.<name>`` 改成 ``value``, 退出即还原 (N5/N6 的探针本体)。

    用上下文管理器而不是直接赋值: 判据级测试最怕的就是"改了没还原",
    那会让后面所有用例都在一个被污染的阈值下跑, 且症状飘到别处难以归因。
    """
    original = getattr(graders, name)  # 记下原值: 还原的依据
    setattr(graders, name, value)      # 打补丁: 与 grade_case 读的是同一个模块属性
    try:
        yield                          # 交还控制权给 with 块: 期间阈值是被改过的
    finally:
        setattr(graders, name, original)  # 无条件还原: 即使断言抛异常也不留下脏阈值


def _pass_score(value: float):
    """只动放行线 (N5 用)。"""
    return _threshold("PASS_SCORE", value)  # 转发: 两个探针同源, 还原逻辑只有一份


def _warn_score(value: float):
    """只动预警线 (N6 用) —— 两者必须能分开动, 否则测不出 warn 是否真的读它。"""
    return _threshold("WARN_SCORE", value)  # 转发: 与 _pass_score 同源, 只有键名不同


def _utterance_trace() -> dict:
    """只带话术的 trace (零工具调用/零请求) —— 本测试要的是"判据对阈值敏感"。"""
    return {"tool_calls": [], "http_requests": 0, "answer_text": "不支持。可以改用别的源。"}  # 零调用零请求: 让"有无取数尝试"这条判据可被单独拨


def _w_item_and_trace():
    """取一条**已判**的 Tier W 用例与一份能触发若干指标的轨迹。"""
    items = {str(i["id"]): i for i in load_items() if i.get("tier") == "W"}  # 只取 W: P 级是话术层, weighted 恒 None, 拨阈值拨不动它
    item = next(iter(items.values()))  # 任取一条: 本测试要的是"判据对阈值敏感", 不依赖具体题面
    return item, _utterance_trace()  # 题面与轨迹成对返回: 两组用例都要同一份输入


class TestPassScoreIsLoadBearing:
    """N5: 放行线必须真的参与判定。

    N5 的实测: 把 ``PASS_SCORE`` 放宽到 0.10, 9 道 audit 0 道判红、pytest 零 newfail ——
    因为 ``test_e4.py`` 全篇只调了两次 ``grade_case``, 断言的是 ``weighted``/``scored``,
    ``["pass"]`` 零命中。**阈值完全逃逸的判据与阈值写错的判据, 在门禁上长得一模一样**,
    所以必须有一组专门去拨它。
    """

    def test_pass_flips_when_threshold_moves(self):
        """把放行线抬到 1.0 以上 → 必然判红; 降到 0 → 必然判绿。

        两条断言合起来才是承重的: 只断"抬到 1.0 判红"的话, 一个恒假的 ``pass``
        也能过; 只断"降到 0 判绿"的话, 一个恒真的 ``pass`` 也能过。
        """
        item, trace = _w_item_and_trace()  # 同一份输入跑两次, 唯一变量是阈值

        with _pass_score(1.01):  # 严于任何真实加权分: 必红
            strict = grade_case(item, trace)  # 严阈值下的结论
        with _pass_score(0.0):   # 松于任何真实加权分: 必绿 (前提是这条真没阻断项)
            loose = grade_case(item, trace)  # 松阈值下的结论: 与上一行同输入

        assert strict["weighted"] is not None, "前置条件: 这条用例得是已判的 (weighted 非 None)"
        assert strict["pass"] is False, (
            f"放行线抬到 1.01 仍判过: pass 没看 PASS_SCORE (weighted={strict['weighted']})")
        assert not strict["blockers"], (
            f"前置条件不成立: 这条用例本来就带阻断项 {strict['blockers']}, "
            "那么宽松阈值下也该是红的, 测不出阈值的作用")
        assert loose["pass"] is True, (
            f"放行线降到 0.0 仍判红: pass 另有硬条件没被这道测试覆盖 (blockers={loose['blockers']})")

    def test_blockers_override_a_perfect_score(self):
        """零阻断是独立于分数的一道闸: 高均分救不回来。"""
        item, trace = _w_item_and_trace()  # 同上: 题面不挑具体的
        trace = dict(trace)  # 拷一份: 不改原轨迹, 免得影响同用例内的其它断言
        trace["tool_calls"] = list(trace.get("tool_calls") or [])  # 拷一层: 改的是副本
        trace["tool_calls"].append({"tool": "nonexistent_tool", "args": {}})  # 注入一个不该有的调用

        graded = grade_case(item, trace)  # 注入非法工具调用后的判定
        # 不预设 graded 的具体 blockers 内容 (取决于七指标哪条命中), 只断"有阻断 ⇒ 不过"
        if graded["blockers"]:
            assert graded["pass"] is False, "有阻断项却判过 = 阻断位没进放行判据"


class TestWarnScoreIsLive:
    """N6: ``WARN_SCORE`` 必须有消费者, 且**不参与**放行。"""

    def test_warn_is_reported_and_respects_threshold(self):
        """N6 承重断言: ``warn`` 这张脸存在, 且它读的是 ``WARN_SCORE``。"""
        item, trace = _w_item_and_trace()
        graded = grade_case(item, trace)  # 缺省阈值下的结论: 用来断 warn 键存在
        assert graded["weighted"] is not None
        assert "warn" in graded, "grade_case 必须给出 warn 这张脸, 否则 WARN_SCORE 仍是死常量"  # 键存在只是第一步
        # 只动 WARN_SCORE: 抬到 1.01 时必不为 warn, 降到 0.0 时必为 warn。
        # **必须单独动它** —— 若两边一起动, 就分不清 warn 读的是哪条线。
        with _warn_score(1.01):
            assert grade_case(item, trace)["warn"] is False  # 阈值严于任何真实加权分: 必不为 warn
        with _warn_score(0.0):
            assert grade_case(item, trace)["warn"] is True  # 阈值松于任何真实加权分: 必为 warn

    def test_warn_does_not_affect_pass(self):
        """warn 是观察线不是放行线: 两者必须解耦, 否则改预警线会改放行结果。"""
        item, trace = _w_item_and_trace()  # 两次只差 WARN_SCORE
        with _warn_score(1.01):          # 只动预警线: pass 的结果不该因此改变
            warn_off = grade_case(item, trace)  # 预警线抬到 1.01 的那一侧  # 预警线抬到 1.01: 必不为 warn
        with _warn_score(0.0):           # 同上, 换成松的一侧
            warn_on = grade_case(item, trace)  # 预警线降到 0.0 的那一侧  # 预警线降到 0.0: 必为 warn
        assert warn_off["warn"] != warn_on["warn"], "前置条件: 两个阈值下 warn 应当不同"  # 不成立则本用例无意义
        # 只动预警线时 pass 不得改变: pass 归 PASS_SCORE 独占
        assert warn_off["pass"] == warn_on["pass"], "改预警线改了放行结果 = 两条线没解耦"  # 只动 WARN_SCORE


class TestUngradedCaseStaysUngraded:
    """未判 ≠ 及格: 无适用指标时 pass/warn 都必须是 False 而不是 True。"""

    def test_none_weighted_never_passes(self):
        """B 级话术用例七指标全不适用 → weighted=None; pass/warn 都不得为真。

        这条是"空判定被读成满分"的防线: 若有人把 ``weighted is not None and ...``
        里的前半句删掉, None 会让比较短路成"通过"。
        """
        items = {str(i["id"]): i for i in load_items() if i.get("tier") == "P"}
        graded = grade_case(next(iter(items.values())), _utterance_trace())  # P 级话术用例: 七指标全不适用
        assert graded["weighted"] is None and graded["scored"] is False
        assert graded["pass"] is False, "未判的用例判过 = 空判定被当成好结果"
        assert graded["warn"] is False, "未判的用例报 warn 也不对: 它连分都没有"


class TestTierPNarrowApplicabilityIsDisclosed:
    """D6 四条 P0 的**实测结论**钉在这里 (2026-10-07 逐条核实, 不是照抄清单)。

    清单记的与实测的差了三处, 而且三处都是"比记的轻"。把结论写成断言而不是留在
    报告文字里, 是因为**结论本身也会过期**: 将来有人给 Tier P 接上协议层事实
    (让 M5/M7 变得可判), 下面第三条就该转红提醒更新口径, 而不是让 Tier P 悄悄
    从"两项判据"变成"七项判据"而没人发现 —— 那正是本条目最初记的那个坑。
    """

    def test_m7_is_na_not_a_fake_full_marks(self):
        """P0-B 实测不成立: M7 在话术轨迹上记 N/A, 不是 1.0。"""
        from evals.robustness import judge_tier_p  # NA 名单的单一真源
        from evals.robustness.graders import score_m7  # 待验的那条判据本身

        items = {str(i["id"]): i for i in load_items() if i.get("tier") == "P"}  # 只取 P 级
        result = score_m7(next(iter(items.values())), _utterance_trace())  # 空话术轨迹: 没有 schema 现场
        assert result["score"] is None, (
            f"M7 报成了 {result['score']}: 离线话术轨迹没有 schema 现场, "
            "报 1.0 就是把『没查』说成『查过且干净』")
        assert "m7_schema_guard" in judge_tier_p.NA_METRICS  # 且它在 NA 名单里, 不是漏配

    def test_m2_discriminates_rather_than_grading_its_own_annotation(self):
        """P0-C/P0-A 实测不成立: M2 随答案变 (复述要点满分 / 空话术零分)。"""
        from evals.robustness.graders import score_m2  # 待验: 它是否随答案变

        items = [i for i in load_items() if i.get("tier") == "P" and (i.get("clarify") or {}).get("probes")]
        assert items, "题集里应有带 probes 的 C 级用例, 否则本测试无对象"  # 前置条件: 空题集会让本用例空转
        item = items[0]
        echo = {**_utterance_trace(),
                "answer_text": " ".join(str(p) for p in item["clarify"]["probes"])}  # 完美复述标注要点
        assert score_m2(item, echo)["score"] == 1.0        # 说清了 → 满分
        assert score_m2(item, _utterance_trace())["score"] == 0.0  # 什么都没说 → 零分
        # 两者必须不同: 同分即"判据不随答案变", 也就是清单里说的那种恒定判定

    def test_summary_reports_which_metrics_actually_scored(self):
        """P0-D 的后果是真的, 所以必须**可见**: weighted 是几项的均值要印出来。"""
        from evals.robustness import judge_tier_p  # 汇总口径在这里

        summary = judge_tier_p.summarize([], {})
        applicable = summary["applicable_metrics"]
        assert applicable, "Tier P 至少要有一项可判判据"  # 全 N/A 等于没判
        assert summary["n_applicable_metrics"] == len(applicable)  # 两份数要自洽
        # 全集减去 NA 名单 = 实际参与者; 两者口径必须对得上, 否则这份披露本身不可信
        assert set(summary["applicable_metrics"]) | set(summary["na_metrics"]) == set(judge_tier_p.M_WEIGHTS)
        assert not (set(applicable) & set(summary["na_metrics"])), "同一项不能既可判又 N/A"


if __name__ == "__main__":  # pragma: no cover - 直跑自检入口
    raise SystemExit(pytest.main([__file__, "-q"]))
