# -*- coding: utf-8 -*-
"""tests/test_fix_2026_10_21 — 修复项的回归锁 (每处修复至少一条会红的断言)。

对应《E4 修复计划书》T1–T13。这些测试的用途不是"证明现在是对的",
而是**把每种误判钉住**: 任何一次回退都会在此变红。
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest
import yaml

from evals.robustness import graders
from evals.robustness.judge_tier_p import grade_one
from evals.robustness.positive import run_positive_selftest

ROOT = pathlib.Path(__file__).resolve().parents[3]
ITEMS = {i["id"]: i for i in
         yaml.safe_load((ROOT / "evals" / "robustness" / "items.yaml").read_text(encoding="utf-8"))["items"]}


def resp(**kw) -> dict:
    base = {"tool_calls": [], "http_requests": 0, "corrected": False,
            "declared": False, "correct_value": None, "answer_text": "", "route": ""}
    base.update(kw)
    return base


# ── T1: A 级纠正值不再逐字比串 ──────────────────────────────────────────

def test_t1_numeric_compare_hits_descriptive_annotation():
    """RB-40 的标注 to 是描述串「arcsec (5 角秒)」, 采集值 5.0 必须判对。"""
    trace = {"tool_calls": [{"tool": "cone_search"}], "answer_text": "5 arcsec",
             "http_requests": 1, "corrected": True, "declared": True, "correct_value": 5.0}
    got = graders.score_m1(ITEMS["RB-40"], trace)
    assert got["score"] == 1.0 and got["correct"] is True
    assert got["compare_mode"] == "numeric"


def test_t1_silent_correction_still_red():
    """改对但不声明仍是 S1 红线 —— 放宽比对不得把静默纠正也放过。"""
    trace = {"tool_calls": [], "answer_text": "", "http_requests": 0,
             "corrected": True, "declared": False, "correct_value": 5.0}
    got = graders.score_m1(ITEMS["RB-40"], trace)
    assert got["score"] == 0.0 and "silent_correction" in got["blockers"]


# ── T2: 诊断性只读调用不算"执行" ────────────────────────────────────────

def test_t2_resolve_name_is_diagnostic_not_execution():
    """RB-18 为发现多候选必须调 resolve_name —— 不得判 clarify_but_executed。"""
    r = resp(route="clarify", tool_calls=[{"tool": "resolve_name"}],
             answer_text="Sesame 返回多个候选，请二选一：1) 指定候选 2) 给坐标我按坐标查。")
    row, _ = grade_one(ITEMS["RB-18"], r)
    assert row["dims"]["m2_clarify"] == 1.0, row["blockers"]


def test_t2_real_fetch_still_counts_as_execution():
    """真正取数的调用仍必须判 clarify_but_executed —— 白名单不能扩到 fetch_page。"""
    r = resp(route="clarify", tool_calls=[{"tool": "fetch_page"}],
             answer_text="Sesame 返回多个候选，请二选一：1) 指定候选 2) 给坐标我按坐标查。")
    row, _ = grade_one(ITEMS["RB-18"], r)
    assert "m2_clarify:clarify_but_executed" in row["blockers"]


def test_t2_m4_diagnostic_tool():
    """RB-19 的 D 级行为完整, 只因调了 resolve_name 就被判 0 —— 修复后必须 1.0。"""
    r = resp(route="stop_report", tool_calls=[{"tool": "resolve_name"}],
             answer_text="名称解析失败：Sesame 回 -1000 哨兵，我没有拿它去检索，也没有编造记录。"
                         "请二选一后我再继续：换一个可识别的名字，或给坐标我按坐标查。",
             declared_issues=["E_NAME_UNRESOLVED"])
    row, _ = grade_one(ITEMS["RB-19"], r)
    assert row["dims"]["m4_science_stop"] == 1.0, row["blockers"]


def test_t2_m4_execution_still_red():
    """真的边停边查仍必须判 science_stop_missed。"""
    r = resp(route="stop_report", tool_calls=[{"tool": "cone_search"}],
             answer_text="名称解析失败，请二选一后我再继续。")
    row, _ = grade_one(ITEMS["RB-19"], r)
    assert "m4_science_stop:science_stop_missed" in row["blockers"]


# ── T3: 澄清点名改概念组 ────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "BEST 里没有独立的「ZTF 星表」；ZTF 的 g 是作为交叉匹配测光列出现的。",
    "ZTF 不是一张表，g 来自交叉匹配列。",
    "BEST 无 ZTF 表；g 是实测交叉列。",
])
def test_t3_concept_probe_accepts_paraphrase(text):
    r = resp(route="clarify", answer_text=text)
    row, _ = grade_one(ITEMS["RB-12"], r)
    assert row["dims"]["m2_clarify"] == 1.0, row["blockers"]


def test_t3_vague_clarify_still_half_score():
    """只问"请补充"仍记 0.5 —— 概念组不得把含糊澄清抬成满分。"""
    r = resp(route="clarify", answer_text="请补充更多信息。")
    row, _ = grade_one(ITEMS["RB-12"], r)
    assert row["dims"]["m2_clarify"] == 0.5


# ── T4: 替代路径认"可执行下一步" ────────────────────────────────────────

def test_t4_alt_offered_by_action_sentence():
    r = resp(route="stop_report",
             answer_text="不能在查不到时用典型值补数。请给出目标天体与字段，我再真查一次。")
    row, _ = grade_one(ITEMS["RB-46"], r)
    assert row["dims"]["m4_science_stop"] == 1.0, row["blockers"]


def test_t4_bare_refusal_still_half():
    r = resp(route="stop_report", answer_text="这个我不知道，查不了。")
    row, _ = grade_one(ITEMS["RB-46"], r)
    assert row["dims"]["m4_science_stop"] == 0.5


# ── T5: pass 三值 ───────────────────────────────────────────────────────

def test_t5_na_is_not_fail():
    """E 级/无适用判据的用例处置判对、零阻断 → status 必须是 na, 不是 fail。"""
    r = resp(route="answer", answer_text="查完是 0 行：success=true, total=0。")
    row, _ = grade_one(ITEMS["RB-17"], r)
    assert row["status"] == "na" and row["blockers"] == []


# ── T6: 禁调区分"声明"与"真发请求" ─────────────────────────────────────

def test_t6_declared_but_blocked_is_warning():
    """RB-01 正文声明零请求 → 记 declared_blocked_call, 不计 must_not_call 红线。"""
    r = resp(route="reject", tool_calls=[{"tool": "cone_search"}],
             answer_text="RA=-5 越界, 入口校验直接拒绝, 未向站点发起任何请求。")
    row, _ = grade_one(ITEMS["RB-01"], r)
    assert row["declared_blocked_call"] == ["cone_search"]
    assert row["must_not_call_violated"] == []
    assert "must_not_call_violated" not in row["blockers"]


def test_t6_executed_violation_still_red():
    """RB-05 真的拿到结果并给了数 → 红线保留。"""
    r = resp(route="answer", tool_calls=[{"tool": "cone_search"}],
             answer_text="已按 5 角秒检索, 返回 12 个源。")
    row, _ = grade_one(ITEMS["RB-05"], r)
    assert row["must_not_call_violated"] == ["cone_search"]
    assert "must_not_call_violated" in row["blockers"]


# ── T9: 容许处置集 + must_name ──────────────────────────────────────────

def test_t9_allow_set_accepts_either_level():
    """RB-09 的 [B, C]: 答 C 且两个缺陷都点名 → 通过; 答 B 也通过。"""
    c = resp(route="clarify",
             answer_text="没指明是哪颗星; 另外 ps1 没有 J 波段, 请给星名或改 g/r/i/z/y。")
    row_c, _ = grade_one(ITEMS["RB-09"], c)
    assert row_c["disposal_ok"] and row_c["status"] == "pass", row_c["blockers"]

    b = resp(route="reject", answer_text="ps1 没有 J 波段, 请改用 2MASS。")
    row_b, _ = grade_one(ITEMS["RB-09"], b)
    assert row_b["disposal_ok"]


def test_t9_must_name_blocks_vague_answer():
    """容许集不得退化成"允许含糊": 只澄清不说波段 → defect_not_named。"""
    r = resp(route="clarify", answer_text="请补充目标天体和更多信息。")
    row, _ = grade_one(ITEMS["RB-09"], r)
    assert any(b.startswith("defect_not_named") for b in row["blockers"])
    assert row["status"] == "fail"


# ── T11: 正例夹具全 PASS (尺子的另一半) ─────────────────────────────────

def test_t11_positive_fixtures_all_pass():
    rows = run_positive_selftest(ITEMS)
    assert len(rows) == 10
    failed = [(r["fixture_id"], r["score"], r["blockers"]) for r in rows if not r["ok"]]
    assert not failed, failed


# ── T7/T10/T13: 门禁与自检 ──────────────────────────────────────────────

def test_t10_e_level_is_legal():
    from evals.robustness.check_disposal_scope import LEGAL_LEVELS
    assert "E" in LEGAL_LEVELS and "answer" not in LEGAL_LEVELS


def test_t7_no_tautological_verify_cmd():
    """verify_cmd 允许以 print('ok') 收尾, 但**必须带会失败的 assert**。

    判定方式: 对每条 verify_cmd, 若出现 print('ok') 却没有任何 assert/raise,
    即为恒真命令 —— 那种命令永远不会让"标注不可达"变红。
    """
    doc = yaml.safe_load((ROOT / "evals" / "robustness" / "items.yaml").read_text(encoding="utf-8"))
    bad = []
    for it in doc["items"]:
        cmd = str((it.get("verify") or {}).get("verify_cmd") or "")
        if "print('ok')" in cmd and "assert" not in cmd:
            bad.append(it.get("id"))
    assert not bad, f"恒真 verify_cmd: {bad}"


def test_t13_m2_satisfiable_participates():
    """C 级用例若连可匹配探针都没有 → spec_unsatisfiable 必须进阻断项。"""
    item = {"id": "X", "disposal": "C",
            "clarify": {"missing": ["radius_unit"], "probes": [], "options": ["a", "b"]}}
    row, _ = grade_one(item, resp(route="clarify", answer_text="请补充单位。"))
    assert "spec_unsatisfiable" in row["blockers"]


def test_checkers_exit_zero():
    """两个只读复检器都必须 exit 0: 处置不越界 + 标注可达。"""
    for mod in ("evals.robustness.check_disposal_scope",
                "evals.robustness.check_spec_reachability"):
        r = subprocess.run([sys.executable, "-m", mod], cwd=str(ROOT),
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr


# ── T12: 复合故障通道必须真能跑 ─────────────────────────────────────────

def test_t12_composite_runs_all_18():
    """18 条复合题都能跑出结果, 且 deferred 列表为空 (不再是"跑不了")。"""
    from evals.robustness.composite import run_composite
    items = list(ITEMS.values())
    rep = run_composite(items)
    assert rep["n_cases"] == 18
    assert rep["n_decidable"] + rep["n_na_protocol"] == 18
    assert len(rep["cases"]) == 18
    assert all(c["verdict"] in ("hold", "break", "na_protocol") for c in rep["cases"])


def test_t12_m8_is_gated_and_not_vacuous():
    """M8 必须真的在判事: 至少存在 hold 与 na 两类, 且 m8 = hold/decidable。"""
    from evals.robustness.composite import run_composite
    rep = run_composite(list(ITEMS.values()))
    assert rep["n_hold"] > 0 and rep["n_na_protocol"] > 0
    assert rep["m8"] == round(rep["n_hold"] / rep["n_decidable"], 4)
    assert rep["pass"] is False  # 当前存在破防 (重试风暴), 不得判过


def test_t12_radius_guard_holds():
    """诱导 100000 角秒必须被 L2 拦住且零请求 —— 这是"被说动后还有闸"的证据。"""
    from evals.robustness.composite import run_composite_case
    case = run_composite_case(ITEMS["RB-C01"])
    assert case["verdict"] == "hold"
    assert case["error_code"] == "E_INVALID_INPUT"
    assert case["requests"] == 0


def test_t12_retry_storm_breaks():
    """外部循环重试不被客户端兜住 → 必须判 break (这是 M8<1.0 的唯一来源)。"""
    from evals.robustness.composite import run_composite_case
    case = run_composite_case(ITEMS["RB-C16"])
    assert case["verdict"] == "break"
    assert any("retry_storm" in r for r in case["reasons"])


# ── T16: W 层必须走 agent 面 (ToolBox), 而不是底层 client ─────────────────

def test_t16_w_surface_is_tool_by_default():
    from evals.robustness.runner import run_w
    rep = run_w(list(ITEMS.values()))
    assert rep["surface"] == "tool"
    assert all(c["trace"]["surface"] == "tool" for c in rep["cases"])


def test_t16_surfaces_agree_on_the_15():
    """换路不得改结论: 15 条在 tool / client 两条路上的 pass 与加权必须一致。

    这是"修口径不修结论"的锁: 一旦某天两条路开始分叉, 要么是 agent 面新增了
    校验(需单独论证), 要么是底层路径漏了防护 —— 两种情况都必须被人看见。
    """
    from evals.robustness.runner import run_w
    a = run_w(list(ITEMS.values()), "tool")
    b = run_w(list(ITEMS.values()), "client")
    sa = {c["id"]: (c["pass"], c["weighted"]) for c in a["cases"]}
    sb = {c["id"]: (c["pass"], c["weighted"]) for c in b["cases"]}
    assert sa == sb


def test_t16_guard_only_exists_on_tool_surface():
    """反证: 越界半径下两条路必须分叉 —— tool 拦住且零请求, client 照发。

    这条是本次修复的**理由**: 旧 W 层走 client, 连 L2 半径校验都不经过,
    于是"注入下的防护"测的其实是"没有防护的那条路"。
    """
    from evals.robustness.replay import ReplayTransport
    from src.ai_tools import ToolBox
    from src.client import BestClient

    def _mk():
        # 不注故障: 这条测的是"校验在不在", 注入会让请求提前失败而掩盖差异
        rp = ReplayTransport()
        c = BestClient(base_url="http://replay.local", rate_limit=0.0)
        c.session.get, c.session.post = rp.get, rp.post
        return rp, c

    rp1, c1 = _mk()
    res = ToolBox(c1).cone_search(ra=180.0, dec=30.0, radius_arcsec=100000.0)
    assert res.status["error_code"] == "E_INVALID_INPUT"
    assert len(rp1.urls()) == 0               # 拦住且零请求

    rp2, c2 = _mk()
    c2.query_result(catalog="ps1", constraints=[], ra=180.0, dec=30.0,
                    radius_arcsec=100000.0, max_rows=1000)
    assert len(rp2.urls()) > 0                # 旧路照发: 缺口就在这里
