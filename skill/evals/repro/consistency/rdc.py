# -*- coding: utf-8 -*-
"""evals.repro.consistency.rdc — RDC 返回数据一致率 (三级, 按 lane 选主口径)。

口径 (文档 §5.3): L1 ``data_hash`` 全等 (R3 快照回放主口径 — 什么都抗,
在线过于严苛); L2 行集 Jaccard/集合相等 (R1/R2 在线主口径 — 抗服务端
分页行序不稳, E2 已知坑); L3 关键字段容差一致 (补充)。主指标按 lane 选,
报告三级都给。分页行序不稳是服务端特性, 不是被测缺陷 — 所以在线主口径
必须走集合 (L2), 只有回放路才配用 L1。

职责: 算 E6 的返回数据一致率 RDC, 回答"同一任务重复跑, 工具拿回来的
  数据本身有多大比例一致" —— 与 TSC/FCC 分工在"结果数据"这一层。
所属实验: E6 可复现与效率 (32 任务 + R0 路实跑); 三级口径的真值是
  docs/eval-E6-reproducibility.md §5.3, 分页行序不稳的已知坑来自 E2。
对外接口: rdc(runs, lane) -> {"rdc", "level", "l1", "l2", "l3",
  "mode_row_count"}; 三个口径值恒定并列上报, 主指标只由 lane 决定。
依赖与数据流: 输入 = N 次运行的返回数据记录 (data_hash / row_keys /
  key_values 三元组, 由调用方从轨迹的 tool_result 事件采集);
  产物 = 纯字典, 进归因表与报告, 自身不落盘、不读盘。
关键契约与不变量: 纯离线, 只在回放轨迹上比较, 不发起任何请求;
  同一组 runs 与同一 lane 重复计算必须得到逐字段相同的结果 (众数参照
  由 mode 的先到先取固定); 零跨实验 import, 唯一依赖是 evals.repro.stats。
陷阱与边界: 三个口径的分母都用众数而非"第一次运行", 与 TSC/FCC 对齐,
  否则同一批数据在三条路径上会得出互相矛盾的结论, 归因时无从下手。
  L1 的 data_hash 逐位比对对回放最严, 任何快照文件改动都会让整条 R3
  lane 归零 — 这是刻意的高敏感度, 用来在 R0 路实跑里第一时间发现
  快照被动过。
"""
from __future__ import annotations

from evals.repro.stats import mode  # 本地: 众数, 三档口径共用同一参照


def rdc(runs: list[dict], lane: str = "R1") -> dict:
    """算一个任务的 RDC (N 次运行的返回数据记录)。

    Args:
        runs: N 次运行, 每次 ``{"data_hash": str, "row_keys": iterable,
            "key_values": dict}`` (由调用方从 tool_result 事件采集)。
        lane: R3 → L1 主口径; 其余 → L2 主口径。

    Returns:
        ``{rdc, level, l1, l2, l3, mode_row_count}``。
    """
    # 空运行集按 lane 给出对应的 level 名, 但三档值一律 0.0: 无数据
    # 不等于一致, level 只是告诉读者"本该用哪档口径", 不是已经比过了
    if not runs:  # 提前短路: 没有参照可比, 硬算三档会在取众数那步除零
        return {"rdc": 0.0, "level": "L1" if lane == "R3" else "L2",
                "l1": 0.0, "l2": 0.0, "l3": 0.0, "mode_row_count": 0}  # 三档与行数一并归零: 上层只认 rdc, 不归零会把「没数据」读成「一致」
    hashes = [r.get("data_hash") for r in runs]  # 缺键取 None: 缺失与"值就是 None"不可区分
    # L1: data_hash 逐位全等, 三档里最严, 只有回放路 (R3) 才当主指标 ——
    # 在线服务端的分页行序与时间戳会无谓地让哈希改变
    l1 = sum(1 for h in hashes if h == mode(hashes)) / len(runs)  # 基准取众数: 用第一次运行当基准, 一次坏运行就能把整条 lane 判成不一致
    # L2: 行键集合相等。转 frozenset 才能进 mode, 且集合语义天然吸收
    # 分页顺序差异 (E2 已记录的坑)
    key_sets = [frozenset(r.get("row_keys") or ()) for r in runs]  # or () 兜 None: 单次运行没采到行键时抛异常会打断整条 lane 的汇总
    ref_keys = mode(key_sets)  # 三档共用「众数当基准」, 与另两条一致率口径才可横向比
    l2 = sum(1 for k in key_sets if k == ref_keys) / len(runs)  # 集合相等才记一致: 分页行序是服务端特性, 在线主口径必须吸收它
    # L3: 关键字段值也一致。items 排序后取元组, 因为 dict 迭代序在跨进程
    # 重建时不保证, 直接对 dict 取值会把构造差异误判成数据漂移
    values = [tuple(sorted((r.get("key_values") or {}).items())) for r in runs]  # 元组化还为可哈希: dict 不能当众数与等值比较的键
    l3 = sum(1 for v in values if v == mode(values)) / len(runs)  # 分母是运行数, 不是非空记录数
    # lane 只在 R3 时切到 L1: R0/R1/R2 都是在线路, 行序不稳是服务端特性
    # 而不是被测缺陷, 用 L1 会把服务端的分页抖动算成不可复现
    main = l1 if lane == "R3" else l2  # 切档点唯一: level 与 rdc 必须由同一条件决定
    return {
        "rdc": main,
        "level": "L1" if lane == "R3" else "L2",
        # 三档恒定并列上报: 评审要能自己看"换成回放口径会不会更好看",
        # 只给主指标等于把口径选择藏起来了
        "l1": l1,
        "l2": l2,
        "l3": l3,
        "mode_row_count": len(ref_keys or ()),  # 供报告核对: 行数太少时"一致"会虚高
    }
