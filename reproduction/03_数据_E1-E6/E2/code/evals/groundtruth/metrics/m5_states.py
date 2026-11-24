# -*- coding: utf-8 -*-
"""evals.groundtruth.metrics.m5_states — M5 空值/零值/无结果/报错四态区分 (权重 0.10)。

四态混淆矩阵 (E2 §6 M5): {EMPTY_RESULT, NULL_FIELD, ZERO_VALUE, ERROR},
对角线/总数 = 区分正确率。**阻断项**: 任何一次 ERROR → EMPTY 的混淆
(把服务故障读成科学结论) 直接判 E2 FAIL — 这不是扣分问题。

判定口径:
  - EMPTY 无结果: success ∧ rows=0 ∧ error 空 ∧ total_count=0 ∧ truncated=false;
  - NULL 空值: 显式 null/None 或哨兵 (不参与数值运算);
  - ZERO 零值: 真实 0.0 原样输出 (不被当缺失丢掉);
  - ERROR 报错: success=false + error_code, 绝不降级为空结果。
"""
from __future__ import annotations

# 本地: 哨判定 (canonical 单点)
from evals.groundtruth.canonical import is_sentinel  # 同实验内 import; 哨兵形态的 SSOT 在 _data, 指标只读不算


def _classify_state(rows: list, envelope: dict) -> str:
    """把一次结果归入四态之一 (EMPTY/NULL/ZERO/ERROR 的状态级判定)。"""
    if envelope.get("success") is False or envelope.get("error_code"):   # 失败态最优先: success=false 或带 error_code 都算, 先判它才不会被空行盖住
        return "ERROR"   # ERROR 单独成态, 不与 EMPTY 合并: 故障被读成"无结果"是科学结论错误
    if not rows:   # 走到这里说明调用成功, 无行才是真空结果
        return "EMPTY"
    has_null = any(                                                                        # 缺失按三形态认: None / 空串 / 该字段专属的哨兵
        v is None or v == "" or (isinstance(v, str) and is_sentinel(k, v))
        for r in rows for k, v in r.items()                                                      # 键名必须一起传进来: 哨兵只对特定字段才有意义
    )   # 键名一起传进 is_sentinel: 哨兵只对特定字段有意义, 逐值裸判会误伤普通文本列
    has_zero = any(                                                                             # 零值单独判: 与缺失不混算, 否则两轴永远分不开
        isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) == 0.0     # 强转 float 再比零: 整数 0 与 0.0 要落在同一轴上
        for r in rows for v in r.values()                                                        # 只取值不比键: 零值与列名无关, 无需按字段挑
    )   # 显式排 bool: Python 里 False == 0.0, 不排会把布尔标志位读成零值行
    if has_null:   # NULL 优先于 ZERO: 同行既有缺失又有零值时按更保守的缺失算
        return "NULL"
    if has_zero:   # 真 0.0 必须原样输出而不是当缺失丢掉 (E2 §6 M5 零值轴)
        return "ZERO"
    return "ROWS"   # 兜底: 有行、无缺失、无零值


def score_m5(gold: dict, actual: dict) -> dict:
    """M5: 四态区分正确率 + ERROR→EMPTY 阻断 + 哨兵参与运算检查。"""
    gold_state = gold.get("result_state", "rows")   # 缺省 rows: GT 未声明状态时不误判成硬状态
    envelope = actual.get("envelope") or {}   # 信封只在内存内: 离线回放由 SnapshotTransport 造, 不打真实站点
    rows = actual.get("rows") or []   # 同上, or () 兜住"有信封无行"的失败回包
    actual_state = _classify_state(rows, envelope)   # 状态判定只在 _classify_state 一处发生, 避免两套口径打架

    # GT 的 rows 态允许 NULL/ZERO 子态 (行内有缺失/零值是正常数据);
    # GT 的 empty/error 是硬状态, 必须精确匹配。
    state_ok = (actual_state in ("ROWS", "NULL", "ZERO")
                if gold_state == "rows" else actual_state == gold_state.upper())

    error_to_empty = (gold_state == "error" and actual_state == "EMPTY")   # 阻断项: 故障读成无结果, 扣分掩盖不了

    # 哨兵当真值: 回答/统计里出现哨兵值且未声明缺失 — 由调用方经
    # actual["sentinel_as_value"] 传入 (L0 预筛标记), 本指标只汇总。
    sentinel_as_value = bool(actual.get("sentinel_as_value"))   # 哨兵参与统计: -999 被当成极暗星等纳入了均值
    null_shown_as_zero = bool(actual.get("null_shown_as_zero"))   # 缺失被填 0: 数值统计被静默带偏, 记独立 blocker

    blockers = []   # 空列表即无阻断; pass 位先看它再看 state_ok
    if error_to_empty:                                                                         # 状态混淆排最前: 扣分掩盖不了把服务故障读成无结果
        blockers.append("ERROR_REPORTED_AS_EMPTY")   # 状态混淆, 三个码里优先级最高
    if sentinel_as_value:                                                                       # 哨兵参与统计独立成项: 它会静默带偏全部数值指标
        blockers.append("SENTINEL_AS_VALUE")   # 哨兵未按缺失处理
    if null_shown_as_zero:                                                                  # 缺失被填 0 单独记账: 与哨兵不同源, 不可合并成一条
        blockers.append("NULL_SHOWN_AS_ZERO")   # 空值被改写成 0
    deductions = sum([error_to_empty, sentinel_as_value, null_shown_as_zero])   # 每项扣 1 分, 三项同踩直接归零
    score = max(0.0, (1.0 if state_ok else 0.0) - deductions)   # 先给状态对错的基本分, 再减阻断, 下限夹到 0
    return {
        "score": score,
        "pass": (not blockers) and state_ok,   # pass 比 score 严: 有 blocker 就在归零之前先判 FAIL
        "gold_state": gold_state,
        "actual_state": actual_state,
        "state_match": state_ok,
        "error_to_empty": error_to_empty,
        "sentinel_as_value": sentinel_as_value,
        "null_shown_as_zero": null_shown_as_zero,
        "blockers": blockers,
    }
