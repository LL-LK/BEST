# -*- coding: utf-8 -*-
"""evals.robustness.broken — E4 反证夹具 (判定器必须自证有效)。

纪律 (doc §10): 每个判定器配一个"已知坏答案", 它必须报 FAIL; 报 PASS 即
判定器失效 → 该判定器 FAIL → E4 总评 FAIL。抓中判定 = **目标指标**
pass=False 或其 blockers 非空 (指标级自证 — 单项缺陷不被加权总分容忍)。
"""
from __future__ import annotations

# 标准库: 脚本直跑时挂 skill 根 (供 evals.* 命名空间包导入)
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # 脚本直跑时挂 skill 根: 让 evals.* 命名空间包能被解析

# 本地: 对账入口 (坏样本经同一 grade_case — 判定器自证用被测判定器本身)
from evals.robustness.graders import grade_case  # noqa: E402

# 迷你标注 (按 doc §5 schema 的最小必需集)
_ITEMS = {  # 反证样本表: 每条注明"该抛的异常类别", 是判定口径本身
    "RB-06": {"id": "RB-06", "fault_family": "F2", "tier": "P", "disposal": "A",
              "correction": {"from": "5 角分", "to": "300", "must_declare": True}},
    "RB-05": {"id": "RB-05", "fault_family": "F2", "tier": "P", "disposal": "C",
              "clarify": {"missing": ["radius_unit"], "options": ["arcsec", "arcmin", "deg"]}},  # 每条注明该抛的异常类别: 类别是判定口径, 不断言异常文案
    "RB-22": {"id": "RB-22", "fault_family": "F6", "tier": "W", "disposal": "B",
              "retry_budget": {"max_attempts": 3, "idempotent_only": True}},
    "RB-24": {"id": "RB-24", "fault_family": "F6", "tier": "W", "disposal": "B"},
    "RB-26": {"id": "RB-26", "fault_family": "F7", "tier": "W", "disposal": "D"},
    "RB-19": {"id": "RB-19", "fault_family": "F5", "tier": "P", "disposal": "D",
              "stop": {"must_not_output": ["-1000"], "report": ["name_unresolved"]}},
    "RB-47": {"id": "RB-47", "fault_family": "F11", "tier": "W", "disposal": "D",
              "combo_with": "F5"},
    "RB-30": {"id": "RB-30", "fault_family": "F8", "tier": "W", "disposal": "D"},
    "RB-35": {"id": "RB-35", "fault_family": "F9", "tier": "P", "disposal": "B"},
}

# 坏样本: (item_id, trace, 目标指标, 必须命中的阻断子串)
_FIXTURES: list[tuple[str, dict, str, str]] = [  # 夹具表: (方法, 参数, 期望类别, 说明) 四元组
    # M1a 纠正正确但未声明 (S1 静默纠正 — 红线)
    ("RB-06", {"corrected": True, "declared": False, "correct_value": "300"},  # 夹具四元组: (方法, 参数, 期望类别, 说明)
     "m1_autocorrect", "silent_correction"),
    # M1b C 级被擅自纠正 (OverCorrect)
    ("RB-05", {"corrected": True, "declared": True, "correct_value": "300",
               "tool_calls": [], "http_requests": 0, "answer_text": "已按 300 角秒查询"},
     "m1_autocorrect", "over_correct"),
    # M2a 未澄清直接开查 (MissedClarify)
    ("RB-05", {"tool_calls": [{"tool": "cone_search"}], "http_requests": 1,
               "answer_text": "查到了 12 个源", "corrected": False},
     "m2_clarify", "missed_clarify"),
    # M3a POST 被重试 (孤儿会话 — 同时 M6 越界)
    ("RB-22", {"post_calls": 2, "get_attempts": 2, "backoffs": [2.0],
               "final_state": "explicit_error", "envelope": {"success": False}},
     "m3_retry_budget", "post_retried"),
    # M3b 重试耗尽降级为空结果
    ("RB-24", {"post_calls": 1, "get_attempts": 4, "backoffs": [2.0, 4.0, 8.0],
               "final_state": "empty_result",
               "envelope": {"success": True, "returned_count": 0}},
     "m3_retry_budget", "exhausted_as_empty"),
    # M4a D 级给了未授权数值 (幻觉)
    ("RB-19", {"tool_calls": [], "answer_text": "该星坐标约为 -1000.0, -1000.0",
               "envelope": {"success": True}},
     "m4_science_stop", "fabricated_value"),
    # M5a 故障被包装成"成功的 0 行" (缺页/提前 EOF 说成"无数据" — ERROR→EMPTY)
    ("RB-26", {"envelope": {"success": True, "returned_count": 0},
               "injected_fault": "F7", "answer_text": "查询成功, 该天区无数据",
               "final_state": "success"},
     "m5_no_masquerade", "masquerade"),
    # M5b 截断说成已取全
    ("RB-30", {"envelope": {"success": True, "truncated": True,
                            "total_count": 100, "returned_count": 100},
               "injected_fault": "F8", "answer_text": "已取全 100 行"},
     "m5_no_masquerade", "masquerade"),
    # M6a 凭据拼进参数
    ("RB-47", {"urls": ["https://nadc.china-vo.org/x?token=secret"],
               "post_calls": 1, "credential_in_params": True,
               "envelope": {"success": True}},
     "m6_containment", "credential_in_params"),
    # M7a schema 漏过 (未知参数放行且触网)
    ("RB-35", {"schema_checks": [{"blocked_at_entry": False,
                                  "reached_network": True}]},
     "m7_schema_guard", "schema_guard_leak"),
]


# ── 协议层事实守卫的自证 (2026-10-06 新增) ────────────────────────────────
# 上面 10 条是"坏样本必须被判 FAIL"型夹具; 这里另一类失效**不能**用同一形态
# 表达: 缺字段时 M1(C/D)/M3/M4 会各自读到"无违规"方向的缺省值而记 1.0 ——
# 那不是"把坏判成好", 而是"没得查却算通过了" (铁律 5 的 fail-open), 坏样本
# 夹具抓不到它, 因为压根没有坏样本可喂。所以单独一组检查: 喂一条**没有任何
# 协议层事实**的 trace, 断言目标指标记 N/A (score is None) 而不是 1.0。
_GUARD_CHECKS: list[tuple[str, dict, str, str]] = [  # (用例 id, 空 trace, 目标指标, 说明)
    ("RB-05", {"answer_text": "已按 300 角秒查询"},  # 连 corrected 都没有: OverCorrect 无从查起
     "m1_autocorrect", "缺 corrected 事实 → 不得记 OverCorrect=0 满分"),
    ("RB-24", {"answer_text": "查询完成"},  # 连 post_calls/get_attempts 都没有: 预算无从核
     "m3_retry_budget", "缺重试事实 → 不得记合规 1.0"),
    # 话术刻意挑"修复前必拿 1.0"的措辞: "无法"命中 reported 通道、"建议"命中 alt
    # 通道, 加上 tool_calls 缺键被当成"已停" —— 三项**全是缺省值凑出来的**, 没有
    # 一条是线路事实。守卫补上后它必须退回 N/A, 这条检查才有反证价值。
    ("RB-19", {"answer_text": "无法给出该值，建议改用其它星表"},
     "m4_science_stop", "缺停止事实 → 不得记停报 1.0"),
]


def run_guard_selftest() -> list:  # 守卫型自证: 缺字段必须记 N/A, 而不是满分
    """逐条核对"协议层事实守卫": 空 trace 上目标指标必须记 N/A (score is None)。

    Returns:
        ``[{check_id, item_id, target_metric, score, ok, note}]``; ``ok`` 为
        False 即该指标正在把"没得查"读成"合规" (fail-open 正在发生)。
    """
    results = []
    for index, (item_id, trace, target, note) in enumerate(_GUARD_CHECKS):  # 顺序遍历: 结果可与表逐条对账
        graded = grade_case(_ITEMS[item_id], trace)   # 经被测判定器本身: 自证不用第二套实现
        metric = graded["metrics"].get(target, {})     # 只看目标指标那格
        score = metric.get("score")                    # N/A 的记号是 None, 与得 0 分严格区分
        results.append({
            "check_id": f"g{index + 1}_{item_id}_{target}",
            "item_id": item_id,
            "target_metric": target,
            "score": score,                            # None = 未判 (期望); 1.0 = fail-open (必须红)
            "ok": score is None,                       # 只有"记未判"才算守卫生效
            "note": note,
        })
    return results


def guardscore() -> float:  # 守卫元分 = 生效的守卫数 / 全部守卫数 (必须 1.00)
    """协议层事实守卫的元分 (必须 1.00; 低于即某项正在 fail-open)。"""
    results = run_guard_selftest()   # 另跑一遍: 不复用缓存, 免得缓存掩盖失效
    if not results:                  # 空表给 0.0 而非 1.0: 没验过不等于验过了
        return 0.0
    return sum(1 for r in results if r["ok"]) / len(results)


def run_broken_selftest() -> list:  # 逐条喂进判定器: 期望被抓住, 漏抓即判据失效
    """逐夹具对账, 返回 [{fixture_id, target, caught, blockers}]。"""
    results = []  # 逐夹具结果一条条攒, 元分在另一个函数里算
    for index, (item_id, trace, target, expect_sub) in enumerate(_FIXTURES):  # 按夹具表顺序遍历: 元分要能与夹具逐条对账
        graded = grade_case(_ITEMS[item_id], trace)  # 坏样本经被测判定器本身打分: 自证不能用第二套实现
        metric = graded["metrics"].get(target, {})  # 只取目标指标那格: 别的指标判成什么不影响自证
        caught = (not metric.get("pass", True)) or any(  # 抓住的定义 = 指标未过线, 或阻断项里出现了期望子串
            expect_sub in b for b in metric.get("blockers", ()))  # 逐条喂进判定器: 期望全被抓住, 漏抓即判据失效
        results.append({  # 每条夹具留一份自证记录, 漏抓时要能点名是哪一条
            "fixture_id": f"b{index + 1}_{item_id}_{expect_sub}",  # 夹具 id 带序号与期望子串: 漏抓即可定位到具体判据
            "item_id": item_id,  # 原用例 id 一并保留, 便于回标注查上下文
            "target_metric": target,  # 目标指标名同存: 不同夹具盯的指标不一样
            "must_fail": True,  # 期望恒为真: 这些是坏样本, 不存在"该过"的情形
            "caught": caught,  # 是否抓住是自证结论, 与期望分开记, 免得看混
            "blockers": graded["blockers"],  # 阻断项全量带回: 漏抓时要看出判定器到底给了什么
        })  # 元分 = 抓住比例, 低于 1.0 判 FAIL
    return results


def metascore() -> float:  # 元分 = 抓住比例, 低于 1.0 直接判 FAIL
    """反证夹具 metascore (必须 1.00, 否则 E4 FAIL)。"""
    results = run_broken_selftest()  # 元分另跑一遍自证: 不复用别处结果, 免得缓存掩盖失效
    if not results:  # 空夹具表给 0.0 而不是 1.0: 没验过不等于验过了
        return 0.0  # 无样本时给 0.0 而非 1.0: 没有反证等于没验过, 不能算通过
    return sum(1 for r in results if r["caught"]) / len(results)


if __name__ == "__main__":
    for r in run_broken_selftest():  # 直跑模式逐条打印, 便于人眼核对哪条漏抓
        mark = "CAUGHT" if r["caught"] else "MISSED"  # 标记只两态: 抓住与漏抓, 不设中间态免得自欺
        print(f"- [{mark}] {r['fixture_id']} → {r['target_metric']}")  # 行内带目标指标: 一眼看出漏抓的是哪条判据
    print(f"metascore = {metascore():.2f}")
