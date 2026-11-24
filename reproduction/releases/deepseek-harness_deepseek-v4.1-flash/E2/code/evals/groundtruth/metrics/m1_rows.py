# -*- coding: utf-8 -*-
"""evals.groundtruth.metrics.m1_rows — M1 行集判定 (权重 0.30)。

**两种口径, 按 ``actual["mode"]`` 分派** (2026-10-07 引入, 依据裁定 D6
「回放作确定性回归基线, 实跑作放行闸; 两层职责分开」):

===============  ==========  ==========================================
mode             口径        依据
===============  ==========  ==========================================
``replay``       行集 P/R    金标准冻结的行主键集 (固定期望值)
``live``         行集不变量  结果集自身的内部一致性 (无跨时间期望值)
===============  ==========  ==========================================

为什么必须分两套, 不能只留一套:

- **回放层必须有 P/R**: 快照冻结了那一刻的答案, 逐行比对是**唯一**能抓
  "分页漏行 / 重复行 / 越界行"的判据。去掉它, 回归基线就只剩"跑通了"，
  而跑通与算对是两件事 —— 这正是 N1 记的「按构造必然满分」那种自证线。
- **实跑层不能用 P/R**: 活站点的数据随时间变。实测同一查询 (ps1/180/30/60″)
  快照记 **1** 行、真站点返 **174** 行。拿一份会过期的行集去比对活数据,
  必然大面积失配, 而失配里没有一条能指向被测代码的缺陷 —— 那不是判据,
  是噪声。故实跑改判**不变量**。

两套口径的返回值字段名不同 (replay 报 ``precision``/``recall``/``f1``/
``tp``/``fp``/``fn``, live 报 ``n_rows``/``n_keys``/``duplicate_keys``/
``violations``)。**两套都带** ``score``/``pass``/``blockers``, 这是
:func:`~evals.groundtruth.metrics.compare_case` 唯一依赖的三个键 —— 聚合层
因此不需要知道当前是哪套口径。
"""
from __future__ import annotations

# 本地: 主键集合 (canonical 单点 — 两侧用同一把尺子才不会假不一致)
from evals.groundtruth.canonical import key_set  # 同实验内 import; 跨实验借实现会让 M1 与 M7 同时失真


def score_m1(gold: dict, actual: dict) -> dict:
    """M1 入口: 按 mode 分派到行集 P/R 或行集不变量。

    Args:
        gold: 金标准侧字典。replay 口径读 ``row_keys``/``max_rows``;
            live 口径只读 ``max_rows`` (客户端预算), 不碰行集。
        actual: 被测侧字典, 需带 ``rows`` / ``batch_keys`` / ``envelope``;
            ``mode`` 缺省按 ``replay`` 处理 —— 缺省值选严的那套,
            免得编排层忘了传 mode 时静默降级成弱判据。

    Returns:
        ``{"score", "pass", "blockers", ...}``: pass 为纯布尔, 加权分不得覆盖它。
    """
    if str(actual.get("mode") or "replay") == "live":
        return _live_invariants(gold, actual)  # 实跑: 无跨时间期望值, 只查内部自洽
    return _replay_rowset(gold, actual)  # 回放: 快照冻结了答案, 逐行比对是唯一强判据


def _replay_rowset(gold: dict, actual: dict) -> dict:
    """回放口径: 行集 precision/recall/f1 (E2 §6 M1 原判据)。

    TP = |K(R) ∩ K(G)|, FP = |K(R) \\ K(G)|, FN = |K(G) \\ K(R)|;
    precision 与 recall **双双**为 1.0 才 pass —— 数据查询不接受"差不多"。
    分母为 0 约定 1.0 并打 degenerate 标记 (GT 空 + SUT 空的"双空吻合"
    必须由 M5 的 result_state 再判一次, 不在此处冒充满分)。
    """
    gold_keys = set(gold.get("row_keys") or ())   # GT 侧已是主键序列, 直接成集; or () 兜住缺字段
    # batch 由 run_e2 按**查询**传下来 (proximity 才带 in<N>: 前缀): 站点对锥搜
    # 响应同样回 inputobjs_input_line, 靠行内列推断会把锥搜全量错判成批量行。
    actual_keys = key_set(actual.get("rows") or (), batch=actual.get("batch_keys"))   # SUT 侧是行字典, 必须过 canonical 提取, 两侧同一把尺
    tp = len(gold_keys & actual_keys)   # 交集 = 真阳性, 分页并集"无重无漏"就落在这一个数上
    fp = len(actual_keys - gold_keys)   # 多出来的行: 分页重复或越界查询的典型症状
    fn = len(gold_keys - actual_keys)   # 漏掉的行: 分页截断、limit 截断或过滤条件写严了
    degenerate = not gold_keys and not actual_keys   # 双空单独打标, 绝不在此冒充分数
    precision = tp / (tp + fp) if (tp + fp) else 1.0   # 分母 0 约定 1.0 而非抛错: 空集查询是合法结果
    recall = tp / (tp + fn) if (tp + fn) else 1.0   # 同一约定, 否则空 GT 会把 recall 变成除零崩溃
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0   # F1 只作连续分, pass 另判
    # E2 §6 M1: 分母为 0 约定值 1.0 并打 degenerate 标记 — "双空吻合"不在此
    # 冒充分数, 由 M5 的 result_state 再判一次 (空结果态 vs 错误态)。
    passed = precision == 1.0 and recall == 1.0   # M1 判据: P 与 R 必须双双为 1.0, 半分不算过
    return {
        "mode": "replay",                          # 口径自报: 报告读者能分清这批比的是行集还是不变量
        "score": 1.0 if passed else f1,   # 折中分照报, 但 pass 位只认上面的布尔, 不让 0.97 蒙混过关
        "pass": passed,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp, "fp": fp, "fn": fn,   # 三元组一起报, 报告端靠它还原"多了还是少了"
        "degenerate": degenerate,
        "missing_keys": sorted(gold_keys - actual_keys)[:20],   # 只列前 20 个: 够定位即可, 全量会淹没报告
        "extra_keys": sorted(actual_keys - gold_keys)[:20],   # 排序后截断, 保证同一份输入每次输出可比
        "blockers": [] if passed else ["row_set_mismatch"],   # 单一 blocker 码: run_e2 靠它归因, 不再细分
    }


def _live_invariants(gold: dict, actual: dict) -> dict:
    """实跑口径: 在结果集**自身内部**检查不变量 (2026-10-07 新增)。

    这类判据不依赖任何跨时间的期望值, 所以活数据随时间变也不会让判据失效:

    - **主键唯一** (``fp == 0``): 复合主键 (坐标回退) 必须逐行不同。防的是分页
      重复 —— 同一个源被两页各返一次, 用户会以为有两颗星。
    - **行数不超预算**: 实际返回不得超过请求的 ``max_rows`` —— 客户端该截断没截断,
      是与站点无关的纯客户端缺陷。
    - **行数不为负 / 计数自洽**: ``returned <= total``。
    - **截断位诚实**: 站点说总数比拿到的多, 而客户端没标 truncated = 把
      "少给了数据" 伪装成 "就这么多"。

    为什么仍保留权重 0.30: 它抓的那类缺陷 (分页重复 / 静默截断) 仍然是最常见
    也最贵的失真。只是现在抓它的**依据**换成了内部一致性, 而不是一份会过期的
    答案清单。**代价要说清**: 实跑层不再能抓"值错了但结构没错" —— 那一类归回放层。

    主键口径: 真站点的 ``ps1_source_id`` **整列为空串** (实测), 所以主键落到
    :func:`evals.groundtruth.canonical.row_key` 的坐标回退分支。实测 174 行 → 174 个
    唯一键、零撞键; 若某次实跑真出现撞键, ``fp > 0`` 会把 M1 判红, 那正是"坐标键
    不足以唯一标识一行"的真实信号, 而不是误报。
    """
    rows = actual.get("rows") or ()          # 规范化后的标准行集
    envelope = actual.get("envelope") or {}  # 信封三计数: total/returned/truncated
    violations: list[str] = []               # 逐条不变量破例, 空 = 全过

    # ── 不变量 1: 主键唯一 (分页重复是最常见也最贵的失真) ──
    keys = key_set(rows, batch=actual.get("batch_keys"))
    fp = len(rows) - len(keys)               # 行数减键数 = 塌成同一主键的行数
    if fp > 0:
        violations.append(f"duplicate_keys:{fp}")  # 撞键即重复: 同一行被算了两次

    # ── 不变量 2: 行数不超请求预算 (纯客户端缺陷, 与站点无关) ──
    budget = gold.get("max_rows")
    if isinstance(budget, int) and budget > 0 and len(rows) > budget:
        violations.append(f"over_budget:{len(rows)}>{budget}")  # 该截断没截断

    # ── 不变量 3: 计数自洽 (returned 不得超过 total) ──
    total = envelope.get("total_count")
    returned = envelope.get("returned_count")
    if isinstance(total, int) and isinstance(returned, int) and returned > total:
        violations.append(f"returned_gt_total:{returned}>{total}")  # 报的数比总量还多

    # ── 不变量 4: 截断位诚实 (截断了必须说) ──
    # 站点说总数比拿到的多, 而客户端没标 truncated = 把"少给了"伪装成"就这么多"。
    # 两者任一为 None (站点没给 / 错误态) 时不判 —— 缺测不等于违约。
    truncated = envelope.get("truncated")
    if isinstance(total, int) and isinstance(truncated, bool) and total > len(rows) and not truncated:
        violations.append("truncation_undisclosed")  # 少给了却不说

    passed = not violations                     # 纯布尔: 加权分不得覆盖它
    return {
        "mode": "live",                         # 口径自报: 报告读者能分清这批查的是不变量
        "score": 1.0 if passed else 0.0,       # 二值: 不变量要么全过要么不过, 没有"差不多"
        "pass": passed,
        "n_rows": len(rows),                    # 行数: 报告要能看出这批查到了什么量级
        "n_keys": len(keys),                    # 唯一键数: 与行数相等即无重复
        "duplicate_keys": fp,                   # 单独报: 它是最常被追问的那一项
        "violations": violations,               # 逐条列: 破的是哪条不变量
        "blockers": [] if passed else ["row_invariant_violated"],  # 单一 blocker 码: 报告靠它归因
    }
