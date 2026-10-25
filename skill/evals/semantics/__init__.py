# -*- coding: utf-8 -*-
"""evals.semantics — E3 科学语义区分与幻觉抑制评测 (解释门)。

定位: 给定"已取到的数据" (fixture), 验受试说出来的话有没有科学错误、
有没有编数 — 与 E1 (决策)/E2 (取数)/E4 (失败) 正交。主测 Tier F 离线
fixture; live 题不计主指标。盲评 (R1/R2 + R3 仲裁) 需评阅人, 机器侧只落地
到 L0 预筛 + 数据完备 (runner 不调大模型、不联网)。

结构: items.yaml (36 题 7 轴) / rubric.yaml (量表与阈值) /
scorecard.csv (填表模板) / README.md (方案) / prescreen.py (L0
机器预筛) / broken/ (反证夹具) / report.py
(报告渲染) / runner.py (入口) / tests/ (单测)。

2026-10-07 删除 agreement.py: 一致性统计 (κ/α/AC1/ICC) 与人工仲裁随「盲评链
整链取消」一并作废 (LLM-only, 见 docs/eval-E3-semantics.md §10)。该模块全仓零
消费者 —— κ 只在**两个真正独立的人**手上有定义, 没有评阅人就无从算起, 留着只
会让人以为"一致性"仍在被计算。
"""
