# -*- coding: utf-8 -*-
"""evals.groundtruth.gold.gold_dictionaries — E2 金标准字典映射层 (容差/单位/语义)。

定位: 列名 → 容差族 → atol/rtol/unit/精度下限 的**分类逻辑**; 所有数值
来自 evals/_data/tolerances.yaml 与 null_sentinel.yaml 两个数据字典单点
(E2 §7 判定分层: L1 配置外置, 改数值不改代码) — 本文件不出现任何硬编码
容差数。消费方: gen_gold.py (编排层)。

所属实验: E2 金标准一致性 (docs/eval-E2-groundtruth.md §6 M2 容差基准表 /
M3 单位与精度 / §4.2 field_values 与 null_semantics 结构), 与同目录的
gold_algorithms.py 一起构成"独立 oracle"。

对外接口: ``field_family()`` 列名分类; ``tolerance_for()`` 取容差契约;
``cell_state()`` 判单元格三态; ``field_entry()`` 产 field_values 单格条目;
``row_cells()`` 一行出双份口径; ``unit_precision_maps()`` 出 M3 的两张表。

依赖与数据流: 输入只有场景声明与已落地快照 (纯离线, 无网络无模型);
产物是 gen_gold.py 编排出的金标准 JSON, 本文件自己不落盘。

关键契约与不变量: 容差数**只允许**来自 evals/_data 数据字典, 改判据改
YAML 不改代码 (L1 外置) —— 在这里写死一个 1e-3 会让所有历史报告失去
可比性, 也让门禁与方案文档各说一套; 未登记族回落到星等族的绝对容差而非
报错, 因为"没登记"只该损失精度, 不该让整个 case 判不了; 零跨实验
import, 唯一共享件是 evals/_data 纯数据字典, 等价性由 evals/equivalence/
断言守护。

陷阱与边界: ``field_family`` 是**顺序敏感**的 —— "radius_arcsec" 必须在
"count" 之类后缀规则之前命中, 调换判断顺序会让半径列被归到别的族并套上
错的容差, 表现为"答案看着差不多却被判不一致"; ``cell_state`` 把哨兵与
真零值分成 null 与 zero 两态, 因为 M5 判的正是"缺失 vs 零"这个区分,
在这里合并成一种会让 M5 永远判不出状态错误。

白盒锚点: docs/eval-E2-groundtruth.md §6 M2 (容差基准表) / M3 (单位与精度) /
§4.2 (field_values/null_semantics 结构)。
"""
from __future__ import annotations

# 标准库: 类型标注
from typing import Any, Optional

# 本地: 算法层的基础判定 (哨兵/安全转 float) — GT 内部分层, 非被测代码
from evals.groundtruth.gold.gold_algorithms import is_sentinel, resolve_column, to_float


def field_family(column: str) -> str:  # 列名归族: 判定按族走, 不逐列硬编码, 新增列自动继承容差
    """列名 → 容差族 (分类逻辑; 数值不外置硬编码, 见 tolerance_for)。"""
    low = column.lower()  # 归一大小写后再判族: 星表导出的列名大小写不一致是实测常态
    # 下面这串判断是**顺序敏感**的短路链: 先命中的族说了算。radius 必须在
    # count/nobs 之类后缀规则之前命中, 否则 radius_arcsec 会被后面的规则
    # 抢走并套上整数计数族的容差, 表现为"数值看着差不多却被判不一致"
    if low.endswith("_id") or low == "source_id":  # _id 后缀归 identifier: 主键类不许做浮点比较
        return "source_id"
    if low == "catalog":
        return "catalog"
    # 赤经/赤纬分成两族而非一族: 两者容差量级不同, 合并会让角度列共用
    # 宽到失去意义的容差, M2 就再也抓不到坐标精度退化
    if low == "ra" or low.endswith("_ra"):  # 裸名 ra 与 _ra 同族: 星表导出两种写法都要认
        return "ra_deg"
    if low == "dec" or low.endswith("_dec"):
        return "dec_deg"
    if "radius" in low:  # radius 归半径族: 单位换算与小数位都按这一族取
        return "radius_arcsec"
    if low == "snr" or low.endswith("_snr"):
        return "snr"
    if "flag" in low:  # flag 归质量族: 质量列不该按数值容差比
        return "flags"
    if low.endswith("_err") or "psf" in low or "mag" in low:
        return "magnitude"
    if low.endswith(("nobs", "npts", "count")):  # 计数类列要求整数值: 0.5 个历元在物理上不存在
        return "count"
    # 兜底族: 未登记的数值列 (class_star/parallax/ebv 等) 仍走数值比对,
    # 只是容差借用星等族 —— 见 tolerance_for, 不在这里判错
    return "numeric_generic"


def tolerance_for(column: str, tolerances: dict) -> dict:
    """该列的容差契约 (atol/rtol/kind/exact_integer, 全部读容差表)。

    numeric_generic (class_star/parallax/ebv 等未登记族) 沿用星等族的
    绝对容差 — 字典单点, 本文件不出现任何硬编码容差数。
    """
    family = field_family(column)  # 通用数值族才回落到 magnitude 容差
    generic = family == "numeric_generic"
    # 未登记族借星等族的容差: 借的是"绝对容差"这一个量, 不是它的单位与
    # 精度下限 —— 单位/精度各自走 units 与 precision_min_digits 两张表,
    # 串在这里会让未登记列凭空获得一个它没有的单位
    spec = tolerances["fields"].get("magnitude" if generic else family)
    if spec is None:  # 表里没登记的族即抛: 静默给默认容差会掩盖登记遗漏
        # 连星等族都没登记时的最后兜底: 判据缺失必须留 atol=0.0 的严格相等
        # 而不是抛错, 否则字典改错会让整批 E2 跑不起来 (该由字典守卫去报)
        spec = tolerances["fields"]["magnitude"]
    return {
        # family 回写为 numeric_generic 而非 magnitude: 报告要能看出这一格
        # 是借容差比的, 否则统计"哪族失分最多"时会把借来的都算到星等头上
        "family": "numeric_generic" if generic else family,
        "kind": spec.get("kind", "numeric"),
        # atol/rtol 统一转 float: YAML 里写成字符串也不会在比对时抛类型错
        "atol": float(spec.get("atol", 0.0)),
        "rtol": float(spec.get("rtol", 0.0)),
        # exact_integer 决定计数类是否必须整值比对, 默认 False 走容差
        "exact_integer": bool(spec.get("exact_integer", False)),
    }


def cell_state(column: str, value: Any) -> str:
    """单元格语义类别 (E2 M5 四态在 GT 侧的裁定): null/zero/value。"""
    if value is None or str(value).strip() == "":  # 空值与哨兵分判: 缺测与脏值在 M3 上结论不同
        return "null"
    if is_sentinel(column, value):  # 哨兵与空串同归 null: 这里判的是语义态, 不是字面量
        # 哨兵也归 null: 落库时的哨兵与真缺失在语义上都是"这一格没有值",
        # M5 判的是语义态而不是字面量, 所以这里必须与空串同态
        return "null"
    number = to_float(value)  # 转数只为分出 zero 态: 转不成的走末尾的 value 兜底
    # 0.0 是"有值且为零", 与 null 严格分开: 这是 M5 状态判据的核心区分,
    # 一旦合并, "该字段没查到"与"查到但值为零"会互相掩盖
    if number is not None and number == 0.0:  # 测到 0.0 与缺测必须可区分: 前者是真值, 后者是 null
        return "zero"
    return "value"


def field_entry(column: str, value: Any, tolerances: dict) -> dict:
    """field_values 单格条目: 标准值 + 类型 + 容差 (容差来自字典)。"""
    tolerance = tolerance_for(column, tolerances)                                       # 容差先定族再取数: 单位与精度下限都要跟着族走, 分开取必然漂移
    unit = tolerances.get("units", {}).get(tolerance["family"])  # 单位与容差同一处取: 两者分开取必然漂移
    state = cell_state(column, value)                                             # 三态先裁定: null 决定容差字段给不给, 也决定 raw 留不留原字面量
    if state == "null":
        # null 条目容差字段一律置 None 而不是 0.0: "没有值"不存在容差可言,
        # 填 0.0 会让 M2 用严格相等去比一个不参与比对的格, 凭空造出失分
        return {"v": None, "t": "null", "unit": unit, "atol": None, "rtol": None,
                # raw 留原始字面量: 排查时要能看出落库的是哨兵数还是空串,
                # 两者归成同一个 null 但根因完全不同
                "raw": None if value is None else str(value)}
    number = to_float(value)                                                                 # 先试转数再按 kind 划界: 看着像数不等于该按数比
    # 只有 kind=numeric 的列才走 float 分支: 字典里声明为 string/boolean 的
    # 列即使看起来像数字也按字符串比, 否则 "001" 会被归一成 1.0 判相等
    if number is not None and tolerance["kind"] == "numeric":
        return {"v": number, "t": "float", "unit": unit,
                "atol": tolerance["atol"], "rtol": tolerance["rtol"],
                "exact_integer": tolerance["exact_integer"]}
    # 兜底字符串条目同样不携带容差, 与 null 分支保持同一形状,
    # 消费侧 (M2) 才能不分类型地遍历
    return {"v": str(value).strip(), "t": "string", "unit": unit,
            "atol": None, "rtol": None}


def row_cells(row: dict, compare_columns: list[str], header: list[str], catalog: str,
              tolerances: dict) -> tuple[dict, dict]:                             # 返回双子表而非合并表: 消费方 M2 与 M5 各取一份, 合并会让两侧耦合
    """一行的 (field_values 条目, null_semantics) 双子 dict — 两处消费同一口径。"""
    entries, states = {}, {}                                                                   # 两份表分别建: 同一次遍历产出, 但彼此不共享结果
    for column in compare_columns:                                                             # 按逻辑列遍历而非按表头: 金标准的键必须跨快照稳定
        resolved = resolve_column(header, column, column, catalog)  # 列名先解析再取值: 带不带星表前缀两种形态都要落到真列
        if resolved is None:                                                               # 快照没这列即跳过: 「没这个列」与「这列是空的」必须分开判
            # 该逻辑列在本次快照表头里不存在 → 这一格不参与比对。跳过而非
            # 记成 null: "没这个列"和"这个列是空的"是两回事, 混起来会让
            # M2 报出一堆查无此列的假失分
            continue
        value = row.get(resolved)                                                          # 按解析后的真列名取值: 带不带星表前缀两种形态都落到同一格
        # 键用逻辑列名而非解析后的实际列名: 快照列序/前缀可以变, 金标准
        # 的键必须跨快照稳定, 否则 M1/M2 的比对会因列改名整体失配
        entries[column] = field_entry(resolved, value, tolerances)                                # 键用逻辑列名: 快照改名不该让金标准整体失配
        # states 与 entries 是**同一口径的两次计算**而非两套规则: M2 用
        # entries 比值, M5 用 states 比态, 两者若算法分叉就会自相矛盾
        states[column] = cell_state(resolved, value)                                 # 同一口径的第二次计算: M2 比值、M5 比态, 算法分叉就会自相矛盾
    return entries, states


def unit_precision_maps(compare_columns: list[str], header: list[str], catalog: str,
                        tolerances: dict) -> tuple[dict, dict]:                      # 单位与精度分两张表: 合成一张会互相覆盖, M3a/M3c 各自取一份
    """unit_map / precision_map (E2 M3a/M3c): 族 → 单位/最少有效位数, 读容差表。"""
    # radius 恒定入表 (即使本次没比对半径列): M3 的量纲探针要拿它当
    # "角度类字段用角秒"的自证样本, 缺了这条判据就只剩"声明单位对不对"
    unit_map = {"radius_arcsec": tolerances["units"]["radius_arcsec"]}  # 半径单位单独钉: 弧秒与度混用会让半径判据整体失真
    precision_map: dict[str, int] = {}                                                    # 精度表独立建: 单位表钉了半径自证样本, 精度表没有这类钉法
    for column in compare_columns:                                                         # 同样按逻辑列遍历: 解析失败也不退出, 下面会退回列名本身
        # 解析不出就退回逻辑列名本身: 这两张表是"该字段该有什么单位/精度"
        # 的声明, 与本次快照有没有这一列无关, 提前退出会让 M3 少判一项
        resolved: Optional[str] = resolve_column(header, column, column, catalog) or column  # or column 兜底: 这是「该字段该有什么单位」的声明, 与本次快照有没有该列无关
        family = tolerance_for(resolved, tolerances)["family"]
        unit = tolerances.get("units", {}).get(family)
        if unit:                                                                    # 只收录有单位声明的族: 空单位不入表, 免得 M3 判成「声明单位为空」
            unit_map[resolved] = unit                                                            # 键用真列名: M3 的量纲探针按实际列名取格子
        digits = tolerances.get("precision_min_digits", {}).get(family)  # 小数位下限来自同一张表: 报告里"18.20"和"18.2"不能互相冒充
        # 字典没登记该族精度 → 不进表 (M3 会跳过它), 而不是塞个 0 把
        # "没要求"变成"零位有效数字也算达标"
        if digits:                                                                    # 0 视为未登记: 塞 0 会把「没要求」变成「零位有效数字也算达标」
            precision_map[resolved] = int(digits)                                        # 转 int: 表里写成字符串也不会让 M3 的位数比较抛类型错
    return unit_map, precision_map
