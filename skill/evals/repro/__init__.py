# -*- coding: utf-8 -*-
"""evals.repro — E6 可复现性/效率/用户可用性评测 (稳定性门)。

定位: 不重新评判对错 (对错归 E1/E2/E3), 只评判**稳定性、代价与可用性** —
同样的输入再来一次, 还是不是同一个结果、花同样的代价、人还用得动吗
(docs/eval-E6-reproducibility.md 定位段)。

结构: manifest.py (八项固定清单) / trace.py (端到端 trace 读写与脱敏) /
transport.py (自包含回放) / normalize.py (参数与结论卡归一) /
consistency/ (TSC/PAC/RDC/FCC 四一致率) / attribution.py (分层归因) /
efficiency.py (EF1..EF7) / usability.py (U1..U7) / stats.py (Wilson/McNemar/α) /
broken/ (6 类反证夹具) / tasks/ (REPRO-01..32) / r0_lane.py + run_e6.py (编排)。

纪律: 本实验代码**零跨实验 import** (E2/E1 各有自包含实现; 等价性由
evals/equivalence 断言守护, P7 统一建); 数据字典读 evals/_data 单点。
"""
