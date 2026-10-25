# -*- coding: utf-8 -*-
"""evals.repro.consistency.tsc — TSC 工具选择一致率 (序列口径, 众数参照)。

口径 (文档 §5.1): 两次运行的工具调用**序列** (去连续重复, 保序) 比对 —
严格档全等记 1; 宽松档工具集合相等记 1 (另报顺序 Jaccard); 聚合
TSC = Σ(众数序列出现次数/N)/T; 另报 Krippendorff α (名义尺度) 与
pairwise 均值 (防众数被五五开分布掩盖)。

为什么用序列不用集合: resolve_name→cone_search 与 cone_search→resolve_name
集合相同语义相反 (后者是拿结果反查名字), 只看集会漏判 (文档 §5.1 注)。

职责: 算 E6 的工具选择一致率 TSC, 回答"同一任务重复跑, 走出来的工具
  调用序列有多大比例一致" —— 衡量的是决策路径的稳定性, 不只是结果。
所属实验: E6 可复现与效率 (32 任务 + R0 路实跑); 口径真值是
  docs/eval-E6-reproducibility.md §5.1 (严格档/宽松档/众数/α/pairwise 五种)。
对外接口: tsc(runs) -> {"tsc", "tsc_strict", "tsc_set", "pairwise",
  "mode_sequence", "alpha"}; 内部 _dedupe_consecutive 把序列压成可哈希元组。
依赖与数据流: 输入 = N 次运行各自的工具名序列 (由 evals/repro/trace.py
  从轨迹事件抽好后传入); 产物 = 纯字典, 进归因表与报告, 自身不落盘。
关键契约与不变量: 纯离线判定, 不触发任何工具调用; 同一组 runs 重复计算
  必须得到同一 TSC — 众数并列时靠 mode 的先到先取固定参照, 否则换台
  机器就换一批"一致"; 零跨实验 import, 依赖只有 evals.repro.stats。
陷阱与边界: 宽松档按集合比会放过顺序错误, 所以严格档与宽松档必须并列
  报告 — 只看 tsc_set 会让"先解析名字还是先搜天区"这类实质差异消失。
  pairwise 分母为 0 (N=1) 时给 1.0: 单次运行没有可比的第二次, 报 0.0
  会被上层当成"彻底不一致", 把该任务从统计里踢掉。
"""
from __future__ import annotations

from evals.repro.stats import krippendorff_alpha_nominal, mode  # 众数与 α 的单点实现


def _dedupe_consecutive(sequence: list) -> tuple:
    """去连续重复项保序成 tuple (可哈希, 供众数与 α 消费)。

    作用: 抹掉"同一工具连调两次"这种无信息重试, 但保留有意义的顺序。
    关键参数 sequence 是单次运行的工具名列表。Returns: 可哈希 tuple。
    抛什么: 不抛; None 入参按空序列处理。
    """
    out: list = []  # 累积去重结果; 顺序是语义的一部分, 不可退化成集合
    for item in sequence or ():  # or () 兜 None: 缺序列的那次运行按空序列参与统计, 不打断汇总
        # 只去**连续**重复: 非相邻的同名调用 (A→B→A) 承载的是回退重试的
        # 决策信息, 一并去重会把真实的路径变化抹平
        if not out or out[-1] != item:  # 只看末位: 全局去重会抹平回退重试这段决策信息
            out.append(item)  # 保序累积: 顺序本身是 TSC 的判据, 退化成集合就废了
    return tuple(out)  # 转 tuple 换取可哈希: mode 与 set 都要拿它当键


def tsc(runs: list[list[str]]) -> dict:
    """算一个任务的 TSC (N 次运行的工具名序列)。

    Args:
        runs: N 次运行的工具名序列 (每次运行一个 list)。

    Returns:
        ``{tsc, tsc_strict, tsc_set, pairwise, mode_sequence, alpha}``。
    """
    # 空运行集五项全给 0.0: 与 FCC 同理, 无数据不是满分, 否则该任务会在
    # 汇总里以满分混进均值, 把"没跑到"洗成"跑到且完美"
    if not runs:  # 提前短路: 没有参照序列时五项都算不出来
        return {"tsc": 0.0, "tsc_strict": 0.0, "tsc_set": 0.0,
                "pairwise": 0.0, "mode_sequence": [], "alpha": 0.0}  # 五项全 0.0: 无数据不是满分, 否则该任务以满分混进均值
    sequences = [_dedupe_consecutive(r) for r in runs]  # 先归一再比: 不去重会把重试次数算成不一致
    n = len(sequences)  # 分母恒为 N: 空序列也是一次真实运行, 不该被剔出统计
    # 众数作参照: 与 FCC 同一理由 —— 参照系必须是分布的中心而非任一次抽样
    ref = mode(sequences)  # 众数对单点离群免疫, 首抽样不免疫
    main = sum(1 for s in sequences if s == ref) / n  # 与众数逐位全等才记一致 (顺序即决策路径)
    ref_set = set(ref or ())  # 宽松档专用集合: 严格档仍逐位比元组, 两档判据刻意不同
    # 宽松档: 工具集合相等即算一致, 顺序差异另由 mode_sequence 与严格档暴露
    set_level = sum(1 for s in sequences if set(s) == ref_set) / n  # 集合相等即一致, 顺序分歧留给严格档
    ok = total = 0  # pairwise 的分子与分母: 严格档全等的对数 / 全部对数
    # 两两配对只取 i<j: 配对本身无序, 全遍历会把 total 翻倍而 ok 同比翻倍,
    # 均值虽不变, 但 N 较小时 total 很小、计数的相对误差被放大
    for i in range(n):  # 逐对比较是众数法的兜底: 五五开分布会让众数参照失真
        for j in range(i + 1, n):  # 只取 i<j: 配对无序, 计入反向对会把计数翻倍
            total += 1  # 分母按对数累加, 与分子同口径
            ok += 1 if sequences[i] == sequences[j] else 0  # 分子仍用严格档: 换成宽松档就与 tsc_set 重复了
    return {
        # 主指标取严格档: 决策顺序是"选了哪些工具"的实质部分, 宽松档只
        # 适合当辅助证据; 两者相等时并列给出, 读者能看出分歧来自顺序
        "tsc": main,  # 主指标=严格档, 单列一份是为了让报告不必自己推断
        "tsc_strict": main,  # 与 tsc 同值: 两档相等时并列给出才能看出分歧来自顺序
        "tsc_set": set_level,  # 宽松档并列: 只看它会放过"先解析名字还是先搜天区"的差异
        # 分母为 0 (N=1) 给 1.0: 一次运行没有可比的第二次, 这是"不适用"
        # 而非"不一致", 报 0.0 会让上层把它当失败样本
        "pairwise": ok / total if total else 1.0,  # N=1 无对可比, 1.0 表示"不适用"而非"不一致"
        "mode_sequence": list(ref or ()),  # 落回 list: 报告要 JSON 序列化, tuple 不行
        # 每条序列包成单元素列表喂 α: α 的输入是"单元 × 评阅者"矩阵,
        # 这里的单元就是单次运行、评阅者恒为同一条序列本身
        "alpha": krippendorff_alpha_nominal([[s] for s in sequences]),  # α 与众数法互补: 众数失真的分布靠它暴露
    }
