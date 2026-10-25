# -*- coding: utf-8 -*-
"""evals.robustness.live_policy — E4 自有的实跑纪律 (铁律 7 的 (a)~(d))。

**为什么是本实验自己的一份副本**: 铁律 6 规定实验须自包含, 跨实验 import 只允许
``evals/_data`` (纯数据字典) 与 ``evals/equivalence`` (裁判)。本模块是**代码**不是
数据, 进不了那个白名单。仓内先例: E2/E4/E6 各持一份 transport 副本, 由
``evals/equivalence`` 断言逐字同值; 本件沿用那套办法。

**E4 特有的纪律**: W 层的 15 条用例打的是可控回放 (故障要有牙, 底层就得可控),
限速器在那里归零是对的 —— 触不触网由 transport 决定, 不是限速器。但
:func:`evals.robustness.runner.live_baseline` 真打站点, 所以**那一路**必须用本件
的 1.5s 间隔。一份模块里两种限速并存时, 判据是"这个请求会不会真的出网"。

对外接口: :data:`RATE_LIMIT_SECONDS` / :func:`pace` / :data:`ARTIFACT_DIR`。

依赖: 只用标准库。不 import 被测代码, 不读配置。
"""
from __future__ import annotations

# 标准库: 计时
import time  # pace: 用例之间的强制间隔

# 客户端限速器取值: 铁律 7 (b)。取 1.5 秒, 比站点侧任何合理限速都保守。
RATE_LIMIT_SECONDS = 1.5

# 用例之间的额外间隔: 与客户端限速叠加。
SCENARIO_GAP_SECONDS = 1.5

# 实跑产物落点: temp/ 是铁律 3 的临时区且 gitignored。
ARTIFACT_DIR = "temp/live_runs"


def pace(what: str = "") -> None:
    """在两个用例之间睡一个强制间隔, 并把这次等待打到 stderr 上。

    刻意每次都无条件睡: "距上次是否已够"需要跨模块共享时间戳, 而各跑批件执行
    顺序不同, 共享状态比统一等待更容易漏间隔。

    Args:
        what: 用例标识, 只进日志便于排查"卡在哪一步"。
    """
    time.sleep(SCENARIO_GAP_SECONDS)  # 无条件睡: 共享时间戳比统一等待更容易漏间隔
    if what:  # 非交互 CI 里 stderr 是唯一能看见"这批在动"的出口
        print(f"[live] 间隔 {SCENARIO_GAP_SECONDS}s 已过: {what}", flush=True)
