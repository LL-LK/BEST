# -*- coding: utf-8 -*-
"""evals.ablation — E5 基线与消融实验 (完整系统的分数里, 每一部分是谁贡献的)。

结构 (docs/eval-E5-baseline-ablation.md §10 落地清单):
  items.yaml          30 条统一任务集 (D12 / C6 / R6 / S6; data_anchor/gold_result/
                     assertions/fixed_followup/applicable 四组新增字段)
  hypotheses.yaml     预登记假设 (跑前冻结, 跑后只核对; A1–A5 + sham + add-back)
  systems/            11 份装配表 (B0/B1/B2a/B2b/B3 + A1–A5 + sham_placeholder)
  harness/            装配层 (三个工具面适配器 + ScriptedLLM 替身 + 跑批编排)
  metrics/            三门合成 (ESR_data/ESR_know/ESR_full + 幻觉三通道 + 拒绝/澄清)
  broken/             反证夹具 V-1..V-7 (metascore 必须 1.00)
  report.py           §12 五张表渲染
  runner.py           入口 (--systems/--category/--repeat/--scripted)
  tests/              单测 (任务集完备性 / 假设冻结 / 三门正反例 / metascore / 冒烟)

铁律: **零跨实验 import** — 本包不 import evals/ 下任何其它实验的代码, 只按路径
读数据文件 (evals/_data 哨兵字典 / references/tools.schema.json / evals/semantics
的 fixtures 节 / evals/groundtruth 的快照与 gold); 与 E1/E2/E3 判定器的等价性**无断言覆盖** (evals/equivalence 只断言 E2/E4/E6
的 transport; 该悬空已登记于 equivalence/import_isolation.py:15)。禁 version 键; 中文 docstring; 净代码 ≤400 行/文件。

白盒锚点: docs/eval-E5-baseline-ablation.md (唯一真值方案)。
"""
