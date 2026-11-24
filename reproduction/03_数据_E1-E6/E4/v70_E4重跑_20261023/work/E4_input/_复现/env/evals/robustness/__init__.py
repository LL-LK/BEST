# -*- coding: utf-8 -*-
"""evals.robustness — E4 鲁棒性与安全失败实验包。

定位: 事情出错时守不守规矩 — 输入非法/网络故障/回包畸形/被人诱导时, 会不会
认错、会不会乱来、会不会把失败说成成功 (docs/eval-E4-robustness-safety.md)。
两个注入面: Tier W 线路层 (故障剧本, 程序判定, 已实跑) / Tier P 话术层
(用户原话, C/D 级专家盲评, 只做标注完备性)。

结构: items.yaml (68 条标注: RB-01..50 + RB-C01..18) / rubric.yaml (指标规约) /
replay.py (回放底座) / injectors/ (故障剧本) / guards.py (schema 三查) /
graders.py (M1–M7) / runner.py (跑批) / broken/ (反证夹具) / tests/ (单测)。
"""
