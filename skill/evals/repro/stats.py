# -*- coding: utf-8 -*-
"""evals.repro.stats — E6 统计件 (Wilson 区间 / McNemar 配对检验 / Krippendorff α)。

能力边界: 手写实现三个统计量 — N=5 小样本下必须给区间而非只给点估计
(文档 §5.5 诚实声明); 一致性汇总用 α (比裸一致率抗偶然一致)。
边界: 纯函数; 不依赖 scipy (本仓零重型依赖纪律 — 离线可复现)。

白盒锚点: docs/eval-E6-reproducibility.md §5.5 (统计诚实声明) /
§11 (效力约 0.6–0.7 的口径)。

职责: 提供 E6 三个统计量的手写实现 —— Wilson 区间给一致率配上小样本
  下诚实的区间, McNemar 精确检验给两系统的配对差异定显著性, Krippendorff α
  给多次运行的一致性一个比裸一致率抗偶然一致的汇总值。
所属实验: E6 可复现与效率 (32 任务 + R0 路实跑); 统计口径与效力声明的真值
  是 docs/eval-E6-reproducibility.md §5.5 与 §11, 报告侧必须同时披露点
  估计与区间。
对外接口: wilson_interval(successes, total, z) -> (low, high) 二项比例区间;
  mcnemar_exact(b, c) -> 双侧 p 值; krippendorff_alpha_nominal(units) -> α;
  mode(items) -> 出现最多者 (并列取先出现者), 供 TSC/PAC/RDC/FCC 取参照。
依赖与数据流: 输入全由调用方传入的整数与可哈希取值序列构成; 产物是纯
  标量, 被 evals/repro/consistency/* 与 evals/repro/run_e6.py 消费, 自身
  不读盘、不落盘。
关键契约与不变量: 纯函数且不依赖 scipy (本仓零重型依赖纪律, 离线环境要能
  直接跑); 同一组输入重复计算必须得到逐位相同的结果 —— mode 的并列取
  先出现者就是为此, 换成"取字典序最小"会让参照随输入顺序漂移, 一致率
  指标会跟着变; 零跨实验 import, 上游只有标准库。
陷阱与边界: N=5 时 Wilson 区间宽到几乎横跨整个 [0,1], 这不是实现缺陷
  而是样本量的诚实呈现, 所以任何一层都不许把它压成点估计 (文档 §5.5)。
  McNemar 只看 b+c 个分歧样本, 效应约 0.6–0.7, 因此 p<0.05 只能写
  "有差异证据", 不能写成"已证明 A 优于 B"。α 在期望分歧为 0 时返回 1.0
  而非除零, 因为那种数据 (所有取值相同) 恰恰是完全一致。
"""
from __future__ import annotations

# 标准库: 数学函数 (开方/幂)、组合数 (McNemar 精确检验的二项尾) 与随机源 (bootstrap 固定种子)
import math
import random
from typing import Sequence


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """二项比例的 Wilson 95% 置信区间 (小样本比 normal 近似稳)。

    Args:
        successes: 一致 (成功) 次数。
        total: 总次数 (N=5 时区间极宽 — 必须报区间, 文档 §5.5)。
        z: 正态分位数 (默认 1.96 = 95%)。

    Returns:
        ``(low, high)`` 均截到 [0, 1]。
    """
    # 分母为 0 时给 (0.0, 1.0) 而不是抛错: 无观测就没有证据, 区间横跨
    # 全域是唯一诚实的表达; 上层拿到它自会披露"该任务无重复观测"
    if total <= 0:                                                                 # 无观测就没有证据: 区间横跨全域是唯一诚实的表达, 抛错等于让整轮统计崩掉
        return (0.0, 1.0)
    p = successes / total                          # 点估计: 必须与下面的区间一起上报, 单独出现即失真
    # Wilson 的三件套: 分母校正 1+z²/n、中心平移 z²/2n、方差加 z²/4n²。
    # 相对 normal 近似的好处是 N 小时不越界 — 一致率天然落在 [0,1] 里,
    # 近似区间冒出 -0.03 这种值在报告里没法解释
    denom = 1.0 + z * z / total                                              # Wilson 的分母校正项: N 越小收缩越强, 这是一致率不越出 [0,1] 的关键
    centre = p + z * z / (2.0 * total)             # 中心向 0.5 收缩, N 越小收缩越强
    margin = z * math.sqrt(p * (1.0 - p) / total + z * z / (4.0 * total * total))     # 方差里加 z²/4n²: 中心平移后必须同步加宽, 否则区间会不对称
    low = max(0.0, (centre - margin) / denom)      # 下界夹取: 公式值理论非负, 这里只防浮点毛刺
    high = min(1.0, (centre + margin) / denom)     # 上界同理: 报告里出现 1.02 无法解释
    return (low, high)


def bootstrap_mean_ci(units: Sequence[float], n_boot: int = 10000,
                      seed: int = 20260928, alpha: float = 0.05) -> tuple[float, float]:
    """均值的**分组重抽样**置信区间 (cluster bootstrap, 百分位法)。

    为什么不能用 Wilson: Wilson 的分母是"独立同分布的 Bernoulli 观测数", 而
    E6 的一致率是**每任务一个比值**再跨任务平均 —— 把跨任务均值乘 100 当成
    "成功次数"再除以 100, 等于凭空造出 100 个观测, 区间宽度与真实重复次数、
    覆盖任务数都脱钩 (5/5 与 100/100 会算出同一个 [0.963, 1], 这在报告里是
    无法解释的)。文档 §5.5 要求区间如实反映样本量, 所以这里重抽**任务**。

    Args:
        units: 每个单元一个观测值 (E6 传的是各任务的比值)。
        n_boot: 重抽次数。
        seed: 随机种子固定 —— 同一组输入必须逐位复现 (可复现实验的硬要求)。
        alpha: 双侧显著性水平 (默认 0.05 → 95% 区间)。

    Returns:
        ``(low, high)`` 百分位区间; 单元数 < 2 时返 (0.0, 1.0) —— 只有一个
        任务时任何重抽样都只能抽到同一个值, 报一个零宽区间比不报更危险。
    """
    values = [float(v) for v in units]
    if len(values) < 2:                                                                 # 无独立单元就没有可估的离散度
        return (0.0, 1.0)  # 与 wilson_interval(0, 0) 同款口径: 无观测即全域, 不给假窄区间
    rng = random.Random(seed)                                                           # noqa: S311 — 重抽的是任务索引不是凭据, 固定种子即可复现
    n = len(values)
    means = []
    for _ in range(max(1, n_boot)):                                                     # 每次重抽 n 个单元 (有放回), 与"重抽题"同款
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()                                                                         # 排序后取分位: 百分位法不依赖抽样顺序
    low_idx = max(0, min(len(means) - 1, int(len(means) * alpha / 2)))
    high_idx = max(0, min(len(means) - 1, int(len(means) * (1 - alpha / 2)) - 1))
    return (max(0.0, means[low_idx]), min(1.0, means[high_idx]))


def _binom_pmf(k: int, n: int, p: float) -> float:
    """二项概率质量函数 (精确 McNemar 的构件; 小 n 直接乘不溢)。

    作用: 给精确检验提供单点概率。关键参数 k/n/p 是二项的参数。
    Returns: 概率值。抛什么: 不抛; 参数非法时 math.comb 自会报错。
    """
    # 直接用 math.comb 而不是阶乘相除: n 只到 N² 量级, 阶乘在 20! 就逼近
    # 双精度上限, 组合数走整数路径没有精度损失
    coeff = math.comb(n, k)                                                           # 走整数路径: 阶乘在 20! 就逼近双精度上限, 组合数没有精度损失
    return coeff * (p ** k) * ((1.0 - p) ** (n - k))  # 末项指数 0 时返回 1.0, p∈{0,1} 不需特判


def mcnemar_exact(b: int, c: int) -> float:
    """McNemar 精确检验 (配对二值; 双侧 p 值)。

    Args:
        b: 系统 A 对 / 系统 B 错的题数。
        c: 系统 A 错 / 系统 B 对的题数。

    Returns:
        双侧精确 p 值 (b+c=0 时返回 1.0 — 无分歧即无差异证据);
        N 小时效力仅约 0.6–0.7 (文档 §5.5, 报告必须声明)。
    """
    # 只看 b+c: 两系统都对/都错的题在配对检验里不带信息, 混进样本会稀释
    n = b + c                                                                      # 分母只看 b+c: 两系统都对或都错的题在配对检验里不带信息, 混入会稀释
    if n == 0:                                                                      # 无分歧即无差异证据: 报 1.0 而非 0.0, 否则会被读成完全不一致
        return 1.0
    k = min(b, c)                                               # 零假设 p=0.5, 取较小尾再乘 2 得双侧
    tail = sum(_binom_pmf(i, n, 0.5) for i in range(0, k + 1))  # 闭区间: 观测值本身必须计入尾部
    # 乘 2 后封顶 1.0: 尾和在小 n 时可能超过 0.5, 不封顶会报出 p>1 这种
    # 报告里无法解释的值
    return min(1.0, 2.0 * tail)


def krippendorff_alpha_nominal(units: Sequence[Sequence[str]]) -> float:
    """Krippendorff α (名义尺度) — 多次运行一致性的稳健汇总。

    Args:
        units: 每个"评分单元"是一个取值序列 (如每个任务各 run 的工具序列),
            取值是可哈希对象 (如 tuple/str)。

    Returns:
        α ∈ [-1, 1] (1 = 完全一致; ≤0 = 偶然一致水平以下);
        全单元无分歧返回 1.0; 数据不足 (无有效对) 返回 0.0 并交由调用方披露。
    """
    # 观测分歧 D_o: 所有单元内两两取值的不同计数
    # coincidence 同时充当边际计数表: 期望分歧要用全局边际, 单遍累加
    # 免得再扫一遍取值
    coincidence: dict = {}                                                            # 边际计数表兼作分歧统计: 期望分歧要用全局边际, 单遍累加省一趟扫描
    total_pairs = 0                       # D_o 的分母: 只数单元内 i<j 的无序对
    disagreements = 0                                                                               # D_o 的分子: 只数单元内取值不同的对
    for values in units:                                                                  # 逐单元独立判分歧: α 衡量的是单元内一致性, 不跨单元配对
        vals = list(values)                                                         # 转 list 才能按下标取对: 入参可能是 tuple 或任意可迭代对象
        # 只取 i<j 的对: 无序对计两次会让 D_o 与 D_e 的分母不同步, α 失真
        for i in range(len(vals)):                                           # 只取 i<j 的对: 无序对计两次会让 D_o 与 D_e 分母不同步, α 随之失真
            for j in range(i + 1, len(vals)):                                             # j 从 i+1 起: 与上一行配成全部无序对, 不重复也不漏
                total_pairs += 1                                                        # D_o 的分母: 无论是否一致都要计入, 分子才只数取值不同的对
                if vals[i] != vals[j]:                                                    # 严格不等即分歧: 可哈希取值的同一性就是一致, 不做近似比较
                    disagreements += 1                                                    # 分子只收不同的对: 与分母同为无序对计数, 两个量纲必须一致
                coincidence[vals[i]] = coincidence.get(vals[i], 0) + 1                # 每个取值在每对里各记一次: 边际要的是参与配对的次数, 不是出现次数
                coincidence[vals[j]] = coincidence.get(vals[j], 0) + 1                  # 对的另一端同样要记: 少记一端会让 D_e 整体偏小, α 虚高
    if total_pairs == 0:                                                               # 一个无序对都没有: 全单元都是单值, 返回 1.0 表示无分歧可测
        return 1.0
    d_o = disagreements / total_pairs  # 观测分歧率 ∈ [0,1]: 与 D_e 同量纲才可相除
    # 期望分歧 D_e: 从边际分布随机抽两个的不同概率
    n_vals = sum(coincidence.values())                                                    # 边际总量: D_e 的分母, 与 D_o 同为参与配对的次数
    if n_vals < 2:                                                                        # 边际只落一个取值: 抽不出两个不同值, 属数据不足而非不一致
        # 边际只落在一个取值上, 抽不出两个不同值, 数据不足而非不一致
        return 0.0
    # 分子用 count*(count-1) 而不是 count²: 无序对不能自己配自己
    d_e = 1.0 - sum(count * (count - 1) for count in coincidence.values()) / (n_vals * (n_vals - 1))  # 分子用 count*(count-1): 无序对不能自己配自己, 用 count² 会高估一致
    if d_e == 0.0:                                                             # 期望分歧为零即边际全同: 那是完全一致, 返回 1.0 而非让 D_o/0 抛除零
        # 期望分歧为零意味着边际全同 — 那正是"完全一致", 返回 1.0 而不是
        # 让 D_o/0 抛 ZeroDivisionError
        return 1.0
    return 1.0 - d_o / d_e  # α 落在 [-1,1]: 越接近 1 越不是偶然一致


def mode(items: Sequence):
    """众数 (出现次数最多; 并列取先出现者 — 报告需披露并列)。

    作用: 给 TSC/PAC/RDC/FCC 提供唯一的比较参照。关键参数 items 是取值
    序列。Returns: 众数元素; 空序列返回 None。抛什么: 不抛。
    """
    if not items:                                                                    # 空序列返 None: 调用方据此判定「无参照」, 返默认值会造出假一致
        return None
    counts: dict = {}                                # 取值须可哈希: 调用方传 tuple/frozenset/str
    for item in items:                                                                        # 频次表只做累加: 参照的裁决留给后面, 这里不提前定
        counts[item] = counts.get(item, 0) + 1       # 频次表只做累加, 不在这里定参照
    best = max(counts.values())                      # 只取最高频次, 并列的裁决留给下面的循环
    # 保持首个达到众数的元素 (确定性)。刻意不改成"取字典序最小":
    # 字典序依赖取值本身的类型, 混合类型会抛; 而先到先取只依赖输入顺序,
    # 在任何平台上都稳定, 这正是可复现指标需要的性质
    for item in items:                                                                    # 按输入顺序再走一遍: 先到先取只依赖顺序, 任何平台上都稳定
        if counts[item] == best:                                                         # 首个达到最高频次者即参照: 刻意不用字典序最小, 混合类型会抛
            return item  # 首个达到最高频次者即参照: 结果只取决于输入顺序
    return None
