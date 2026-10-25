# -*- coding: utf-8 -*-
"""evals.groundtruth — E2 查询结果与数据库金标准一致性实验包。

定位: 同一个冻结快照上, Skill 交出来的行和数跟人工审核过的标准答案
是不是一模一样 (docs/eval-E2-groundtruth.md)。七个指标 M1–M7 各自算分,
阻断项任一命中即 FAIL; 判定器自身须经反证夹具自证 (metascore=1.0)。

结构: canonical.py (标准行集) / transport.py (快照回放) /
snapshots/ (冻结快照族, L 类保真 + S 类合成) / gold/ (独立 oracle + 签字) /
scenarios/ (8 类场景用例) / metrics/ (M1–M7) / broken/ (反证夹具) /
run_e2.py (编排 + 报告 + 退出码)。
"""
