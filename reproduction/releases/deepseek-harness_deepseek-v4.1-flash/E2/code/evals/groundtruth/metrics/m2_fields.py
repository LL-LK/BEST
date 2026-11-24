# -*- coding: utf-8 -*-
"""evals.groundtruth.metrics.m2_fields — M2 字段值完全一致率 (权重 0.25)。

口径 (E2 §6 M2): 只对 TP 行逐字段比 — **先判语义类别再比值**
(null/zero/value 三者类别不符直接记不一致, 不做数值比较); 数值字段按
``|a-b| <= atol + rtol*|b|`` (容差来自 GT field_values, 不外置硬编码);
字符串/ID 精确相等 (canonical 已 strip/去零填充/大小写归一)。
报告按字段聚合 (哪个字段错得最多 — 一眼看出列错位还是单位错)。
"""
from __future__ import annotations

# 本地: 主键与哨兵判定 (canonical 单点)
from evals.groundtruth.canonical import (  # 同实验内 import; 归一规则归 E2 私有, 不外借
    batch_line_offset,
    id_keys_unique,
    is_sentinel,
    row_key,
)


def _semantic_class(column: str, value) -> str:
    """单格语义类别: null (空/哨兵) / zero (真零) / value (有值)。"""
    if value is None or value == "":
        return "null"  # None 与空串同归缺失: 客户端两种空态都真实出现过
    if is_sentinel(column, value):                                         # 哨兵与空值同归 null: 判的是语义态, -999 是「没测到」而非「测到了 -999」
        return "null"  # 哨兵即缺失: -999 是"没测到", 不是"测到了 -999"
    try:
        return "zero" if float(value) == 0.0 else "value"  # 真零单列一类: 0 与缺失的科学含义不同
    except (TypeError, ValueError):
        return "value"  # 转不成数 = ID/字符串列, 走精确相等


def score_m2(gold: dict, actual: dict) -> dict:
    """M2: 字段一致率 = 1 - 不一致字段数/应比对字段数 (TP 行 × GT 字段)。

    比对范围 = field_values (有值字段) **∪ null_semantics** (语义字段) —
    后者是"这一格必须是缺失"的硬声明 (哨兵/空), 漏了它, "把 -999 换 0"
    这类最危险的污染就无人判定 (E2 §6 M2 类别不符直接记不一致)。
    """
    gold_values = gold.get("field_values") or {}        # 有值字段: 期望值 + 容差都在 spec 里
    gold_semantics = gold.get("null_semantics") or {}    # 纯语义字段: 只声明"这格必须缺失"
    # 主键索引: 逐格比对的定位单位。batch 必须与 M1 同源传入, 否则索引键与
    # gold 的 row_keys 前缀不一致, 每格都定位不到 → compared=0 → 判据空转。
    # coords_only 走 canonical.id_keys_unique —— 与 M1 的 key_set、oracle 的
    # id_keys_unique 同一判据; 三处若有一处不同, 键就会一边用 id 一边用坐标,
    # 索引全落空。
    rows = actual.get("rows") or ()
    batch = actual.get("batch_keys")                 # run_e2 按查询给的批量标记 (proximity 才带 in<N>:)
    coords_only = not id_keys_unique(rows)           # 结果集内 id 有重复即整批走坐标键
    line_offset = batch_line_offset(rows)            # 服务端 input_line 基准 → 场景 0-based 序号
    actual_by_key = {row_key(r, batch=batch, coords_only=coords_only, line_offset=line_offset): r
                     for r in rows}  # 定位不到的行归 M1, 不双扣
    compared, mismatches, per_field = 0, 0, {}          # 分母/分子/按列归因三件套

    def _compare_cell(key, column, spec, gold_semantic):
        """比一格: 先类别后数值; 返回 (是否一致, 明细或 None)。"""
        nonlocal compared                                                  # 回写外层计数: 嵌套函数 return 不了累计值, 只能靠 nonlocal 带回主函数 (mismatches 在主循环累加, 此处不碰)
        row = actual_by_key.get(key)                                                 # 按主键定位行: 定位不到说明这行 M1 已经判过, 不该在这里再扣一次
        if row is None:                                                          # 行缺失不在此扣分: 双扣会让同一处错在 M1 与 M2 各记一次, 失真被放大
            return None  # 行缺失归 M1, 不双扣
        actual_value = row.get(column)                                          # 列名取 gold 的逻辑名: actual 行已按同一份列名归一过, 键才对得上
        actual_class = _semantic_class(column, actual_value)                        # 先定类别再比值: null/zero/value 混了之后比数值毫无意义
        compared += 1  # 只在行存在时计数: 分母才对得上 gold 断言的行集
        if gold_semantic != actual_class:                                            # 类别不符直接判错: 「把 -999 换成 0」这类污染正是本指标要抓的
            # 类别不符直接判不一致: 缺失/零/有值混了, 再比数值毫无意义
            return {"key": key, "gold": spec.get("v") if spec else gold_semantic,
                    "actual": actual_value, "gold_class": gold_semantic,
                    "actual_class": actual_class}  # 双侧类别都带上: 报告要能区分"错在类别"与"错在数值"
        if gold_semantic == "null":
            return None  # 双方皆缺失 — 类别一致即通过
        if spec is None:                                                                         # 纯语义格没有期望值: 只判类别, 不进数值分支
            return None  # 无语义值时仅有类别声明
        if spec.get("kind") == "string" or isinstance(spec.get("v"), str):
            ok = str(actual_value).strip() == str(spec.get("v")).strip()  # 字符串/ID 精确比, 只容忍首尾空白
        else:
            atol = float(spec.get("atol", 0.0))  # 容差由 GT 携带: 换列不必改判据
            rtol = float(spec.get("rtol", 0.0))
            try:
                ok = abs(float(actual_value) - float(spec["v"])) <= atol + rtol * abs(float(spec["v"]))  # 绝对+相对双容差
            except (TypeError, ValueError):
                ok = False  # 期望是数、实际转不成 = 不一致, 绝不当作"跳过"
        if ok:                                                                          # 一致即返 None: 明细只留失配, 报告里没有明细就意味着通过
            return None
        return {"key": key, "gold": spec.get("v"), "actual": actual_value,
                "gold_class": gold_semantic, "actual_class": actual_class}  # 超容差: 记明细

    for key, fields in gold_values.items():                                        # 第一趟只比有值字段: 期望值与容差都挂在 spec 上, 语义表要另走一趟
        for column, spec in fields.items():                                               # 逐字段下钻: 分母单位是「格」, 按行加权会让大字段数行虚高
            semantic = (gold_semantics.get(key) or {}).get(column) or \
                spec.get("semantic") or _semantic_class(column, spec.get("v"))  # 优先级 显式语义 > 内嵌 > 按期望值推
            detail = _compare_cell(key, column, spec, semantic)                        # 比对集中在这一个函数: 两趟循环的口径必须同源, 复制两遍必然漂移
            if detail:                                                                 # 非 None 即失配: 返回值本身就是判据, 不再二次判断是否相等
                mismatches += 1                                                            # 分子按格计: 分子分母同为格数, 1-x/y 才是真一致率
                per_field.setdefault(column, []).append(detail)  # 按列归因: 一眼看出是列错位还是单位错
    for key, columns in gold_semantics.items():                                        # 第二趟补纯语义格: 只声明「这格必须缺失」的字段在第一趟根本不在场
        for column, semantic in columns.items():                                              # 逐列下钻, 口径与第一趟完全相同: 两趟不可各写一套
            if column in (gold_values.get(key) or {}):                                        # 第一趟比过就跳过: 同一格比两次会让失配分子虚高一倍
                continue  # 已由 field_values 覆盖 (语义优先取值里的)
            detail = _compare_cell(key, column, None, semantic)  # 纯语义格: 没有值可比, 只判类别
            if detail:                                                               # 同样以 None 为通过标记: 两趟共用一套返回约定, 消费侧不用分叉
                mismatches += 1                                                        # 同口径累加: 两趟的分子可以直接相加, 分母共用 compared
                per_field.setdefault(column, []).append(detail)                       # 按列归因: 报告要能一眼看出是列错位还是单位错, 而不是只给一个总数

    consistency = 1.0 - mismatches / compared if compared else 1.0                   # 零分母给 1.0: 无可比格属无从判定, 但下一行的空转检查会兜住虚高
    # gold 本身期望 0 行 (空结果/错误态) 时无比对对象 — 记 N/A 而非失败
    # (双空由 M1 的 degenerate 标记 + M5 的 result_state 接管)。
    gold_expects_rows = bool(gold.get("row_keys"))  # gold 期望零行 = 空结果/错误态
    live = str(actual.get("mode") or "replay") == "live"  # 两种接线两种可比性: 只有 live 会因活数据变化而丢交集
    if not gold_expects_rows and compared == 0:                              # 双空才判 N/A: 有行却一格没比是判据空转, 由 passed 那条判失败而不是放过
        return {"score": None, "pass": True, "compared_fields": 0,   # N/A 而非失败: 状态判归 M5
                "mismatched_fields": 0, "per_field_errors": {},
                "blockers": [], "note": "gold 期望 0 行 — M2 不适用 (M5 接管)"}
    if live and gold_expects_rows and compared == 0:
        # live 下实测行与 gold 行**无主键交集**: 两种成因都不是被测代码的缺陷 ——
        # ① 活数据随时间变, 坐标键重算后与冻结行集不再重叠;
        # ② gold 是合成素材 (如 missing_column 的 syn_missing), 实测却是真实抓取。
        # 行级逐格对账在这两种情形下都没有基础, 记 N/A 而非 FAIL。
        # **代价**: live 层因此不判"值错了但结构没错" —— 那一类已随回放层一并失去
        # (见 docs/REPLAY-RETIREMENT-CRITERIA.md §3.2); 语义类判据由 M3/M5 承担
        # (它们不依赖行集)。
        return {"score": None, "pass": True, "compared_fields": 0,
                "mismatched_fields": 0, "per_field_errors": {},
                "blockers": [], "not_applicable": True,
                "note": "live 下实测行与 gold 行无主键交集 (活数据变化 / 合成素材), "
                        "逐格对账无基础 → N/A"}
    passed = consistency == 1.0 and (compared > 0 or not gold_expects_rows)  # 有行却一格没比 = 判据空转
    return {
        "score": consistency,                   # 一致率: 逐格加权, 不是按行加权
        "pass": passed,
        "compared_fields": compared,            # 分母进报告: 0 比对却 1.0 一眼看出虚高
        "mismatched_fields": mismatches,        # 分子, 供人复算 1-x/y
        "per_field_errors": {k: v[:5] for k, v in per_field.items()},  # 每列只留 5 条: 否则报告不可读
        "blockers": [] if passed else ["field_mismatch"],   # 单一码: 具体错在哪一列看 per_field_errors
    }
