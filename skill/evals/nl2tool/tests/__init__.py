# -*- coding: utf-8 -*-
"""evals/nl2tool/tests — E1 单测包 (归一化器/评分器/反证夹具自证)。

职责: 给 E1 的三个可测部件各自配一组自证测试 — 归一化器 (``normalizers``)
是否把等价的问法规约成同一个动作、评分器 (``graders``) 是否按 rubric 打分、
以及 ``broken/`` 里的反证夹具是否真的会被判负。这里是包标记, 判定逻辑在
同目录的 ``test_e1.py`` 与 ``test_graders.py``。

所属实验: E1 NL→工具决策 (方案真值见 docs/eval-E1-nl2tool.md), 覆盖
26 条全量用例的判分链路。

对外接口: 无导出符号 (空包标记), 对外效果仅是让 ``pytest evals/nl2tool``
在包上下文中收集本目录的测试模块。

依赖与数据流: 输入是 ``evals/nl2tool/tasks.yaml`` 里的 26 条
问句与 rubric 快照, 由 ``runner.py`` 产出判分结果; 产物只有 pytest 结论,
不额外落盘。

关键契约与不变量: 全离线 — 测试不打真实站点、不接真实模型, 工具选择
由 ``ScriptedLLM`` 之类的替身给出, 因此结果可重跑复现; E1 不得 import
其他实验目录 (零跨实验 import), 唯一的共享件是 ``evals/_data/`` 纯数据
字典, 跨实验行为一致性由 ``evals/equivalence/`` 的断言兜底。

陷阱与边界: 反证夹具 (``evals/nl2tool/broken/``) 故意写成会答错的版本,
它必须始终被判负; 若某天它"通过"了, 那多半是评分器退化成永远给满分, 而不是
夹具修好了, 所以不要为了让测试变绿去改 broken 目录。
"""
