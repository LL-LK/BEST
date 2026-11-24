# -*- coding: utf-8 -*-
"""evals.repro.consistency.fcc — FCC 最终结论一致率 (结论卡四子项, 众数口径)。

口径 (文档 §5.4): **不比对逐字文本** (同结论措辞差异无意义) — 抽取结论卡
(kind/key_numbers/key_entities/caveats) 归一后比对, 四子项全一致才记 1;
FCC = Σ(众数卡出现次数/N)/T。数值按相对容差 1e-6; 实体/限定语按集合;
stable_uri 剥离 session_id 后进实体集 (sqlid 易失)。
L2 (专家) 只做语义等价判定且不得翻转 L0 — 本文件只实现 L0 部分。

职责: 算 E6 的结论卡一致率 FCC, 回答"同一任务重复跑 N 次, 最终结论
  有多大比例落到同一张卡"这个问题, 并把不一致拆到四个子项上供归因。
所属实验: E6 可复现与效率 (32 任务 + R0 路实跑); 口径真值是
  docs/eval-E6-reproducibility.md §5.4, 归一化细则在 evals/repro/normalize.py。
对外接口: fcc(runs) -> {"fcc", "mode_card", "sub_item_failures"}; 内部
  _card_key 把归一后的结论卡压成可哈希键供众数与相等判定复用。
依赖与数据流: 输入 = N 次运行各自的原始结论卡 (由调用方从轨迹的结论卡
  事件采集, 本文件不做采集); 产物 = 纯字典, 汇入 evals/repro/attribution.py
  的归因表, 自身不落盘、不读盘。
关键契约与不变量: 纯离线, 只在回放轨迹上判定, 不发任何请求; 同一组 runs
  重复计算必须得到逐字段相同的结果 (众数并列时靠 mode 的先到先取保证
  可复现, 否则 FCC 会在不同机器上漂移); 零跨实验 import, 依赖只限
  evals.repro 内部件, 跨实验等价性由 evals/equivalence/ 的断言守护。
陷阱与边界: 1e-6 是相对容差而非绝对容差, 因为星等可以是大数也可以是
  0.001 量级的视差; 用绝对容差会让大数值的舍入差异被误判成漂移。反过来,
  子项统计里刻意不把 kind 翻转牵连到 key_numbers — 否则归因表会把一次
  结论类型切换重复计成两种漂移, 掩盖真正的单点故障 (D-6 修复)。
"""
from __future__ import annotations

from evals.repro.normalize import norm_card  # 归一: 单位换算/sqlid 剥离都在这一件里
from evals.repro.stats import mode  # 众数: 参照必须是分布中心, 不能取首抽样


def _card_key(card: dict) -> tuple:
    """归一化结论卡的可哈希键 (集合转 frozenset; 数值保留 float)。

    作用: 众数与相等判定共用的唯一比较口径。关键参数 card 是已归一的
    结论卡。Returns: 四元组, 可直接进 mode/作 dict 键。抛什么: 不抛,
    缺子项由 norm_card 补齐后再进来。
    """
    # 实体与限定语转 frozenset: 这两项本身无序, 保留 list 会让同一张卡的
    # 不同排列被算成两张, FCC 会被集合顺序噪声压低
    return (
        card["kind"],                        # 结论类型: 枚举精确, 不做近似匹配
        # 数值保序且保 float: 同一组数换序是实质漂移 (口径变化), 不能像
        # 实体那样无序化; 容差比较留给 _numbers_equal, 这里只求可哈希
        tuple((n["field"], n["value"]) for n in card["key_numbers"]),  # 保序: 数值换序是口径变化的实质漂移, 不像实体那样可无序化
        frozenset(card["key_entities"]),     # 无序化: 同一张卡的不同排列必须落同一个键
        frozenset(card["caveats"]),  # 限定语同理无序: 换个排列仍是同一张卡, 否则 FCC 被排列噪声压低
    )


def fcc(runs: list[dict]) -> dict:
    """算一个任务的 FCC (N 次运行的 ``{"card": 结论卡}``)。

    Args:
        runs: N 次运行, 每次 ``{"card": {...}}`` (原始结论卡, 内部归一)。

    Returns:
        ``{fcc, mode_card, sub_item_failures}`` — sub_item_failures 报
        漂移子项 (kind/key_numbers/key_entities/caveats) 及次数, 供归因。
    """
    # 空运行集给 0.0 而不是 1.0: 没有数据等于没测, 报满分就是 fail-open;
    # 上层 lane 汇总会把这类任务计入分母, 缺测因此不会被悄悄抹平
    if not runs:  # 提前短路: 没有参照卡时分子分母都无意义
        return {"fcc": 0.0, "mode_card": None, "sub_item_failures": {}}
    # 归一在函数内做而不是要求调用方: 调用方是从任意轨迹位置采卡的,
    # 把归一责任推出去等于留一条"忘了归一就静默算漂移"的路
    cards = [norm_card(r.get("card") or {}) for r in runs]  # or {} 兜缺卡: 单次没采到卡不该打断整条 lane
    # 以众数卡为参照而非"第一次运行的卡": 众数口径对单次离群运行免疫,
    # 第一次运行只是 N 次里的随机一个, 用它当基准会让 FCC 随种子漂移
    ref_key = mode([_card_key(c) for c in cards])  # 众数对单点离群免疫, 首抽样不免疫
    ok = sum(1 for c in cards if _card_key(c) == ref_key)  # 分子: 四子项全等才算一致
    failures: dict[str, int] = {}                         # 子项 → 漂移次数; 缺键即从未漂过
    # 取一张真的等于众数的卡当参照卡: 后面子项统计要读它的字段, 而
    # ref_key 只是键, 没有可读字段 (归一后四子项都在卡上)
    ref_card = next((c for c in cards if _card_key(c) == ref_key), None)  # 键比完要还原成卡, 下面按子项读它的字段

    def _numbers_equal(card: dict, reference: dict) -> bool:
        """key_numbers 子项单独比 (field, value) 配对 (带 1e-6 容差)。

        不能用 cards_equal (比全部四子项) — 那会让 kind 翻转时连带多报
        key_numbers, 漂移定位失真 (D-6 修复)。
        """
        # 先比长度: 长度不等时后面的 zip 会静默截断, 少一个数也会判成一致
        if len(card["key_numbers"]) != len(reference["key_numbers"]):  # 长度是硬闸: 少报一个数就是漏了指标
            return False
        for left, right in zip(card["key_numbers"], reference["key_numbers"]):  # 按位配对: 数值项保序
            if left.get("field") != right.get("field"):  # 名不同即换了指标, 位置对齐只是巧合
                return False
            try:
                # 1e-6 取相对量级: 归一后的值里既有 16.812 也有 0.00231,
                # 绝对容差会在大数侧放过肉眼可见的差异
                if abs(float(left.get("value")) - float(right.get("value"))) > 1e-6:  # 阈值定在比较侧: 归一只管单位, 容差属判定口径
                    return False
            except (TypeError, ValueError):  # 非数值走原样相等: 强转只会抛
                # 非数值 (如 "无"/None) 退回原样相等: 强转会抛异常,
                # 而"两个都是无"确实是子项一致的
                if left.get("value") != right.get("value"):  # 原样相等即可: 这一档不设容差, 文本没有"接近"可言
                    return False
        return True  # 长度、字段名、数值三关都过才落到这里

    for card in cards:  # 逐张卡与参照做子项比对, 分子在上面已定, 这里只出归因
        # 跳过与参照卡相同的运行: 它们不是漂移样本, 计进去会让四个子项
        # 的计数都被稀释, 归因表看不出真正的分歧点
        if ref_card is None or _card_key(card) == ref_key:  # 无参照卡时整列无意义, 与参照同键则不构成漂移
            continue
        # 四个子项逐一判定: 一张漂移卡可能同时命中多项, 因此是累加而非
        # 记一次 — 归因要的是"哪一项最常漂", 不是"漂了几张卡"
        for sub in ("kind", "key_numbers", "key_entities", "caveats"):  # 四项各自独立判定, 不短路
            same = (  # 一次算完三项判定, 分支与子项名一一对应, 漏一支就等于漏判该子项
                card["kind"] == ref_card["kind"] if sub == "kind"
                else _numbers_equal(card, ref_card) if sub == "key_numbers"
                # 实体与限定语按集合比: 顺序不承载语义, 按列表比会把
                # 重排误报成漂移 (这类重排在归一阶段已尽量消化)
                else set(card[sub]) == set(ref_card[sub])
            )
            if not same:  # 累加而非置位: 同一子项被多张卡命中要如实计数
                failures[sub] = failures.get(sub, 0) + 1  # 计数可超过漂移卡数: 一卡命中多项
    return {"fcc": ok / len(cards), "mode_card": ref_card,  # 分母含参照卡自身, 全一致时为 1.0
            "sub_item_failures": failures}  # 空字典即"四子项都没漂过", 归因侧据此不改口径
