# -*- coding: utf-8 -*-
"""evals/semantics/tests — E3 单测 (预筛正反例 / 反证 metascore / 一致性自测 / runner 冒烟)。

职责: 守住 E3 语义与幻觉实验的三条不变量 — L0 预筛对坏回答不能漏检 (反证
  metascore 恒为 1.00)、对好回答不能误报 (否定用法与哨兵声明必须豁免)、
  人工盲评之前 runner 已能给出可复核的 L0 摘要。
所属实验: E3 科学语义区分与幻觉抑制 (36 题 7 轴), 方案真值是
  docs/eval-E3-semantics.md (§7.3 预筛 / §9 反证 / §10 盲评) 与
  evals/semantics/rubric.yaml (§3 正则与容差的唯一权威)。
对外接口: 本包只导出测试符号供 pytest 收集 — test_e3.py 内 TestStaticAsLc /
  TestSentinelMisuse / TestUnsourcedNumbers / TestQualifierCoverage /
  TestUnsupportedClaims / TestPrescreenIntegration / TestBrokenSelftest /
  TestAgreement / TestRunnerSmoke / TestCoverageGate 十个类 (预筛的一项正反例或
  runner 冒烟), 另 test_e3_twozero.py 内 TestTwoZeroCatalogsItemDiscriminates /
  TestTwoZeroFixtureIsTraceable / TestTwoZeroProbeIsInsideJplusRegion 三个类
  (E3-F06 那道题的区分度实证 / 逐字段溯源 / 探点天区门, 2026-10-05 按内聚拆出,
  理由见该文件模块头)。依赖与数据流: 输入 = 两个测试文件内联的最小 fixture
  (_FIXTURES, 数值与 items.yaml fx_ps1_pair / fx_gaia_mixed 对齐) 与
  evals.semantics.prescreen / agreement / broken / runner 的公开函数;
  产物 = pytest 断言结果, 不落盘。
关键契约与不变量: 纯离线, 不发网络请求、不调大模型, 也不读真实站点 — 全部
  在回放数据上判定; 零跨实验 import, 只允许 import evals.semantics.* 与
  evals._data 的纯数据字典; 重复运行必须给出同一结果 (metascore 恒 1.00 即
  预筛规则没被改动悄悄放松), 跨实验等价性由 evals/equivalence/ 的断言守护。
陷阱与边界: 反证夹具的价值全在 "must_flag 必须全中" — 若某天为了降误报
  放宽了某条判据, 这里会先红, 所以宁可把期望值调严也不能让夹具变绿。
"""
