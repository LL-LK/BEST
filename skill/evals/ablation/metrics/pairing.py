# -*- coding: utf-8 -*-
"""evals.ablation.metrics.pairing — 预登记核对的**配对证据层**。

**为什么需要它 (2026-10-10, 实测倒挂)**: 原判据只用"聚合 Δ 的符号"判方向, 于是出现
**标签与证据强度反相关**:

| 条目 | 配对不一致对 | p | 旧标签 |
|------|-------------|---|--------|
| A5 `HR_num` | 6 : 7 (一次抛硬币) | 1.0000 | **反向** (最强标签) |
| A3 `RejectAcc` | 18 : 0 (全票) | <1e-4 | **未命中** |
| A3 `route_ok` | 36 : 0 (全票) | <1e-4 | — |

**"反向"是最强的断言, 却由最弱的检验触发。** 本模块把**逐题配对**证据算出来,
供 `prereg.py` 把标签升级为"方向 × 可辨性"两维。

**口径 (必须与 aggregate 的定义一致, 否则核错指标)**:
  * ``HR_num``   = ``E.unsourced_numbers`` 为真                (分母: 全部 run)
  * ``HR_claim`` = ``E.unsupported_claims`` 为真                (分母: 全部 run)
  * ``ParamHallucination`` = ``D.param_hallucination`` 为真     (分母: 全部 run)
  * ``MissedClarify`` = ``not D.route_ok``, **仅 C 类**         (分母: C 类 run)
  * ``RejectAcc`` = ``_reject_score`` **分级值**, 仅 R 类        (走符号计数, 非二值)

判别力参考: n=30 配对题 (90 run) 下, 需 ``|b-c| >= 6`` 才达 McNemar 精确 p<0.05。
"""
from __future__ import annotations

# 标准库: 精确二项系数 (McNemar 精确检验)
from math import comb

# 显著性门槛: |b-c| >= 该值才记"显著" (n=30 配对题下 p<0.05 的临界)
SIGNIFICANT_MIN = 6


# 有逐 run 二值口径的指标 (其余指标没有配对口径, 核对时如实标 ·未配对)
SUPPORTED = ("HR_num", "HR_claim", "ParamHallucination", "MissedClarify")


def _flag(card: dict, metric: str, item_id: str) -> bool | None:
    """取该 metric 在该 run 上的二值; **不适用**该题时返回 None (由调用方跳过)。"""
    if metric == "HR_num":
        return bool((card.get("E") or {}).get("unsourced_numbers"))
    if metric == "HR_claim":
        return bool((card.get("E") or {}).get("unsupported_claims"))
    if metric == "ParamHallucination":
        return bool((card.get("D") or {}).get("param_hallucination"))
    if metric == "MissedClarify":
        if not item_id.startswith("E5-C"):                       # 口径: 仅 C 类进分母
            return None                                          # **不适用**, 不是"值为假"
        return not bool((card.get("D") or {}).get("route_ok"))
    return None


def mcnemar_exact(b: int, c: int) -> float:
    """McNemar 精确双尾 p (b/c 为两类不一致对数)。"""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / (2 ** n))


def pair_counts(runs: list[dict], items: list[dict], system: str, base: str,
                metric: str, scorer) -> dict | None:
    """逐题配对比较 ``system`` 与 ``base``, 返回不一致对数与显著性。

    Args:
        runs: 逐 run 轨迹 (须含 system/item/attempt)。
        items: 任务集 (用于把 item id 交给 scorer)。
        system: 被核对系统 (如 ``"A3"``)。
        base: 基准系统 (恒为 ``"B3"``)。
        metric: 指标名 (须在 :func:`_flag` 支持表内)。
        scorer: ``score_run(item, run) -> card`` 可调用 (注入以免循环 import)。

    Returns:
        ``{"b","c","p","significant","n_pairs"}``; 该 metric 无配对口径时返回 ``None``。
    """
    if metric not in SUPPORTED:                                  # 无口径: 整条不给显著性
        return None
    by_item = {str(i.get("id")): i for i in items}               # item id -> item
    cards: dict[tuple[str, str], dict] = {}                      # (系统, 题@轮) -> 成绩单
    for run in runs:
        sid = str(run.get("system"))                             # 系统
        if sid not in (system, base):
            continue
        item = by_item.get(str(run.get("item")))
        if item is None:
            continue
        key = (sid, f"{run.get('item')}@{run.get('attempt')}")   # 题与轮合成配对键
        cards[key] = scorer(item, run)
    b = c = 0                                                    # b: 消融命中而基准未; c: 反之
    for (sid, k), card in cards.items():
        if sid != system:
            continue
        other = cards.get((base, k))
        if other is None:                                        # 缺对侧即跳过 (不硬配)
            continue
        item_id = str(k).split("@")[0]                           # 题号 (判类用)
        av = _flag(card, metric, item_id)
        bv = _flag(other, metric, item_id)
        if av is None or bv is None:
            continue                                             # **不适用该题**: 跳过, 不中断整条
        if av and not bv:
            b += 1
        elif bv and not av:
            c += 1
    p = mcnemar_exact(b, c)                                      # 精确双尾
    return {"b": b, "c": c, "p": round(p, 4),
            "significant": abs(b - c) >= SIGNIFICANT_MIN, "n_pairs": b + c}
