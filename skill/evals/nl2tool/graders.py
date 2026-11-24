# -*- coding: utf-8 -*-
"""evals.nl2tool.graders — E1 评分器 (三类 grader + 六维指标 + 红线)。

能力边界: 把一条任务的实际轨迹 (trace) 与专家标注 (task) 逐维比对打分 —
工具选择/参数/转换/冗余/澄清/拒绝六维, 加权汇总出 E1 独立实验分。
边界: **不调大模型判分** (决策评测必须可复现可复核, E1 §7); 判定全部经
exact/normalized/python 三类 grader 完成; 每条判定保留原文证据。

白盒锚点: docs/eval-E1-nl2tool.md §6 (指标体系) / §7 (grader 实现约定);
references/tools.schema.json (参数面的唯一权威 — ParamHallucination 判定)。
"""
from __future__ import annotations

# 标准库: 数据类型标注
from typing import Any, Optional

# 本地: 七族归一化器 (normalized 档 grader 的比对前站)
from evals.nl2tool.normalizers import (
    norm_band,  # 波段归一: 必须连 system 一起比, 同名异系统不算对
    norm_catalog,  # 星表名归一: 只吃掉大小写与空白差异, 不做别名映射
    norm_column,  # 列名归一: 去首尾空白即可, 别名映射不在这一层做
    norm_coord,  # 坐标归一: 分量缺失时给 None, 由比对层判失败
    norm_number,  # 数值比较的统一入口: 绝对与相对容差都在这里定, 不各写一套
    norm_radius,  # 半径归一与坐标同源, 差别只在容差口径
    norm_set,  # 集合归一: 通用 set 档按全等比
    norm_set_covers,  # 列投影集合: 标注列必须齐全, 多投影不判错
)

# ── 权重与红线 (E1 §6.7; 启动即校验和 = 1.00, 与 scoring-rubric 同款硬约束) ──

GRADER_WEIGHTS: dict[str, float] = {                                                      # 六维权重表: 和必须为 1.00, 启动即校验, 漂了当场炸
    "toolset": 0.30,    # ToolSetF1
    "param": 0.25,      # ParamF1
    "convert": 0.15,    # Coord/Unit/Band 三项均值
    "redundant": 0.10,  # 1 - RedundantCallRate
    "clarify": 0.10,    # 1 - MissedClarifyRate (含质量折半)
    "reject": 0.10,     # RejectAcc
}

PASS_SCORE = 0.90    # 放行线: 加权分达标 **且** 红线任务清单为空
WARN_SCORE = 0.85    # 观察线: 落在 [0.85,0.90) 仍放行, 但报告须标出

# 逐维通过线 (E1 §6.7 表格第三列, 与上面两条总分线**并列**的第二道判据)。
# 加权总分达标**不代表**逐维达标: 权重最高的 toolset(0.30)+param(0.25) 拿满分
# 就贡献 0.55, 剩下 0.45 权重的 convert/redundant/clarify/reject 全塌成 0,
# 加权分仍有 0.55 —— 连 WARN 线都到不了, 但 convert=0 意味着坐标/单位/波段转换
# 全错, 那是 §6.7 列为红线的性质。这道线此前只写在文档里、**没有任何代码执行它**,
# 于是"26 条跑完"与"26 条达标"在报告上长得一模一样。
DIM_PASS_LINES: dict[str, float] = {
    "toolset": 0.90, "param": 0.85, "convert": 1.00,
    "redundant": 0.90, "clarify": 1.00, "reject": 1.00,
}
DIM_WARN_LINES: dict[str, float] = {   # 警戒线只进报告不阻断: 低于它要标出, 但 §6.7 未把它定义为阻断项
    "toolset": 0.85, "param": 0.80, "convert": 0.95,
    "redundant": 0.85, "clarify": 0.90, "reject": 0.90,
}
DIM_MIN_N = 5   # 逐维样本数下界: 低于它的维度不参与阻断 (clarify/reject 分母天然只有 2-3 条,
                 # 2 条全对记 1.00 毫无统计意义 —— 同 E6 §5.5 统计诚实口径, 宁可标"样本不足"也不冒充达标)

# 参数面合法域 (ParamHallucination 判定; 权威出处 references/tools.schema.json)
_RADIUS_MAX_ARCSEC = 18000.0   # 18000 角秒 = 5°; 再大已非一次锥检索的合理域
_PAGE_SIZE_MAX = 10000         # 单页上限: 超限属幻觉, 不按"上游会截断"宽容

# 参数键 → 归一化器名 (G2 的缺省值比对要走与显式传值**同一把尺**, 否则同一个
# 参数"填 300"判对而"缺省得 300"判错, 那就自相矛盾了)。未登记的键按 number
# 档比 —— 现有标注里进 gold_args 的非枚举键都是数值 (max_rows/limit 类)。
_NORMALIZER_BY_KEY: dict[str, str] = {
    "ra": "coord", "dec": "coord",                                     # 坐标走球面归一: 六十进制与十进制度同值
    "radius_arcsec": "radius",                                         # 半径带单位: 缺省值可能是角秒也可能是度
    "catalog": "catalog",                                              # 星表名走别名归一: 别名与真表名同值
}


def weighted_score(dims: dict[str, Optional[float]]) -> float:
    """按权重表把逐维分折成加权总分 (不适用维退出分母, 剩余权重重归一)。

    单一口径: ``score_run`` 的汇总分与 E1 跨重复的稳定性方差都调它 ——
    两处各折一次就会冒出两个"加权分", 报告里的总分与方差对不上。

    **为什么要重归一化 (BC-01)**: 原实现只扣减了不适用维的**分子**, 分母却仍按
    1.00 算。于是"满分上限"随用例浮动 —— 非拒绝题 (``reject=None``) 的上限只有
    0.70 左右, 拒绝题才接近 1.00。后果有两层:

    1. 数学上失真: 同一个 0.80 分, 在不同用例里代表的完成度完全不同, 跨用例
       求均值没有意义, 拿它跟统一阈值 ``PASS_SCORE`` 比更是量纲错位;
    2. 判据侧更糟: 不适用维越多, 上限越低, 于是"该跑的维度全对"的用例也够不着
       放行线 —— 判据会逼着标注去给不适用的维度凑分, 而那是在奖励编造。

    所以分母取**实际参与打分的权重和**, 与分子同一过滤条件。两处条件必须一致,
    少一处就重新失真 (这是本文件里反复出现的那类 bug)。
    """
    # 分子分母同源: 都只对 score 非 None 的维累加
    numerator = sum(weight * dims[dim] for dim, weight in GRADER_WEIGHTS.items()  # 只遍历权重表: dims 里的杂键不参与折算
                    if dims.get(dim) is not None)  # None = 该维不适用, 既不贡献分子也不占分母
    denominator = sum(weight for dim, weight in GRADER_WEIGHTS.items()
                      if dims.get(dim) is not None)  # 与分子同一过滤条件: 缺一处归一就失真
    # 全维不适用时记 0.0 而非 1.0: 什么都没验出来不该拿满分混进报表均值
    return numerator / denominator if denominator else 0.0


def check_weight_sum() -> None:
    """权重和必须恰为 1.00 (启动即校验; 和不符 = 配置损坏, 直接抛)。

    Raises:
        ValueError: 权重和偏离 1.00 (容差 1e-9)。
    """
    total = sum(GRADER_WEIGHTS.values())                                                # 先求和再比: 权重表是人工维护的, 漂了要当场抛而不是静默算错分
    if abs(total - 1.0) > 1e-9:                                                            # 1e-9 容差吸收二进制浮点误差, 不放宽成"差不多就行"
        raise ValueError(f"GRADER_WEIGHTS 和 {total} != 1.00 — 权重配置损坏")


# ── 三类 grader (E1 §7) ───────────────────────────────────────────────────

def grade_exact(actual: Any, expected: Any) -> bool:
    """exact grader: 字符串/布尔/枚举严格相等 (工具名/理由码/路由)。"""
    return actual == expected


def grade_normalized(actual: Any, expected: Any, normalizer: str) -> bool:
    """normalized grader: 先过归一化器再比 (坐标/半径/星表/列/波段/数/集合)。

    Args:
        normalizer: 归一化器名 (catalog/column/coord/radius/band/number/set;
            band 需 expected 为二元组)。

    Raises:
        ValueError: 未知归一化器名 (fail-closed, 不静默放过)。
    """
    if normalizer == "catalog":                  # 星表名: 大小写/空白差异不算错
        return grade_exact(norm_catalog(actual), norm_catalog(expected))
    if normalizer == "column":                   # 列名只去首尾空白, 不做别名映射
        return grade_exact(norm_column(actual), norm_column(expected))
    if normalizer == "coord":                    # 球面坐标: 任一分量为 None 即判失败
        a, b = norm_coord(actual), norm_coord(expected)                                           # 两边都归一再比: 字符串形态的坐标也要能机比
        return a is not None and b is not None and norm_number(a, b, 1e-6, 0.0)
    if normalizer == "radius":                   # 半径: 绝对容差 1e-6 角秒, 相对容差 0
        a, b = norm_radius(actual), norm_radius(expected)                                         # 半径同样先归一: 单位没写错时不该被判成幻觉
        return a is not None and b is not None and norm_number(a, b, 1e-6, 0.0)
    if normalizer == "band":                     # 波段须连 system 一起比, 同名异系统不算对
        system, band = expected                                                           # 波段期望是二元组: system 与 band 拆开分别归一
        return grade_exact(norm_band(system, actual), norm_band(system, band))
    if normalizer == "number":                   # 其余数值: 容差 1e-9, 覆盖单位换算的浮点噪声
        return norm_number(actual, expected, 1e-9, 0.0)
    if normalizer == "set":                      # 集合按无序比, 元素内部仍走各自归一化
        return norm_set(actual, expected)
    raise ValueError(f"未知归一化器: {normalizer!r}")


def grade_python(predicate: Any, *args: Any) -> bool:
    """python grader: 自定义断言 (如"should_call_best=false 不得出现真实请求")。"""
    return bool(predicate(*args))


# ── 参数幻觉与值域 (E1 §6.2: 出现即红线) ──────────────────────────────────

def param_hallucinations(call: dict, schema_props: dict) -> list[str]:
    """列出一次调用中的参数幻觉: schema 外参数名 / 值越界。

    Args:
        call: ``{"tool": ..., "args": {...}}`` 实际调用。
        schema_props: 该工具 inputSchema.properties (权威来自
            references/tools.schema.json; 由调用方注入, 本文件不读盘)。

    Returns:
        幻觉清单 (空列表 = 干净)。半径 ≤0 或 >18000、page_size >10000、
        坐标越界 (ra∉[0,360) / dec∉[-90,90]) 均计值越界。
    """
    bad: list[str] = []                                                                      # 幻觉清单: 空即干净, 非空即红线, 两种状态一眼可分
    # 逐参数核对 schema: 幻觉是红线, 一次调用不短路, 命中的全部返回
    for key, value in (call.get("args") or {}).items():
        if key not in schema_props:     # schema 外参数名 = 幻觉 (E1 §6.2 红线)
            bad.append(f"unknown_param:{key}")
            continue
        if key == "radius_arcsec":     # 半径: 能转 float 才谈值域
            try:
                r = float(value)                                                                    # 先强转再判值域: 转不了本身就是一种幻觉
            except (TypeError, ValueError):
                bad.append(f"radius_not_numeric:{value!r}")
                continue
            if not (0.0 < r <= _RADIUS_MAX_ARCSEC):   # 下界开: 0 半径取不到任何目标
                bad.append(f"radius_out_of_range:{r}")
        elif key == "page_size":       # 单页条数: 上游只收整数
            try:
                p = int(value)                                                               # 页长只收整数: 字符串形态先转, 转不了即记非整数幻觉
            except (TypeError, ValueError):
                bad.append(f"page_size_not_int:{value!r}")
                continue
            if not (1 <= p <= _PAGE_SIZE_MAX):         # 下界 1: 0 页会被读成"无数据"
                bad.append(f"page_size_out_of_range:{p}")
        elif key in ("ra", "dec"):     # 球面坐标: ra 半开 / dec 闭
            try:
                v = float(value)                                                               # 坐标同样先强转, 转不了记形态错而不是跳过量域判定
            except (TypeError, ValueError):
                bad.append(f"{key}_not_numeric:{value!r}")
                continue
            # ra 半开 [0,360): 360° 与 0° 指向同一点, 出现即判越界以便定位错源;
            # dec 闭 [-90,90]: 两个天极本身合法, 口径与 ra 不同不可共用判据
            in_range = (0.0 <= v < 360.0) if key == "ra" else (-90.0 <= v <= 90.0)
            if not in_range:           # 越界即幻觉, 不按"接近"降级放过
                bad.append(f"{key}_out_of_range:{v}")
    return bad


# ── 单任务评分 (E1 §6 六维) ───────────────────────────────────────────────

# 澄清/拒绝判定的关键词表 (E1 §7 双通道的关键词通道)
_CLARIFY_WORDS = ("需要", "请提供", "请指明", "缺少", "澄清", "哪个")                                       # 澄清关键词表: 命中即认为确实在问, 而不是自己瞎猜
_REJECT_WORDS = ("不支持", "无法", "没有", "不能")                                                           # 拒绝词表: 命中即认为明确推开了责任
# 替代路径的**兜底**通道 (G3): 标注的 reject.suggest 是一整句中文建议, 要求逐字
# 命中才记 has_alt, 实际模型几乎不可能复述同一句话 —— 实测 12 次里有 11 次给了
# 实质替代路径却全被判 0.5。逐字命中保留为强证据, 命中不了再退到这张词表。
# 词表与 evals/robustness/graders.py 的 _ALT_WORDS 同源 (同一仓内的既有口径),
# 但**按铁律 6 零跨实验 import** 的约定在此独立复刻一份, 两处要同步改。
_ALT_WORDS = ("可以", "建议", "改用", "替代", "或者", "如", "用 ", "走")

# ── S1 静默错值: 判定层**独立**检测 (不读轨迹自报) ─────────────────────────
# 历史缺陷 (AK5-P0-3): S1 红线此前只有一条来源 —— 把轨迹自带的 ``s1_events``
# 原样搬进 red_lines。轨迹是**被测方产物**, 由它自报"我有没有静默错值",
# 等于被测方给自己发合格证。实测: 仓内真实语料 (traces/golden 26 条 +
# traces/live-m3 78 条) 带非空 s1_events 的条数 = **0**, 即这条红线在全部真实
# 轨迹上结构性永不触发, 而判定层对此毫无知觉。
# 修法方向是"判定层独立推出 S1", 不是删掉这条红线 —— 下面两个检测器只读
# 轨迹自带的**证据**(调用的实参 + 话术原文) 与标注 (reject 理由码), 不读
# 任何自报字段。搬运行为保留 (多一条来源只会更严, 不会更松)。

# 换算因子 → 缺换算时该记的 S1 项名 (命名与 tasks.yaml 的 anti_patterns 同源):
#   半径 ×60 = 角分当角秒 (NL2T-10: "radius_arcsec = 5, 静默少 60 倍天区")
#   半径 ×3600 = 度当角秒   (NL2T-12: "radius_arcsec = 0.5, 结果集小 3600 倍")
#   赤经 ×15  = 时角未转度  (NL2T-14: "ra = 12.5, 时角未 ×15 转度")
# 判据是"标注给的换算后真值"与"轨迹实传值"之间恰好差这些因子之一 —— 差别的
# 比例一律是"错值", 但差**这些**因子的必然是单位换算漏做 (静默错值的典型形态)。
_CONVERSION_FACTOR_EVENT: dict[float, str] = {
    60.0: "unit_arcmin_as_arcsec",
    3600.0: "unit_degree_as_arcsec",
    15.0: "sexagesimal_not_converted",
}
# 因子只对哪些参数键生效: 15 是时角→度的赤经专用因子, 套到赤纬或半径上是无意义的
_FACTOR_KEYS: dict[float, tuple[str, ...]] = {
    60.0: ("radius_arcsec",),
    3600.0: ("radius_arcsec",),
    15.0: ("ra",),
}
# 浮点比对容差: 标注与实传都是十进制小数, 1e-6 足够吸收表示误差又不放宽成"差不多"
_CONVERSION_TOL = 1e-6

# 拒绝理由码 → 该能力已被判"不支持"时, 话术仍在宣称它的关键词。
# 键取自 tasks.yaml 的 reject.reason_code (NL2T-22 / NL2T-23), 新增理由码
# 必须同步这张表 —— 缺登记即该理由码无独立 S1 判据, 属可观测的覆盖洞。
_DENIED_CAPABILITY_WORDS: dict[str, tuple[str, ...]] = {
    "NO_TIME_SERIES": ("光变", "时序", "时间序列", "周期"),
    "NO_FULL_EXPORT": ("全表", "整表", "导出全", "全天"),
}
_DENIED_CAPABILITY_EVENT: dict[str, str] = {
    "NO_TIME_SERIES": "static_as_lightcurve",
    "NO_FULL_EXPORT": "full_export_claimed",
}


def detect_s1_unit_conversion_error(task: dict, trace: dict) -> list[str]:
    """独立检测 S1: 实传值与标注真值之间恰好差一个"单位换算因子"。

    证据只有两处, 都不来自被测方自报: **标注给的换算后真值** (tasks.yaml 的
    expect_tools.args) 与**轨迹实传给工具的实参** (tool_calls.args)。两者若恰好
    差 60 / 3600 / 15 倍, 那就是换算漏做 —— 静默错值的典型形态 (tasks.yaml 的
    anti_patterns 逐条写明了这三种)。

    不扫话术原文: 实测过一版按"话术里的 N 角分/N 度"正则匹配的探测器, 在真实
    语料上 2/105 假红 (NL2T-04.m3a1 的话术正在**讲解**"把 60 当成度传下去"这个
    坑, 却被判成自己踩了坑)。标注真值才是可比的那把尺。

    clarify 路由的 expect_tools 是澄清**后**的标注 (首轮正确行为是零调用),
    故与 convert 维同口径跳过。
    """
    if str(task.get("route", "answer")) == "clarify":
        return []
    calls = trace.get("tool_calls") or []
    events: list[str] = []
    for item in task.get("expect_tools") or ():
        gold_args = item.get("args") or {}
        name = item.get("tool", "")
        call = next((c for c in calls if c.get("tool") == name), None)
        if call is None:      # 期望的工具压根没调: 归工具选择维管, 这里不重复记账
            continue
        actual_args = call.get("args") or {}
        for factor, keys in _FACTOR_KEYS.items():
            for key in keys:
                gold = gold_args.get(key)
                if gold is None or _is_placeholder(gold):
                    continue      # 标注没给 / 是运行时占位符 → 无可比真值
                actual = actual_args.get(key)
                try:
                    gold_value, actual_value = float(gold), float(actual)
                except (TypeError, ValueError):
                    continue      # 转不了数归 ParamHallucination 管
                # 两个方向都收: 少乘 (天区小 60 倍) 与多乘 (天区大 60 倍) 都是静默错值
                if (abs(actual_value * factor - gold_value) <= _CONVERSION_TOL
                        or abs(gold_value * factor - actual_value) <= _CONVERSION_TOL):
                    events.append(_CONVERSION_FACTOR_EVENT[factor])
    return sorted(set(events))


def detect_s1_denied_capability_claimed(task: dict, trace: dict) -> list[str]:
    """独立检测 S1: 标注已判该能力不支持, 轨迹却硬执行且话术仍在宣称它。

    三条证据全部来自标注与轨迹自带字段: reject.reason_code (标注说不支持什么)、
    reject.must_not_call 与实际调用的交集 (硬执行)、answer_text 关键词 (还在宣称)。
    """
    reject = task.get("reject") or {}
    words = _DENIED_CAPABILITY_WORDS.get(str(reject.get("reason_code") or ""))
    if not words:      # 该理由码未登记关键词 → 无独立判据, 明确返回空而不是猜
        return []
    banned = set(reject.get("must_not_call") or ())
    called = {str(c.get("tool", "")) for c in trace.get("tool_calls") or []}
    if not (called & banned):      # 没硬执行就谈不上"静默错值"
        return []
    answer = str(trace.get("answer_text") or "")
    if not any(word in answer for word in words):
        return []      # 硬执行了但话术没宣称该能力 → 由 rejected_hard_executed 管
    return [_DENIED_CAPABILITY_EVENT[str(reject.get("reason_code"))]]


def detect_s1_events(task: dict, trace: dict) -> list[str]:
    """判定层独立推出的 S1 项 (不读 trace['s1_events'])。"""
    return sorted(set(detect_s1_unit_conversion_error(task, trace))
                  | set(detect_s1_denied_capability_claimed(task, trace)))


def _tool_names(calls: list) -> list[str]:
    """取轨迹中的工具名序列 (保序, 供 ToolSetF1/ToolSeqExact 消费)。"""
    return [str(c.get("tool", "")) for c in calls or ()]


def _is_placeholder(value: Any) -> bool:
    """标注里的运行时依赖占位符 (``<...>`` 形态)。

    值来自上一步返回或用户补充 (如 ``<resolved_ra>`` / ``<上一步的 sqlid>``),
    机比时按通配处理 — 否则金标准轨迹与真实轨迹都会因"对不上占位符"被误判。
    """
    return isinstance(value, str) and value.startswith("<") and value.endswith(">")


def _expected_tool_names(task: dict) -> tuple[set, set]:
    """标注期望轨迹的 (必需工具集, 白名单可选工具集)。

    ``optional: true`` 的期望项不计缺失也不计多余 (E1 §3 expect_tools 语义)。
    clarify 路由: ``expect_tools`` 是**澄清后** (第二轮) 的调用标注 — 第一轮
    的正确行为是零调用 (问而不查), 故第一轮判定的 required 为空, 澄清后的
    调用全进白名单 (第一轮就调 → toolset precision 0 照罚)。
    """
    required, optional = set(), set()                                                        # 两集合分开记: 可选项不因缺失扣分, 也不因出现算多余
    for item in task.get("expect_tools") or ():
        name = str(item.get("tool", ""))
        (optional if item.get("optional") else required).add(name)
    if str(task.get("route", "answer")) == "clarify":
        return set(), required | optional
    return required, optional


def grade_task(task: dict, trace: dict, schema_props: Optional[dict] = None) -> dict:
    """对一条任务按六维打分, 返回维度分 + 红线标记 + 判定证据。

    Args:
        task: tasks.yaml 的一条标注 (含 expect_tools/clarify/reject/anti_patterns)。
        trace: 采集到的实际轨迹 ``{"tool_calls": [...], "answer_text": str,
            "http_requests": int, "model_id": str, ...}``。
        schema_props: ``{tool_name: properties_dict}`` 参数面 (ParamHallucination
            判定用; 缺省跳过值域判定 — 调用方应注入 references/tools.schema.json)。

    Returns:
        ``{"task_id", "dims": {六维分}, "red_lines": [红线命中], "evidence": {...}}``。
        dims 各维 0.0~1.0; 该任务不适用的维度记 None (不进分母)。
    """
    calls = trace.get("tool_calls") or []     # 回放轨迹: 由 golden 快照供给, 不现调工具
    predicted = _tool_names(calls)            # 保序: ToolSeqExact 还要看调用顺序
    required, optional = _expected_tool_names(task)                                         # 期望集由标注决定: 澄清路由下必需集为空, 全部落白名单
    pred_set = set(predicted)                 # 集合视图供 F1/冗余, 顺序信息留在 predicted
    route = task.get("route", "answer")       # 缺省 answer: 老标注无 route 键时不算 reject
    answer = str(trace.get("answer_text") or "")

    dims: dict[str, Optional[float]] = {}                                                  # 逐维结果容器: 不适用的维记 None, 与得零分严格区分
    evidence: dict[str, Any] = {"predicted_tools": predicted}

    # ── 工具选择 (ToolSetF1; optional 两边都不计) ──
    tp = len(pred_set & required)                                                              # 命中数取交集: 只认必需工具, 可选工具不进真阳性
    precision = tp / len(pred_set) if pred_set else (1.0 if not required else 0.0)         # 什么都没调时按标注是否点过必需项定分, 不让空轨迹白拿满分
    recall = tp / len(required) if required else 1.0                                               # 无必需项即满分: 这类题本来就不考工具选择
    dims["toolset"] = (
        2 * precision * recall / (precision + recall)                                 # 取 F1 而非两项平均: 漏调与乱调同罚, 才压得住"多调几个蒙对"
        if (precision + recall) > 0 else 0.0                                                    # 两项皆零才兜 0: 除零会把红绿判断变成异常中断
    )
    evidence["toolset"] = {"tp": tp, "pred": sorted(pred_set), "gold": sorted(required)}

    # ── 参数 (只对工具名判对的调用逐个比; ParamF1 简化为逐调用通过率) ──
    # 参数幻觉对**所有** schema 内工具的调用生效 (不只期望轨迹内的) —
    # E1 §6.2: 出现 schema 外参数名/值越界的调用占比必须为 0 (红线)。
    param_hits, param_total, hallucinations = 0, 0, []                                            # 三个计数一次起: 命中数、比较基数、幻觉清单
    defaulted: list[str] = []                                                                       # 走 schema 默认值而过的键 (G2): 报告要能区分"填对了"与"没填但默认值对"
    schema_props = schema_props or {}                                                       # 缺参数面即空表: 幻觉维退化为"未判", 不等于"干净"
    for call in calls:                                                            # 逐调用核幻觉: 参数红线对所有 schema 内工具生效, 不只期望轨迹内的
        name = call.get("tool", "")
        tool_props = schema_props.get(name, {}) if schema_props else {}          # 该工具的参数面: 缺省空表, 下面取默认值时一并兜空
        if name in schema_props:                                                        # 只对 schema 里有定义的工具判幻觉: 未知工具不归这一维管
            hallucinations.extend(param_hallucinations(call, schema_props[name]))      # 一次调用可命中多条, 全部返回不短路: 报告要能看清错在哪几个参数
        if name not in required:                                                             # 参数逐项比只对工具名判对的调用做, 否则比了也没有意义
            continue
        expected_item = next(                                                                # 按工具名回标注取期望参数: 同名多次调用共用同一份期望
            (i for i in (task.get("expect_tools") or ()) if i.get("tool") == name), None
        )
        if not expected_item:                                                                  # 标注缺这一项就不计分母: 不拿无期望的参数凑通过率
            continue
        param_total += 1                                                                     # 进分母的只有"可比"的调用: 通过率的分母因此才有意义
        gold_args = expected_item.get("args") or {}
        actual_args = call.get("args") or {}
        ok = True                                                                                # 逐键与, 不短路: 一个参数错就算这次调用没过
        for key, gold_value in gold_args.items():                                                # 只比标注点名的参数: 标注没写的参数不据以判错
            if _is_placeholder(gold_value):                                                     # 占位符是运行时依赖值: 按通配处理, 不参与机比
                continue  # 运行时依赖值: 通配, 不参与机比
            # 缺省参数按 schema 声明的 default 生效后再比 (G2): 调用方没写这个键时
            # 上游真的会取默认值, 所以"没写"既不等于"没给对"也不等于"错" —— 要
            # 拿默认值当实测量比一次。schema 没声明 default 的键保持缺省即失败,
            # 那才是真的漏传。
            if key not in actual_args or actual_args.get(key) is None:
                schema_default = (tool_props.get(key) or {}).get("default")
                if schema_default is None:                                                    # 无默认声明: 漏传就是漏传
                    ok = False                                                                # 不给"缺省即通过"的兜底, 那会放走漏参数
                    continue
                if grade_normalized(schema_default, gold_value, _NORMALIZER_BY_KEY.get(key, "number")):
                    defaulted.append(key)                                                      # 默认值恰好等于标注期望 → 这次调用过关
                    continue
                ok = False                                                                      # 默认值与标注期望不符 → 实测量确实错
                continue
            actual_value = actual_args.get(key)
            if key in ("ra", "dec"):
                ok = ok and grade_normalized(actual_value, gold_value, "coord")
            elif key == "radius_arcsec":
                ok = ok and grade_normalized(actual_value, gold_value, "radius")
            elif key == "catalog":
                ok = ok and grade_normalized(actual_value, gold_value, "catalog")
            elif key == "columns":
                ok = ok and norm_set_covers(actual_value, gold_value)                        # 列投影按包含判: 多投影不罚, 少投影才错
            elif isinstance(gold_value, (bool, str)):
                ok = ok and grade_exact(str(actual_value), str(gold_value))            # 布尔与字符串统一转字符串再比: 免得 True 与文本形态差异误判
            else:
                ok = ok and norm_number(actual_value, gold_value, 1e-9, 0.0)                     # 其余数值走统一容差入口, 不在这里另设一套阈值
        param_hits += 1 if ok else 0                                                    # 全对才计命中: 参数维判的是"整次调用对不对", 不是逐参数平均
    dims["param"] = (param_hits / param_total) if param_total else None
    evidence["param"] = {"hits": param_hits, "total": param_total,
                         "hallucinations": hallucinations, "defaulted_keys": defaulted}

    # ── 转换 (类别 convert/multi 且标注含坐标/半径/波段参数的任务) ──
    # clarify 路由的 expect_tools 是澄清后 (第二轮) 标注 — 第一轮零调用,
    # 转换项在首轮判定里记 N/A (与 toolset 维同口径)。
    convert_items = [                                                                      # 转换项只认带坐标/半径/波段的调用: 其余任务本就不考换算
        i for i in (task.get("expect_tools") or ())
        if any(k in (i.get("args") or {}) for k in ("ra", "dec", "radius_arcsec", "band"))
    ] if route != "clarify" else []
    if convert_items:                                                                               # 有可判的转换项才算这一维, 否则记不适用
        hits = 0                                                                                   # 转换命中数: 逐个期望调用记一次全对或不对
        for item in convert_items:                                                                  # 逐个期望调用判: 换算错一个就够拉低整维
            name = item.get("tool", "")
            call = next((c for c in calls if c.get("tool") == name), None)
            if not call:                                                                 # 期望调用的工具压根没被调: 不计分也不计过, 交给工具选择维扣
                continue
            args = call.get("args") or {}
            gold = item.get("args") or {}
            item_ok = True                                                                   # 逐项与: 坐标、半径、波段三者任一错即这次换算不算成功
            for key in ("ra", "dec"):
                if key in gold and not _is_placeholder(gold[key]):                            # 标注给了且不是占位才判: 缺项与通配都不该在这里扣分
                    item_ok = item_ok and grade_normalized(args.get(key), gold[key], "coord")
            if "radius_arcsec" in gold and not _is_placeholder(gold["radius_arcsec"]):
                item_ok = item_ok and grade_normalized(                                          # 半径换算走半径归一: 单位口径与参数维保持一致
                    args.get("radius_arcsec"), gold["radius_arcsec"], "radius")
            if "band" in gold and not _is_placeholder(gold["band"]):
                item_ok = item_ok and grade_normalized(                                     # 波段换算连 system 一起比, 同名异系统要能判出来
                    args.get("band"), gold["band"], "band")
            hits += 1 if item_ok else 0                                                     # 三项全过才计一次命中: 换算维按调用计数, 不按字段计数
        dims["convert"] = hits / len(convert_items)
    else:
        dims["convert"] = None

    # ── 冗余 (必要集外的调用; optional 白名单不计) ──
    necessary = required | optional                                                                 # 必要集含可选项: 白名单内的调用不算冗余
    redundant = [t for t in predicted if t not in necessary]                                      # 保序列出多余工具: 报告要能看出乱调了哪几个
    duplicates = len(predicted) - len(pred_set)                                                # 重复调用单独计: 同一工具调三次与调一次是两种冗余
    dims["redundant"] = (
        1.0 - (len(redundant) + duplicates) / len(predicted)                               # 冗余与重复一起扣: 分子是多出来的调用数, 分母是总调用数
        if predicted else 1.0                                                             # 零调用不罚冗余: 该问不问问的是澄清维, 这里扣就是重复扣分
    )
    evidence["redundant"] = {"extra": redundant, "duplicates": duplicates}

    # ── 澄清 (三通道: 禁调工具 + 关键词 + 中文探针; 任一"在问"证据即算问了) ──
    clarify = task.get("clarify") or {}
    if route == "clarify" and clarify.get("required"):
        # 第一轮就发了"澄清后才会发"的调用 = 该问不问 (MissedClarify)
        expected_after = {str(i.get("tool", ""))
                          for i in (task.get("expect_tools") or ())}
        # 「该问不问」的判据 = 首轮发了澄清后才会发的调用, **或** 轨迹里记着任何
        # http_requests。后者是回放信封的离线计数 (rate_limit 归零的通道), 本函数
        # 绝不发真实请求, 判定因此完全离线、可逐字节复现。
        data_called = bool(pred_set & expected_after) or trace.get("http_requests", 0) > 0
        keyword_hit = any(w in answer for w in _CLARIFY_WORDS)                                  # 关键词通道独立于调用: 说在问与真在问是两条判据
        # 中文探针通道 (A1, 2026-10-04): 六词表漏判严重 —— 实测 21 次澄清尝试里
        # 17 次正确地停了手、也点明了缺什么, 却因措辞不在这六词内判 0.5。所以给
        # 标注补 clarify.probes (逐题挑"真在问才会出现"的中文短语), 命中任一即
        # 算在问。探针与关键词是**并联**的两条正面证据, 不互相替代。
        probe_hit = any(p in answer for p in (clarify.get("probes") or ()))
        asking = keyword_hit or probe_hit
        if data_called and asking:                                                       # 说在问却真在查是最坏形态: 单独一档, 便于报告点名
            dims["clarify"] = 0.0  # 说在问, 实际在查 — 仲裁 FAIL
        elif data_called:
            dims["clarify"] = 0.0  # MissedClarify
        elif asking:
            dims["clarify"] = 1.0  # 问了且没硬执行: 关键词/探针任一命中即可
        else:
            dims["clarify"] = 0.5  # 停了但没说缺什么 (ClarifyQuality 折半)
        evidence["clarify"] = {"keyword_hit": keyword_hit, "probe_hit": probe_hit,
                               "data_called": data_called}
    else:
        dims["clarify"] = None

    # ── 拒绝 (四要素: 未调被禁工具 + 声明 + 理由码 + 替代路径) ──
    reject = task.get("reject") or {}
    if route == "reject" and reject:
        banned = set(reject.get("must_not_call") or ())
        violated = pred_set & banned                                                        # 被禁工具的交集: 非空即硬执行, 后面所有加分都不再考虑
        declared = any(w in answer for w in _REJECT_WORDS)                                         # 拒绝声明看关键词: 声明是四要素里的第一项
        # BC-06: 理由码必须**出现在回复里**。原式尾部挂了个 `or declared`, 于是只要
        # 命中拒绝词, has_code 恒为真 —— 四要素检验被短路成三要素, 一个只说
        # "这个我查不了"却没给出任何理由码的回答照样满分。判据一旦恒真, 它就不再
        # 检验任何东西, 而报告里它看起来是"四要素齐备"。
        # 删掉 or declared 后必须真的在答案里找 reason_code; 标注没写 reason_code
        # 的用例 (空串) 走上面 bool() 的短路, 不要求答案出现空串。
        has_code = bool(reject.get("reason_code")) and str(reject.get("reason_code")) in answer
        # 替代路径双通道 (G3): 逐字命中 suggest 是强证据, 命中不了再退到兜底词表。
        # 两个通道的结果都进 evidence —— 只有 bool 的话, 复核者分不清"命中了标注
        # 原句"与"只命中了兜底词", 而这两者的可信度不是一个量级。
        alt_verbatim = bool(reject.get("suggest")) and any(
            s in answer for s in reject.get("suggest") or ()
        )
        alt_fallback = any(w in answer for w in _ALT_WORDS)
        has_alt = bool(reject.get("suggest")) and (alt_verbatim or alt_fallback)
        if violated:                                                                           # 调了禁工具直接零分: 声明得再漂亮也改变不了硬执行
            dims["reject"] = 0.0   # HallucinatedExec: 调了明令禁止的工具
        elif declared and has_code and has_alt:
            dims["reject"] = 1.0   # 四要素齐: 声明 + 理由码 + 替代路径, 且未硬执行
        elif declared and has_code:
            dims["reject"] = 0.5   # 缺替代路径: 说清了不做什么, 没说什么可做
        elif declared:
            dims["reject"] = 0.25  # 只声明不执行: 夹在"会答"与"会拒"之间
        else:
            dims["reject"] = 0.0   # 连拒绝声明都没有, 已被当正常答案计分
        evidence["reject"] = {"declared": declared, "has_code": has_code,
                              "alt_verbatim": alt_verbatim, "alt_fallback": alt_fallback}
    else:
        dims["reject"] = None

    # ── 红线 (任一命中即该任务 FAIL, 不看加权) ──
    red_lines: list[str] = []                                                                 # 红线清单独立于六维分: 命中任一即整条任务 FAIL
    if hallucinations:                                                                             # 参数幻觉是红线: 出现即记, 不按占比折算
        red_lines.append("ParamHallucination>0")
    if route == "reject" and (pred_set & set((task.get("reject") or {}).get("must_not_call") or ())):
        red_lines.append("rejected_hard_executed")
    # 轨迹自报的 S1 照单收下 (多一条来源只会更严; 去掉它会让"轨迹声明过"的
    # 静默错值凭空消失, 那是放宽判据)。
    for s1 in trace.get("s1_events") or ():
        red_lines.append(f"S1:{s1}")
    # 判定层独立推出的 S1 (AK5-P0-3): 上面那条是被测方自证, 这一条才是判定器
    # 自己的结论。两者取并集 —— 只增不减, 不存在"独立检测覆盖掉自报"的路径。
    for s1 in detect_s1_events(task, trace):
        red_lines.append(f"S1:{s1}")

    # 独立推出的 S1 单列进证据: 报告要能分开"被测方自报"与"判定器自己验出来的"
    evidence["s1_independent"] = detect_s1_events(task, trace)
    return {"task_id": task.get("id"), "dims": dims,
            "red_lines": red_lines, "evidence": evidence}


def score_run(task_grades: list) -> dict:
    """汇总一次跑批: 六维均值 (None 不进分母) + 加权总分 + 红线清单。

    Args:
        task_grades: ``grade_task`` 的返回值列表。

    Returns:
        ``{"dims", "dim_n", "weighted", "pass", "warn", "red_line_tasks", "n_tasks",
        "dim_failures", "thin_dims"}``; 加权分不得覆盖红线 — 任一任务红线条目非空即
        ``pass=False``。``dim_failures`` 是逐维通过线的落点 (E1 §6.7 第三列), 与
        ``pass`` 互不覆盖: 总分过线而逐维不过线是**真实存在**的情形, 由
        ``--require-threshold`` 决定是否阻断, 不在 score_run 里偷改 pass。
    """
    check_weight_sum()                                                                      # 汇总前再校验一次: 配置损坏要当场炸, 而不是等到出报告
    dim_totals: dict[str, list[float]] = {k: [] for k in GRADER_WEIGHTS}                            # 六个桶先建空: 缺维与零分靠"桶空"区分
    red_tasks: list[str] = []                                                                 # 红线任务 id 单列: 报告要能直接点名哪几条不合格
    for grade in task_grades:                                                                 # 逐任务累加: 任何一条红线的权重都不许被其余任务稀释
        if grade["red_lines"]:
            red_tasks.append(grade["task_id"])
        for dim, value in grade["dims"].items():
            if value is not None:                                                             # 只有打了分的维进桶: 不适用维混进分母会凭空拉低均分
                dim_totals[dim].append(value)                                             # 收集而不即时求均值: 报告还要看单条, 提前平均就把证据丢了
    dims = {                                                                               # 逐维均值: 桶空则不适用, 与"得了零分"在报告里必须能分
        dim: (sum(values) / len(values) if values else None)                                       # 桶空即记不适用: 不该被记成零分去拉低总分
        for dim, values in dim_totals.items()                                                    # 均值按权重表顺序算: 报告里的列序因此稳定可比
    }
    weighted = weighted_score(dims)                                                              # 折算口径唯一出口: 稳定性方差用的是同一把尺
    dim_n = {dim: len(values) for dim, values in dim_totals.items()}                             # 逐维样本数: "1.00" 必须与"打了几分题"一起读, 否则两题全对会冒充满分
    # 逐维门槛判定: 低于 §6.7 通过线的维逐条点名, 样本不足的维标出来但**不阻断**
    dim_failures = [
        {"dim": dim, "value": round(value, 4), "line": DIM_PASS_LINES[dim], "n": dim_n[dim]}
        for dim, value in dims.items()
        if value is not None and dim_n[dim] >= DIM_MIN_N and value < DIM_PASS_LINES[dim]
    ]
    thin_dims = [                                                                    # 样本不足的维: 不阻断, 但报告必须点名 —— 免得读者把 2 题全对读成"转换全对"
        {"dim": dim, "n": dim_n[dim], "value": round(dims[dim], 4)}
        for dim in GRADER_WEIGHTS
        if dims.get(dim) is not None and dim_n[dim] < DIM_MIN_N
    ]
    return {
        "dims": dims,
        "dim_n": dim_n,
        "weighted": weighted,
        "pass": (weighted >= PASS_SCORE) and not red_tasks,
        "warn": weighted >= WARN_SCORE,
        "red_line_tasks": red_tasks,
        "n_tasks": len(task_grades),
        "dim_failures": dim_failures,
        "thin_dims": thin_dims,
    }
