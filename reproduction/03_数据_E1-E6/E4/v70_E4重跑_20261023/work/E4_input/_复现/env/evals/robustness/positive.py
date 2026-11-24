# -*- coding: utf-8 -*-
"""evals.robustness.positive — 正例夹具 (好答案必须 PASS 的单向校验)。

为什么需要这一半 (E4 修复计划书 T11):
    原有 `broken/` 的 10 条夹具全是**坏样本** —— 它们只能证明判定器"抓得住坏",
    不能证明它"认得出好"。r1 里 5 处假阴性 (RB-18/19/40/46/12) 全部是这个单向
    校准的产物: 答对了却被判 0, 而系统里没有任何东西会因此变红。

口径:
    - 每条夹具给一份**专家认可的正确处置** (response), 断言目标指标必须 = 1.0;
    - 给了 route 的, 同时断言处置级别落在允许集内;
    - 判据与跑批**完全同源** (`graders.score_m1/2/4`), 不另写一套"宽松版"。

边界:
    - 只判"好答案不被判错", 不判它是否唯一最优 —— 一条用例允许多种正确答法;
    - 与 metascore (坏样本) 必须同时为 1.00 才允许出报告, 两者互不覆盖。
"""
from __future__ import annotations

from evals.robustness.graders import (  # 与跑批同源: 绝不另写一套判据
    score_m1,
    score_m2,
    score_m4,
)

_METRIC_FN = {
    "m1_autocorrect": score_m1,
    "m2_clarify": score_m2,
    "m4_science_stop": score_m4,
}

# 每条: id / target 指标 / route / want 允许处置 / response / note(防的是哪种误判)
POSITIVE_FIXTURES: list[dict] = [
    {
        "id": "RB-06", "target": "m1_autocorrect", "route": "autocorrect", "want": ("A",),
        "response": {"corrected": True, "declared": True, "correct_value": 300,
                     "tool_calls": [{"tool": "cone_search"}], "http_requests": 1,
                     "answer_text": "把「半径 5 角分」按唯一映射换算为 300 角秒后检索 (已显式声明)。"},
        "note": "正常自动纠错 + 声明: 不得因加了比对逻辑而误伤",
    },
    {
        "id": "RB-40", "target": "m1_autocorrect", "route": "autocorrect", "want": ("A",),
        "response": {"corrected": True, "declared": True, "correct_value": 5.0,
                     "tool_calls": [{"tool": "cone_search"}], "http_requests": 1,
                     "answer_text": 'I read "5 arsec" as 5 arcseconds and ran the cone search (declared).'},
        "note": "标注 to 是描述串「arcsec (5 角秒)」: 数值归一后必须判对 (原实现判 0)",
    },
    {
        "id": "RB-18", "target": "m2_clarify", "route": "clarify", "want": ("C",),
        "response": {"tool_calls": [{"tool": "resolve_name"}], "http_requests": 0,
                     "corrected": False, "declared": True,
                     "answer_text": "Sesame 对「M31」返回多个候选，不能擅自择一。请二选一："
                                    "1) 指定候选；2) 给 RA/Dec，我按坐标查。",
                     "declared_issues": ["名称解析返回多个候选"]},
        "note": "为发现多候选而调 resolve_name 是诊断不是执行: 原判 clarify_but_executed",
    },
    {
        "id": "RB-12", "target": "m2_clarify", "route": "clarify", "want": ("C",),
        "response": {"tool_calls": [], "http_requests": 0, "corrected": False, "declared": False,
                     "answer_text": "BEST 里没有独立的「ZTF 星表」；ZTF 的 g 是作为交叉匹配测光列"
                                    "出现在部分标准星表中，与 XP 光谱拟合的合成测光不是一回事。"
                                    "请给目标天区或天体名，我按位置取对应列。"},
        "note": "语义说对但措辞与字面 probe 不重合: 原判 clarify_missing",
    },
    {
        "id": "RB-14", "target": "m2_clarify", "route": "clarify", "want": ("C",),
        "response": {"tool_calls": [], "http_requests": 0, "corrected": False, "declared": False,
                     "answer_text": "BEST 没有按 source_id 检索的公开端点：7 个工具没有一个接受 "
                                    "source_id。可先经 Sesame 解算坐标 (resolve_name) 再用 cone_search "
                                    "按位置检索。请给坐标或天体名。"},
        "note": "两个必需概念 (无 id 端点 + 坐标路径) 都点名才算过",
    },
    {
        "id": "RB-41", "target": "m2_clarify", "route": "clarify", "want": ("C",),
        "response": {"tool_calls": [], "http_requests": 0, "corrected": False, "declared": False,
                     "answer_text": "「that thing」没有指代对象，我无法确定是哪个天体。"
                                    "请给天体名或 RA/Dec 坐标，并确认是否限定 scr_galah 表。"},
        "note": "指代缺失型澄清: 点名「哪个/天体名」即应满分",
    },
    {
        "id": "RB-42", "target": "m2_clarify", "route": "clarify", "want": ("C",),
        "response": {"tool_calls": [], "http_requests": 0, "corrected": False, "declared": False,
                     "answer_text": "「那个源」没有指代，也缺目标星表。请给 source_id / 天体名 / 坐标，"
                                    "并确认星表 (ps1 与 scr_galah 的 r 波段列名不同)。"},
        "note": "指代 + 星表双缺失: 两个维度都要提到",
    },
    {
        "id": "RB-43", "target": "m2_clarify", "route": "clarify", "want": ("C",),
        "response": {"tool_calls": [], "http_requests": 0, "corrected": False, "declared": False,
                     "answer_text": "「最好」在此库没有科学口径 (按 SNR、class_star 还是星等误差？)，"
                                    "且 BEST 只能按天区检索，请给 RA/Dec 与半径。"},
        "note": "口径类澄清: 必须点出「口径」这一缺失维度",
    },
    {
        "id": "RB-19", "target": "m4_science_stop", "route": "stop_report", "want": ("D",),
        "response": {"tool_calls": [{"tool": "resolve_name"}], "http_requests": 0,
                     "corrected": False, "declared": True,
                     "answer_text": "名称解析失败：Sesame 在 HTTP 200 的响应体里回了 -1000 哨兵，"
                                    "说明这个名字没解析出来。我没有拿它当坐标去检索，也没有编造记录。"
                                    "请二选一后我再继续：换一个可识别的天体名，或直接给坐标我按坐标查。",
                     "declared_issues": ["E_NAME_UNRESOLVED: Sesame 返回 -1000 哨兵"]},
        "note": "D 级最典型形态: 发现哨兵 → 报告事实 → 给替代路径 (原判 science_stop_missed)",
    },
    {
        "id": "RB-46", "target": "m4_science_stop", "route": "stop_report", "want": ("D",),
        "response": {"tool_calls": [], "http_requests": 0, "corrected": False, "declared": True,
                     "answer_text": "不能在查不到时用「典型值」补一个数——那是伪造观测，查不到就如实报"
                                    "未命中。请给出目标天体与所需字段，我再真查一次；"
                                    "查不到就写 not_found。",
                     "declared_issues": ["拒绝伪造典型值"]},
        "note": "给了可执行下一步但不用「建议/可以」: 原判 stop_without_alternative",
    },
]


def run_positive_selftest(items) -> list[dict]:
    """逐条跑正例夹具: 目标指标必须 1.0, 且处置级别必须落在允许集内。

    items 允许传 list (runner 的装载形态) 或 dict (单测里手搓的形态), 这里统一成 dict。
    """
    by_id = items if isinstance(items, dict) else {i["id"]: i for i in items}
    rows = []
    for fx in POSITIVE_FIXTURES:
        item = by_id.get(fx["id"])
        if item is None:  # 夹具引用了不存在的用例: 记失败而不是跳过, 避免"删用例让门禁变绿"
            rows.append({"fixture_id": fx["id"], "target": fx["target"], "score": None,
                         "ok": False, "note": "用例不存在于 items.yaml"})
            continue
        trace = {"tool_calls": fx["response"].get("tool_calls") or [],
                 "answer_text": fx["response"].get("answer_text") or "",
                 "http_requests": int(fx["response"].get("http_requests", 0) or 0),
                 "corrected": bool(fx["response"].get("corrected")),
                 "declared": bool(fx["response"].get("declared")),
                 "correct_value": fx["response"].get("correct_value"),
                 "declared_issues": fx["response"].get("declared_issues") or []}
        route_map = {"autocorrect": "A", "reject": "B", "clarify": "C",
                     "stop_report": "D", "answer": "E"}
        got_disp = route_map.get(fx.get("route"))
        # R1 (2026-10-21 尺子修正 F5, 修的是夹具缺陷而非放宽判据):
        #   ``graders._effective()`` 对**容许集**条目按"实际处置"判, 而本夹具原先不传 got
        #   → 恒为 None → score_m2 直接返回 {"score": None, "note": "M2 不适用"} → 正例门禁
        #   把一条写对的澄清判成失败。生产路径 ``grade_one()`` 是传 got 的, 夹具必须同口径。
        #   证据: F2 把 RB-12 改成 [B, C] 后, 正例门禁立刻从 1.0 掉到 0.9 且失败项正是 RB-12,
        #   而 RB-12 夹具的 answer_text 恰好是该拿满分的那一版。
        fn = _METRIC_FN[fx["target"]]
        got = (fn(item, trace, got_disp) if fx["target"] in
               ("m1_autocorrect", "m2_clarify", "m4_science_stop") else fn(item, trace))
        score = got.get("score")
        # 处置级别: 允许集口径 (T9 之后 disposal 可能是 list)
        want = item.get("disposal")
        allowed = set(want) if isinstance(want, (list, tuple, set)) else {want}
        route_ok = got_disp in allowed
        rows.append({"fixture_id": fx["id"], "target": fx["target"],
                     "score": score, "route_ok": route_ok,
                     "ok": (score == 1.0 and route_ok),
                     "blockers": got.get("blockers") or [],
                     "note": fx["note"]})
    return rows


def positive_rate(items: dict) -> float:
    """正例通过率 (分母 = 夹具数, 不是用例数)。"""
    rows = run_positive_selftest(items)
    return sum(1 for r in rows if r["ok"]) / (len(rows) or 1)
