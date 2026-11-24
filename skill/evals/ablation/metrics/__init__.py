# -*- coding: utf-8 -*-
"""evals.ablation.metrics — E5 合成指标 (三门判定 + ESR + 幻觉三通道 + 拒绝/澄清 + 成本)。

零跨实验 import: 判定依据 (工具参数面 / 哨兵字典 / E2 gold / E3 fixtures) 一律
按**路径读数据文件**, 不 import evals/ 下其它实验的代码; 与 E1/E2/E3 判定器的
同语义精简版在本包内自带, **等价性无断言覆盖** (该悬空已登记于
equivalence/import_isolation.py:15)。

白盒锚点: docs/eval-E5-baseline-ablation.md §6 (指标体系) / §6.4 (诚实声明)。
"""
