# -*- coding: utf-8 -*-
"""evals.repro.consistency.pac — PAC 参数一致率 (先归一再比, 调用级全等主口径)。

口径 (文档 §5.2): 角度→度 (容差 1e-6) / 半径→角秒 (1e-3) / 列名**全限定**
(裸名与带前缀名视为不一致 — 投影稳定性正是 PAC 要抓的) / 枚举精确 /
columns 按集合 / bool 与 None 精确。两个口径: PAC_call (整条调用全等,
主指标) 与 PAC_field (字段级, 定位哪个字段在抖)。stable_uri 的 sqlid
易失, 归一时剥离 (文档 §5.2 地雷)。

职责: 算 E6 的参数一致率 PAC, 回答"同一任务重复跑, 第 i 次工具调用带
  的参数有多大比例与参照一致" —— 与 TSC (看选了哪些工具)、RDC (看拿回
  什么数据) 分工在"怎么调"这一层。
所属实验: E6 可复现与效率 (32 任务 + R0 路实跑); 口径真值是
  docs/eval-E6-reproducibility.md §5.2, 归一细则在 evals/repro/normalize.py。
对外接口: pac(runs) -> {"pac_call", "pac_field", "unstable_fields",
  "mode_calls"}; 内部 _value_same 做字段级容差判定, _call_key / _hashable
  把嵌套参数压成可哈希键供众数比对复用。
依赖与数据流: 输入 = N 次运行的调用参数序列 (第 i 个 dict 对第 i 次工具
  调用, 与 TSC 的工具序列按位对齐); 产物 = 纯字典, 进归因表与报告,
  自身不落盘、不读盘。
关键契约与不变量: 纯离线, 只在回放轨迹上比较, 不发起任何调用;
  同一组 runs 重复计算必须得到逐字段相同的 PAC (众数参照靠 mode 的
  先到先取固定, 换机器不会换参照); 零跨实验 import, 依赖只限 evals.repro
  内部件, 跨实验等价性由 evals/equivalence/ 的断言守护。
陷阱与边界: 列名坚持全限定, 裸名与带前缀名一律判不一致 — 投影稳定性
  正是 PAC 要抓的东西, 这里放水等于把最该报的问题藏起来。stable_uri 的
  sqlid 是文档明列的地雷, 归一时必须剥掉, 否则每次运行都会拿到不同的
  URI 而让 PAC 无意义地归零。字段级分母为 0 时给 1.0 而非 0.0, 因为
  "没有任何字段可比"是"无可指摘"而不是"全面不一致"。
"""
from __future__ import annotations

from evals.repro.normalize import norm_args  # 归一: 角度/半径/列名/sqlid 全部先在这转
from evals.repro.stats import mode  # 众数: 与 TSC/FCC 同一套参照口径


def _value_same(a, b) -> bool:
    """字段级一致判定 (浮点按 1e-6 容差; None/标量精确)。

    作用: 让"角度归一后差在小数第 7 位"这类舍入不计入漂移, 其余严格相等。
    关键参数 a/b 是两个待比较的字段值。Returns: 一致即 True。抛什么: 不抛,
    不可比较的类型退化为原样相等。
    """
    # None 必须先单独判: 缺字段与"显式声明为空"不是一回事, 混进浮点分支
    # 会在 norm_args 漏补键时把缺失误判成一致
    if a is None or b is None:  # None 走身份判: 缺字段与显式声明为空不同, 混进浮点分支会掩盖漏补键
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):  # bool 是 int 子类, 也走这里
        # 1e-6 绝对 + 1e-9 相对: 绝对项覆盖度数量级的舍入, 相对项兜住
        # 大数值 (如 1e8 量级的距离) 上绝对项压不住的尾数
        return abs(float(a) - float(b)) <= 1e-6 + 1e-9 * abs(float(b))
    # 其余 (str/bool/枚举) 精确比: 列名全限定、枚举精确都是 E6 的硬要求,
    # 对这些类型放宽容差等于放弃 PAC 的一半抓取能力
    return a == b


def _call_key(call: dict) -> tuple:
    """归一化调用的可哈希键 (列集合已排序; 值原样参与众数)。

    作用: 整条调用压成一个可哈希值, 供众数与相等判定复用。
    关键参数 call 是已归一的参数字典。Returns: 排序后的元组。
    抛什么: 不抛, 嵌套容器由 _hashable 逐层转成可哈希形态。
    """
    # 键先排序再转哈希: dict 的迭代序不保证跨进程一致, 不排序会让同一
    # 次调用在不同机器上算出不同的键, PAC 直接失去可复现性
    return tuple(sorted((k, _hashable(v)) for k, v in call.items()))


def _hashable(value):
    """值转可哈希 (list → tuple; dict → 排序项 tuple)。

    作用: 递归把嵌套容器压成可哈希形态。关键参数 value 是任意字段值。
    Returns: 可哈希对象。抛什么: 不抛; 标量原样返回。
    """
    if isinstance(value, list):  # list 保序: 排序会把"换了列顺序"这种实质漂移洗成一致
        # list 保序不排序: columns 之类参数里顺序可能承载语义, 排序会把
        # "换了列顺序"这种实质漂移洗成一致 (归一阶段已按口径单独处理过)
        return tuple(_hashable(v) for v in value)  # 只转形态, 不动内容与次序
    if isinstance(value, dict):  # dict 顺序不承载语义, 必须排序才能落同一个键
        # dict 则必须排序: 它的顺序本就不承载语义, 排序后同一份数据的
        # 不同构造方式才会落到同一个键上
        return tuple(sorted((k, _hashable(v)) for k, v in value.items()))
    return value  # 标量原样返回: 容差与精确判定都交给上层


def pac(runs: list[list[dict]]) -> dict:
    """算一个任务的 PAC (N 次运行的调用参数序列, 与工具序列按位对齐)。

    Args:
        runs: N 次运行, 每次是 ``[args_dict, ...]`` (第 i 个调用对第 i 个工具)。

    Returns:
        ``{pac_call, pac_field, unstable_fields, mode_calls}`` —
        pac_call 主口径; pac_field 字段级; unstable_fields 报不一致字段及次数。
    """
    # 空运行集两档都 0.0: 缺测不等于一致, 报 1.0 会让该任务以满分混进汇总
    if not runs:  # 提前短路: 没有序列就没有调用位可对齐, 硬算会在取 max() 那步抛错
        return {"pac_call": 0.0, "pac_field": 0.0, "unstable_fields": {},
                "mode_calls": []}  # 参照序列给空: 归因侧按长度对齐, 缺这一项会整体错位
    # 归一在比较之前做: 角度/半径/列名的口径转换全在 norm_args 里, 不先归一
    # 就比的话每次运行都会因为单位不同而全判不一致
    norm_runs = [[norm_args(c) for c in run] for run in runs]  # 归一收在本文件: 口径只有这一处, 免得两处漂移
    n_runs = len(norm_runs)  # 运行数 N: 调用级分母要乘它
    # 按位对齐而不是配对: 第 i 次调用对应第 i 个工具, 少调了一次的那次运行
    # 只能补空字典占位, 不能把后面的调用往前挪 —— 挪位会让一次"少调一次"
    # 的实质漂移看起来像参数都变了
    n_calls = max(len(run) for run in norm_runs)  # 取最长而非最短: 调用位少一次本身就是漂移, 按最短对齐会把它藏起来
    call_ok = 0                                                                                     # 调用成功计数从零起
    field_ok = field_total = 0  # 字段级分子/分母: 并集里的每个键各计一次
    unstable: dict[str, int] = {}  # 字段名 → 抖动次数, 排序后即 Top 抖动参数
    mode_calls: list[dict] = []  # 逐调用位的参照, 下标即第几次调用
    for index in range(n_calls):  # 每个调用位各取一次众数: 不同位的"标准参数"本就不同
        # 越界的运行补空 dict: 少调一次本身就是漂移, 补空才能让字段级
        # 统计把"这层调用没有这个字段"计入不一致
        column = [run[index] if index < len(run) else {} for run in norm_runs]  # 补空而非跳过: 少调一次必须在分母里留痕
        keys = [_call_key(c) for c in column]  # 同一调用位上 N 条键, 众数只在这 N 条里取
        ref_key = mode(keys)  # 参照取分布中心: 一次离群不该定义"标准调用"
        # mode_calls 取"第一个与众数键相等"的原始调用 (保持 list 等原始值 —
        # _call_key 的 tuple 化只用于众数比对, 不外泄到归因侧)
        ref = next((c for c in column if _call_key(c) == ref_key), {})  # 兜空 dict 而非 None: 找不到时下游按空调用比对, 不会 KeyError
        mode_calls.append(ref)  # 按调用位顺序追加: 下标即第几次调用, 归因侧按位取参照
        for call in column:  # 本调用位上的 N 条逐条与参照比
            if _call_key(call) == ref_key:  # 调用级判据: 整条参数全等, 不拆到字段
                call_ok += 1  # 分子只在整条全等时累加, 字段级另有一套分母
            # 取并集而非交集: 参照有而本次没有的字段 (或反之) 同样是漂移,
            # 只看交集会把"漏传参数"这种最典型的错误放过
            for key in set(ref) | set(call):  # 并集口径: 漏传与多传都是漂移, 交集会把漏参放过
                field_total += 1  # 分母按并集计, 少传字段的那一侧不得逃出统计
                if key in ref and key in call and _value_same(ref[key], call[key]):  # 三条件缺一不可: 不设"部分一致"这一档
                    field_ok += 1  # 分子只收两侧都有且落在容差内的字段
                else:
                    # 归因要的是"哪个参数最常抖", 而不是"总共抖了几次"
                    unstable[key] = unstable.get(key, 0) + 1  # 按字段名累计, 便于排序出 Top 抖动项
    return {
        # 分母含 n_runs: 少调一次的那次运行会在这里被扣成不一致, 与字段级
        # 口径保持同一套惩罚
        "pac_call": call_ok / (n_calls * n_runs),  # 调用位 × 运行数: 两个维度都要计入分母
        # 字段级分母为 0 给 1.0: 没有任何字段可比等于"无可指摘", 报 0.0
        # 会被上层当成全面不一致而把任务踢出统计
        "pac_field": field_ok / field_total if field_total else 1.0,  # 零分母给满分, 与调用级口径刻意不同
        "unstable_fields": unstable,  # 空字典即无字段抖动, 可与两档分数交叉验算
        "mode_calls": mode_calls,  # 交原始 list 而非键 tuple: 归因侧要读出真实参数值
    }
