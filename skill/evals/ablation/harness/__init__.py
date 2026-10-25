# -*- coding: utf-8 -*-
"""evals.ablation.harness — E5 装配层 (工具面适配器 + 确定性模型替身 + 跑批编排)。

能力边界: 把 systems/*.yaml 的组件开关翻译成可执行的工具面 (ToolBox 7 工具 /
BestClient 裸协议 / 预写序列), 并把 items.yaml 的 expect_tools 变成确定性
tool_call 序列。**本包零跨实验 import** — 只按路径读数据文件
(evals/_data 哨兵字典 / references/tools.schema.json / evals/semantics 的
fixtures 节 / evals/groundtruth 的快照与 gold); 与 evals/groundtruth 的
transport/metrics 等价性**无断言覆盖** (evals/equivalence 的
transport 断言只含 E2/E4/E6, 不含 E5; 见 equivalence/import_isolation.py:15)。

白盒锚点: docs/eval-E5-baseline-ablation.md §3.1 (装配表) / §10 (落地清单)。
"""
