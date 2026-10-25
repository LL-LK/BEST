# -*- coding: utf-8 -*-
"""evals.robustness.tests — E4 单测包 (判定器自证 + 注入器语义 + 护栏探针)。

职责: 守住 E4 的"判定器本身"这一层 —— 单测不测被测客户端, 只测判定器、注入器
与回放底座自身是否成立; 这类自证失败意味着评分口径不可信, 比被测对象失败更严重。

所属实验: E4 鲁棒与安全 (68 条标注 = Tier W 33 / Tier P 35, Tier W 主线 15 条
程序判定全过), 方案真值 docs/eval-E4-robustness-safety.md。单测覆盖四块:
权重和纪律 (M_WEIGHTS 必须恰为 1.00)、反证夹具 metascore、注入器故障窗口语义、
回放路由与护栏探针入口拦截。

对外接口: 本文件是 pytest 收集面 (TestWeights / TestBrokenSelftest / TestInjectors
/ TestReplay / TestGuards / TestMasqueradeDetection 六个类), 无对外函数 API。

依赖与数据流: 输入 = 被测的 evals.robustness.{graders,broken,injectors,replay,
guards} 与 pytest 本身; 产物只有测试报告, 不落任何评测数据文件。

关键契约与不变量: 离线回放 —— 测试全程打本地替身, 不接真实模型、不打真实站点;
零跨实验 import —— 只 import 本实验内的件, 唯一共享件 evals/_data/ 纯数据字典
不由本包直接引用; 等价性由 evals/equivalence 断言守护 (本包不重复那层检查);
断言必须确定性 —— 所有夹具都是固定值, 不含随机与时间依赖, 同一提交重复跑结论一致。

陷阱与边界: 反证夹具必须"全中才算有效" —— 漏抓一条即判定器失效, 所以这里用
metascore == 1.0 硬断言而不是"多数通过"; 注入器用例刻意只覆盖 Tier W 主线 15 条
覆盖到的那几类故障语义, 复合变体 (second_round) 的叠加效应属于跑批面, 不在这里
断言, 也不写成"预期失败"来充数。
"""
