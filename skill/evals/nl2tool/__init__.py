# -*- coding: utf-8 -*-
"""evals.nl2tool — E1 自然语言→工具调用正确性评测 (决策门)。

定位: 给定一句自然语言, 验"选哪个工具/传什么参数/该不该澄清/该不该拒绝"
的**决策** — 不验取回来的数据对不对 (那是 E2 的活)。评测仅离线判定,
标注答案不入 RAG 索引 (防污染, docs/eval-E1-nl2tool.md §9)。

结构: tasks.yaml (26 条专家标注) / normalizers.py (七族归一化器) /
graders.py (三类 grader + 六维指标 + 红线) / runner.py (跑批入口) /
broken/ (反证夹具: 已知坏轨迹必须被判 FAIL) / tests/ (单测)。
"""
