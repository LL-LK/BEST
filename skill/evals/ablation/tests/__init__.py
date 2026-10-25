# -*- coding: utf-8 -*-
"""evals.ablation.tests — E5 单测包 (任务集/假设/三门/反证/scripted 冒烟)。

职责: 守住 E5 的**判定器与装配层**自身 — 任务集 schema 齐备、系统装配 one-at-a-time、
三门正反例、七条反证夹具全抓、scripted 端到端冒烟与确定性。本包不评被测系统好坏,
那是 E5 跑批报告的职责; 这里失败说明评分口径本身不可信。

所属实验: E5 基线与消融 (30 任务 × 10 系统 + sham 共 11 装配, ScriptedLLM 离线跑;
成功率 = ScriptedLLM 跑通率而非模型能力), 方案真值 docs/eval-E5-baseline-ablation.md
§5 (任务集) / §7 (判定分层与反证夹具) / §9 (顺序与澄清轮控制) / §11 (阻断项)。

对外接口: 本文件是 pytest 收集面 —— TestTaskSet / TestSystems / TestGates /
TestBrokenFixtures / TestScriptedEndToEnd / TestItemsCompleteness /
TestThreeGates / TestScriptedSmoke 八个类, 无对外函数 API。

依赖与数据流: 输入 = evals.ablation 下的 harness (装载与跑批) / metrics (三门) /
broken (反证) / runner (放行判定) + items.yaml 与 systems/*.yaml;
产物只有 pytest 报告, 不写任何评测数据文件。

关键契约与不变量: 离线回放 —— 全部用例打在 ScriptedLLM 与本地快照上, 不接真实
模型、不打真实站点; 零跨实验 import —— 只 import 本实验内的件, 唯一共享件
evals/_data/ 纯数据字典不由本包直接引用; **等价性无断言覆盖** (该悬空见
equivalence/import_isolation.py:15),
本包不重复那层; 断言确定性 —— 跑批不传 seed 时保持 items.yaml 原序, 重复跑指纹一致。

陷阱与边界: scripted 模式的覆盖有结构性边界, 单测要如实写出来而不是绕开 ——
Δ1 (B0→B1) 与 sham/A2 的区分度在 scripted 下不可分辨, A1 只在 E5-D08 一题上可观测;
这些边界不能被写成"预期失败"来充数, 该验的是"已知的模式边界被如实披露";
repeat<3 会被 runner 判阻断项, 那是 scripted 冒烟不得冒充显著性结论的硬约束
(§11), 单测里既验得住也拦得住, 不属于"已知失败"。
"""
