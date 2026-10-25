# -*- coding: utf-8 -*-
"""evals.ablation.metrics.prereg — 预登记假设的**机器核对** (表 2.2「预登记核对」栏)。

**为什么需要它 (2026-10-10)**: ``hypotheses.yaml`` 早已冻结 (含 ``prediction`` 的
方向/区间与 ``falsified_if`` 的否证条件), 但报告表 2.2 的「预登记核对」列五行一直停在
``待核对 (跑后只核对不改写)`` —— 那句话把**核对**本身留给了人。留给人不是"纪律更严",
而是**没有执行者**: 没人核, 这一栏就永远是"待核对", 而读者会以为假设还没验。

本模块把核对做成机器动作, 且**只读不写**: ``hypotheses.yaml`` 一个字节都不改
(不改写是防 HARKing 的铁律, 见 E5 §11 阻断项 6)。核对结论只进报告。

判据 (只认 ``prediction`` 里**可机析**的那几种写法, 析不动的如实标"不可机析"):
  * 区间 ``"+0.15 ~ +0.35"`` → 观测 Δ 落在闭区间内记「命中」;
  * 关系 ``"> 0"`` → 观测值满足关系记「命中」;
  * 方向词 ``下降 / 上升`` → 观测 Δ 的符号与之一致记「命中」;
  * 符号与 ``direction`` 相反 → 记「反向」(不是"未命中": 反向是更强的信号);
  * 其余 → 记「未命中」。

对外接口: :func:`verdicts` (逐条核对) / :func:`render_prereg` (渲染表 2.2 的那一列)。

依赖: 只用标准库 + 本实验内件。不 import 被测产品代码。
"""
from __future__ import annotations

# 标准库: 正则 (解析冻结文本) / 类型标注
import re
from typing import Any, Optional

# 本地: 逐题配对证据 (显著/不可辨) —— 与 aggregate 同口径, 不另造一套取数规则
from evals.ablation.metrics import pairing

# 预登记里的指标键 → composite 成绩单里的真键。**必须一一对应**, 别名会静默核错指标。
_METRIC_KEYS: dict[str, str] = {
    "esr_full_delta": "ESR_full",           # 端到端成功率 (全集)
    "esr_data_delta": "ESR_data",           # 端到端成功率 (取数域)
    "esr_know_delta": "ESR_know",           # 端到端成功率 (知识域)
    "row_f1_delta": "RowF1",                # 行集 F1 (取数门)
    "field_consistency_delta": "FieldConsistency",   # 字段一致率 (取数门)
    "trunc_triple_delta": "TruncTriple",    # 截断三元组 (取数门)
    "reject_acc_delta": "RejectAcc",        # 该拒则拒的准确率
    "missed_clarify_delta": "MissedClarify",  # 该问不问的漏澄清率
    "avg_calls_delta": "AvgCalls",          # 平均工具调用数 (代价)
    "http_requests_delta": "http_requests",  # 平均 HTTP 请求数 (代价)
    "hr_any_delta": "HR_any",               # 幻觉三通道任一命中率
    "hr_num_delta": "HR_num",               # 数值通道
    "hr_claim_delta": "HR_claim",           # 主张通道
    "param_hallucination": "ParamHallucination",   # schema 外参数 (红线)
}

_BAND_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*~\s*([+-]?\d+(?:\.\d+)?)")   # "+0.15 ~ +0.35"
_REL_RE = re.compile(r"([<>])\s*([+-]?\d+(?:\.\d+)?)")                     # "> 0"
_DOWN_RE = re.compile(r"下降|降低|减少")                                     # 方向词: 变差
_UP_RE = re.compile(r"上升|抬升|增加")                                       # 方向词: 变好


def _delta(cards: dict, contrast: str) -> Optional[dict[str, float]]:
    """按 ``"B3 - B2b"`` 形态的对照算逐指标 Δ (左减右); 缺任一系统或指标返 None。"""
    if " - " not in contrast:                                    # 形态不对就不猜
        return None
    left, right = (part.strip() for part in contrast.split(" - ", 1))   # 左减右
    a, b = cards.get(left), cards.get(right)
    if not a or not b:                                           # 对照的任一侧没跑 (如 B2a 缺) 即不可核
        return None
    out: dict[str, float] = {}
    for key in set(a) & set(b):                                  # 只比两侧都有的指标
        va, vb = a.get(key), b.get(key)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):   # 非数值 (N/A / None) 不进 Δ
            out[key] = float(va) - float(vb)
    return out


def _verdict_one(text: str, observed: float, direction: str, pair: Optional[dict] = None) -> str:
    """单条预测文本的核对结论 (只认可机析的写法)。

    **符号归属 (2026-10-10 纠错)**: 判定"反向"必须用**该条预测自己的方向**, 不能用
    假设级的 ``direction``。``direction`` 描述的是**组件整体的好坏走向**, 而单条
    指标可以有相反的预期 —— 例如 A3 的 ``direction: down`` (拆掉后整体掉分), 但
    ``missed_clarify_delta: "+0.30 ~ +0.60"`` 明写"该问不问**上升**"。
    初版把假设级 direction 套到每一条上, 于是 A3 的 MissedClarify 实测 **+1.0**
    (方向与预测一致, 只是**超出区间上界**) 被判成"反向" —— 那是量级未命中, 不是反向。
    现改为: 区间自带符号 (``hi<=0`` 预测降 / ``lo>=0`` 预测升), 只有符号相反才算反向。

    **可辨性维度 (2026-10-10 补)**: 除方向外还标证据够不够分辨。实测倒挂 ——
    A5 的 ``HR_num`` 不一致对 **6:7** (抛硬币, p=1.0) 拿到最强标签"反向",
    而 A3 的 ``RejectAcc`` **18:0** (全票, p<1e-4) 只记"未命中"。故标签升级为
    ``同向/反向 × 显著/不可辨`` (显著 = ``|b-c| >= 6``, 即 n=30 配对下 p<0.05)。
    ``pair`` 为 None 时标 ``·未配对`` —— 如实说明该指标没有逐 run 配对口径, 不冒充有。
    """
    band = _BAND_RE.search(text)                                 # 区间写法优先 (信息量最大)
    if band:
        lo, hi = sorted((float(band.group(1)), float(band.group(2))))   # 允许写成 "-0.35 ~ -0.05" 的反序
        if lo <= observed <= hi:
            return "命中"
        if observed == 0:                                        # 零变化: 没有方向可言
            return "无方向"
        same = not ((lo >= 0 and observed < 0) or (hi <= 0 and observed > 0))   # 区间自带方向
        return _label(same, pair)                                # 方向对但超界 -> 同向·不可辨/显著
    rel = _REL_RE.search(text)                                   # 关系写法次之
    if rel:
        op, bound = rel.group(1), float(rel.group(2))
        ok = observed > bound if op == ">" else observed < bound
        if ok:
            return "命中"
        if observed == 0:
            return "无方向"
        same = not (op == ">" and observed < bound and bound >= 0)   # "> 0" 却为负 -> 反向
        return _label(same, pair)
    if _DOWN_RE.search(text):                                    # 方向词: 预期下降
        return "命中" if observed < 0 else ("无方向" if observed == 0 else _label(False, pair))
    if _UP_RE.search(text):                                      # 方向词: 预期上升
        return "命中" if observed > 0 else ("无方向" if observed == 0 else _label(False, pair))
    return "不可机析"                                              # 析不动就如实说, 不硬判


def _label(same_dir: bool, pair: Optional[dict]) -> str:
    """按"方向 × 可辨性"给出标签; 无配对口径时如实标 ``·未配对`` (不冒充已检验)。"""
    if pair is None:
        return "同向·未配对" if same_dir else "反向·未配对"
    tag = "显著" if pair.get("significant") else "不可辨"
    return f"{'同向' if same_dir else '反向'}·{tag}"


def _pairs_for(spec: dict, system: str, base: str, runs: Optional[list],
               items: Optional[list], scorer) -> dict[str, dict]:
    """为该条的每个可机析指标算配对证据; 缺 runs/scorer 或无口径时该指标不进表。"""
    if not runs or not items or scorer is None:                  # 未提供轨迹 -> 全部走 ·未配对
        return {}
    out: dict[str, dict] = {}
    for key in (spec.get("prediction") or {}):                   # 只算 prediction 段提到的指标
        metric = _METRIC_KEYS.get(key)
        if not metric:
            continue
        got = pairing.pair_counts(runs, items, system, base, metric, scorer)
        if got is not None:
            out[metric] = got                                    # 无口径的指标不进表 (如实缺席)
    return out


def verdicts(cards: dict, hypotheses: dict, runs: Optional[list] = None,
             items: Optional[list] = None, scorer=None) -> dict:
    """逐条核对预登记假设, 返回 ``{id: {verdict, details}}``。

    Args:
        cards: :func:`~evals.ablation.metrics.composite.aggregate` 的成绩单 ``{系统: 卡}``。
        hypotheses: ``hypotheses.yaml`` 的已冻结内容 (本函数**只读**)。
        runs: 可选逐 run 轨迹; 给了才做**逐题配对**并标"显著/不可辨"。
        items: 可选任务集 (配对需要 item 上下文)。
        scorer: 可选 ``score_run(item, run) -> card``; 与 runs 同时给才生效。

    Returns:
        ``{"entries": {id: {...}}, "summary": {...}}``; ``entries`` 里每条含
        逐指标观测 Δ、配对证据、该条结论与不可机析的条数。
    """
    entries: dict[str, dict[str, Any]] = {}
    # 基线四级: 对照写在 contrast 字段里 (如 "B3 - B2b")
    for spec in hypotheses.get("baselines") or []:
        hid = str(spec.get("id"))                                # 条目标识
        contrast = str(spec.get("contrast") or "")               # 对照式
        observed = _delta(cards, contrast)                       # 逐指标 Δ
        parts = [p.strip() for p in contrast.split(" - ", 1)] if " - " in contrast else []
        pairs = _pairs_for(spec, parts[0], parts[1], runs, items, scorer) if len(parts) == 2 else {}
        entries[hid] = _judge(spec, observed, pairs)
    # 单组件消融: 对照恒为"相对 B3", 且**符号约定必须与 report.py 的 T2.2 一致** ——
    # report.py 用 ``base = cards["B3"]`` 且注释写明"所有 Δ 都是相对完整系统的差",
    # 即 Δ = **消融系统 − B3** (被消融系统自身的变化, 负 = 掉分)。
    #
    # 【纠错留痕 2026-10-10】初版此处写成 ``f"B3 - {hid}"`` (反号), 于是五条消融
    # 全部机析为"反向"。取证: 归档的旧 live 报告 T2.2 打印 A3 的 ΔRejectAcc = **-0.639**,
    # 而旧批 B3=0.639 / A3=0.000 —— 只有 A3−B3 能复现 -0.639; 且冻结区间
    # ``-0.30 ~ -0.60`` **正好含** -0.639, 说明区间也是按 A−B3 标定的。
    # 结论: **冻结文本与既有报告代码为准, 出错的是本判据的符号**。已改正。
    for spec in hypotheses.get("ablations") or []:
        hid = str(spec.get("id"))                                # 条目标识
        observed = _delta(cards, f"{hid} - B3")                  # 消融相对 B3: 与 T2.2 同号
        pairs = _pairs_for(spec, hid, "B3", runs, items, scorer)  # 逐题配对证据
        entries[hid] = _judge(spec, observed, pairs)
    tally: dict[str, int] = {}                                   # 结论计数
    for item in entries.values():
        tally[item["verdict"]] = tally.get(item["verdict"], 0) + 1
    return {"entries": entries, "summary": tally}                # 逐条 + 汇总


def _judge(spec: dict, observed: Optional[dict[str, float]],
           pairs: Optional[dict[str, dict]] = None) -> dict:
    """把一条预登记规格与观测 Δ 对起来, 给出结论 (不改写规格)。"""
    direction = str((spec.get("prediction") or {}).get("direction") or "")
    if observed is None:                                         # 对照缺一侧: 不可核, 不硬判
        return {"verdict": "不可核 (对照缺一侧)", "details": {}, "unparsed": 0}
    pairs = pairs or {}                                          # 无配对证据时逐条走 ·未配对
    details: dict[str, dict[str, Any]] = {}                      # 逐指标留痕
    unparsed = 0                                                 # 析不动的条数
    for key, text in (spec.get("prediction") or {}).items():     # 只核 prediction 段
        metric = _METRIC_KEYS.get(key)                           # 指标键映射
        if not metric or metric not in observed:                 # 非指标键 (如 direction/note) 或该指标无观测
            continue
        got = observed[metric]                                   # 观测 Δ
        pair = pairs.get(metric)                                 # 该指标的配对证据 (可能缺)
        verdict = _verdict_one(str(text), got, direction, pair)  # 单条结论
        if verdict == "不可机析":
            unparsed += 1                                        # 计数: 披露"有几条没机析"
        details[metric] = {"observed_delta": round(got, 4),
                           "predicted": str(text), "verdict": verdict,
                           "pair": pair}                         # 配对证据随条留痕
    judged = [d["verdict"] for d in details.values()]            # 有结论的那些
    overall = (_aggregate(judged) if judged                      # 按强度取最强标签 (见 _aggregate)
               else ("不可机析" if unparsed else "无可核指标"))    # 一条都没机析出来时如实说
    return {"verdict": overall, "details": details, "unparsed": unparsed}


# 汇总优先级: 从强到弱, **只列有方向含义的标签**。
# **必须原样沿用逐指标标签** ——
# 【纠错留痕 2026-10-10】初版用 ``any(v.startswith("反向"))`` 再**写死**成 "反向·不可辨",
# 于是"从未做过显著性检验"的 `反向·未配对` 被改写成"检验过且分不出"的 `反向·不可辨` ——
# 两者是不同的主张 (前者是**没测**, 后者是**测了不显著**), 混同即是 fail-open。
_PRIORITY = ("反向·显著", "反向·不可辨", "反向·未配对",
             "同向·显著", "同向·不可辨", "同向·未配对")


def _aggregate(judged: list[str]) -> str:
    """把逐指标标签汇总成一条: 按强度取最强, 且**原样沿用**, 不改写语义。

    ``无方向`` **不进优先级** —— 它表示"某条指标毫无变化", 不该盖过其它条目的命中。
    有命中又有无变化时记 ``部分命中`` (比笼统的"无方向"更如实)。
    """
    if all(v == "命中" for v in judged):                         # 全中才记命中
        return "命中"
    for label in _PRIORITY:                                      # 从强到弱找第一个出现的
        if label in judged:
            return label
    if "命中" in judged:                                         # 有中、也有无变化/不可机析
        return "部分命中"
    return "无方向"                                               # 其余情形: 确实没有方向


def render_prereg(result: dict, ids: list[str]) -> str:
    """把若干条核对结论渲染成表 2.2「预登记核对」栏的单元格文本。"""
    cells = []                                                   # 逐条单元格
    for hid in ids:
        item = (result.get("entries") or {}).get(hid) or {}      # 缺条目按未知处理
        cells.append(f"{hid}={item.get('verdict', '未核')}")     # 形如 "A1=未命中"
    return "；".join(cells)                                      # 一格内并列, 不撑破表格
