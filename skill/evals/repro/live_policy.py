# -*- coding: utf-8 -*-
"""evals.repro.live_policy — E6 自有的实跑纪律 (铁律 7 的 (a)~(d))。

**为什么是本实验自己的一份副本**, 而不是 import ``evals.groundtruth.live_policy``:
铁律 6 规定实验须自包含, 跨实验 import 只允许 ``evals/_data`` (纯数据字典) 与
``evals/equivalence`` (裁判)。本模块是**代码**不是数据, 所以进不了那个白名单。
仓里已有同类先例 —— 各实验各持一份判定实现的副本, 由 ``evals/equivalence`` 的
判定口径等价性测试守卫。本件沿用那套办法: 自己一份, 口径对齐, 等价性有测试兜底。

能力边界: 只管"打真实站点时的行为准则"—— 请求间隔、错误重试边界、请求计数。
不负责查询语义 (那是 ``src.protocol``)、不负责结果判定 (那是 consistency/stats)。

对外接口: :data:`RATE_LIMIT_SECONDS` / :func:`pace` / :data:`ARTIFACT_DIR`。

依赖: 只用标准库。不 import 被测代码, 不读配置 —— 纪律必须是硬编码常量,
配置化等于"可以被人关掉"。
"""
from __future__ import annotations

# 标准库: 计时
import time  # pace: 场景之间的强制间隔

# 客户端限速器取值: 铁律 7 (b) 要求串行且强制间隔。取 1.5 秒 —— 比站点侧任何
# 合理限速都保守。**live 路径不得归零**: 归零后连续 phase-1/phase-2 会把真站点
# 当压力源打; R0 的回放探针可以归零, 因为它的请求全被 transport 拦下、零外网。
RATE_LIMIT_SECONDS = 1.5

# 场景之间的额外间隔: 与客户端限速**叠加**。客户端限速只管"两次请求之间",
# 这里管"两个场景之间" —— 后者要留够时间让站点喘口气。
SCENARIO_GAP_SECONDS = 1.5

# 实跑产物落点: temp/ 是铁律 3 的临时区且 gitignored。
ARTIFACT_DIR = "temp/live_runs"


def pace(what: str = "") -> None:
    """在两个场景之间睡一个强制间隔, 并把这次等待打到 stderr 上。

    刻意**每次都睡**而不是"按需睡": 判据是"上一次调用距今是否已够", 那需要跨模块
    保存时间戳, 而各跑批件的执行顺序各不相同, 共享状态比统一无条件睡更容易出错。

    Args:
        what: 场景标识, 只进日志便于排查"卡在哪一步"。
    """
    time.sleep(SCENARIO_GAP_SECONDS)  # 无条件睡: 共享时间戳比统一等待更容易漏间隔
    if what:  # 非交互 CI 里 stderr 是唯一能看见"这批在动"的出口
        print(f"[live] 间隔 {SCENARIO_GAP_SECONDS}s 已过: {what}", flush=True)
