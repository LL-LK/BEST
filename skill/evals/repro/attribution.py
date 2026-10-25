# -*- coding: utf-8 -*-
"""evals.repro.attribution — E6 分层归因决策表 (§4.3, 顺序不可调整)。

能力边界: 把"两次不一样"归到唯一责任方 — 按文档 §4.3 的七行表**自上而下
第一条命中即用** (第 4/5 条必须以"工具与参数均与众数一致"为前提, 否则会
把模型侧不稳误判成后端问题 — 这是全表最容易犯的错)。
边界: 只归因不判对错 (对错移交 E1/E2/E3); 漂移定量移交 E7 (本表只标
ERR_BACKEND_DRIFT, 不量化)。

白盒锚点: docs/eval-E6-reproducibility.md §4.3 (七行决策表与顺序铁律);
references/tools.schema.json (7 个原子工具名的权威面)。
"""
from __future__ import annotations

from evals.repro.normalize import norm_args  # 归一前站: 判"参数合法/一致"都先过它

SCHEMA_TOOLS = frozenset({  # 权威面 references/tools.schema.json; 不在内即 ERR_ROUTE
    "resolve_name", "list_catalogs", "describe_catalog", "cone_search",
    "crossmatch_batch", "count", "fetch_page",
})
BACKEND_ERROR_CODES = frozenset({  # 第 4 条的判定集合: 只有这四个码算后端问题
    "E_SOFT_404", "E_NO_SQLID", "E_BACKEND", "E_NAME_UNRESOLVED",
})
ATTRIBUTION_CODES = (  # 枚举与 trace.schema.json 的 attribution_codes 同一面
    "ERR_ROUTE", "ERR_PARAM_SCHEMA", "ERR_PARAM_UNSTABLE", "ERR_BACKEND",
    "ERR_BACKEND_DRIFT", "ERR_RETRY_INEFFECTIVE", "ERR_CONCLUSION_UNSTABLE",
)


def _args_legal(call: dict) -> bool:
    """参数硬合法性 (与稳定性无关的错: 半径/坐标/page 越界, 类型错)。"""
    args = call.get("args") or {}
    radius = args.get("radius_arcsec")                                                # 最常越界的字段, 单独先判
    if radius is not None:                                                                    # 半径是最常越界的字段, 单独先判, 不混进经纬度循环
        try:
            value = float(radius)                                                    # 强转失败即非法
        except (TypeError, ValueError):
            return False
        if not (0.0 < value <= 18000.0):                                             # 上界闭下界开: 0 半径无意义
            return False
    for key, low, high in (("ra", 0.0, 360.0), ("dec", -90.0, 90.0)):                # 经度 [0,360) / 纬度 [-90,90]
        if key in args and args[key] is not None:                                    # 显式 None 视为未给
            try:
                value = float(args[key])                                                         # 强转失败即判非法: 不替调用方猜它到底想传什么
            except (TypeError, ValueError):
                return False
            if not (low <= value < high if key == "ra" else low <= value <= high):   # ra 半开而 dec 全闭
                return False
    return True


def attribute_run(run: dict, mode_calls: list[dict], mode_card: dict | None,
                  baseline_data_hash: str | None = None) -> str:
    """对一次运行按七行表归因 (第一条命中即用)。

    Args:
        run: 一次运行的记录 ``{"tool_calls": [{tool, args}],
            "results": [{ok, error_code, data_hash}], "card": 结论卡,
            "retries": [{strategy_changed}]}``。
        mode_calls: 同任务其他 run 的众数调用 (归一后)。
        mode_card: 同任务其他 run 的众数结论卡 (归一后)。
        baseline_data_hash: 基线 data_hash (在线路无基线传 None)。

    Returns:
        ATTRIBUTION_CODES 之一; 全部不命中返回 "OK" (稳定且无异常)。
    """
    calls = run.get("tool_calls") or []  # 缺记录即空: 只遍历拿得到的那部分
    results = run.get("results") or []
    # 1. 路由错误 (工具名不在 7 原子工具内)
    for call in calls:                                                                       # 路由判最优先: 工具名错了, 后面的参数比对都失去意义
        if call.get("tool") not in SCHEMA_TOOLS:
            return "ERR_ROUTE"
    # 2. 参数硬错 (任何一次运行都会错 — 与稳定性无关)
    for call in calls:                                                                       # 参数硬错与稳定性无关: 每次都错, 值得单独一个归因码
        if not _args_legal(call):                                                           # 任一次调用硬错就整条判 schema 错, 不做多数投票
            return "ERR_PARAM_SCHEMA"
    # 3. 参数与众数不一致 (E6 主抓的模型侧不稳定)
    norm_calls = [norm_args(c.get("args") or {}) for c in calls]  # 先归一再比: 未归一会把口径差算成不稳
    if len(norm_calls) != len(mode_calls):                         # 调用数不等即判不稳: 对不齐就没资格逐位比
        return "ERR_PARAM_UNSTABLE"
    for actual, ref in zip(norm_calls, mode_calls):                # 逐位对齐: 第 i 次调用对第 i 次, 不做集合匹配
        if set(actual) != set(ref):                                # 键集不等 = 多传或漏传: 列名全限定是硬要求
            return "ERR_PARAM_UNSTABLE"
        for key in ref:                                                                           # 按参照的键逐个比: 参照没给的键不算本次漏传
            if key not in actual:                                                             # 键集上面已比过, 这道是防御: 参照键必须都取得到值
                return "ERR_PARAM_UNSTABLE"
            a, b = actual[key], ref[key]                           # 本次在前、参照在后: 容差以参照为基准
            if isinstance(a, float) and isinstance(b, float):      # 两侧都须是 float: 归一后整数坐标已转型
                if abs(a - b) > 1e-6 + 1e-9 * abs(b):              # 与 PAC 同一容差: 两处口径不同会让归因与指标打架
                    return "ERR_PARAM_UNSTABLE"
            elif isinstance(a, list) and isinstance(b, list):
                # list 值按集合/排序键比 (E6 §5.2: columns 顺序不敏感 —
                # mode_calls 若未排序, 仅顺序不同不是参数不稳定)
                if sorted(str(v) for v in a) != sorted(str(v) for v in b):     # 先转字符串再排序: columns 里混着列名与数字, 直排会 TypeError
                    return "ERR_PARAM_UNSTABLE"
            elif a != b:                                           # 其余精确比: 放宽容差就放弃了一半抓取力
                return "ERR_PARAM_UNSTABLE"
    # 4. 后端错误 (前提: 工具与参数均与众数一致 — 顺序铁律)
    for result in results:                                                                   # 后端判据排在参数之后: 顺序铁律不因看起来更严重而提前
        if result.get("ok") is False and result.get("error_code") in BACKEND_ERROR_CODES:  # 双重条件: ok 但内容变了归第 5 条
            return "ERR_BACKEND"
    # 5. 数据内容漂移 (工具参数一致且 ok, 但 data_hash 与基线不符)
    if baseline_data_hash:  # 在线路无基线时整条跳过: 不能拿"无基线"当漂移
        for result in results:                                                           # 漂移只看成功结果: 失败结果的 data_hash 本身不可比
            if result.get("ok") is True and result.get("data_hash") not in (None, baseline_data_hash):  # 放过缺失: 无内容可比≠漂移
                return "ERR_BACKEND_DRIFT"
    # 6. 无效重试 (原样重发)
    for retry in run.get("retries") or ():
        if retry.get("strategy_changed") is False:  # 只认显式 False: 缺字段不等于原样重发
            return "ERR_RETRY_INEFFECTIVE"
    # 7. 结论卡漂移 (工具层一致但结论不稳)
    if mode_card is not None:  # 无参照卡就整条跳过: 没有比对面不下结论
        # 本地: 结论卡归一 (归因第 7 条判据的比对面)
        from evals.repro.normalize import cards_equal, norm_card

        if not cards_equal(norm_card(run.get("card") or {}), mode_card):
            return "ERR_CONCLUSION_UNSTABLE"
    return "OK"


def attribute_lane(runs: list[dict], mode_calls: list[dict],
                   mode_card: dict | None, baseline_data_hash: str | None = None) -> dict:
    """一批运行的归因分布 (报告 §12 第 7 个数: 各归因码多少条)。"""
    distribution = {code: 0 for code in ATTRIBUTION_CODES}                                     # 七码全部预置 0: 没出现过的码也要在报告里看得见
    distribution["OK"] = 0
    for run in runs:                                                                    # 逐 run 独立归因: 互不影响, 便于回单条 trace 复算
        code = attribute_run(run, mode_calls, mode_card, baseline_data_hash)                      # 同任务共用一份众数参照: 参照在批外只算一次
        distribution[code] = distribution.get(code, 0) + 1                                   # get 默认值兜底: 外部塞进来的未知码也能记账而不崩
    return distribution
