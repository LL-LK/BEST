# -*- coding: utf-8 -*-
"""evals.equivalence.tests — 跨实验等价性单测包 (只做命名空间, 无可执行代码)。

职责: 把等价性断言聚成一个 pytest 包。它本身不判定任何东西, 判定逻辑全在
同目录的 ``test_equivalence.py``; 之所以要有这个 ``__init__``, 是为了让
``evals.equivalence`` 成为一个有明确包边界的单元, 跨实验 import 守卫才能
把它整体识别为"允许被依赖的守门件"而非普通实验目录。

所属实验: 不属于 E1–E6 任一实验编号, 它横向守护全部六个实验 ——
E2 (groundtruth)、E4 (robustness)、E6 (repro) 三个 transport 副本必须对
同一份快照给出逐字节相同的回包。对应方案见 docs/eval-E2-groundtruth.md
的等价性约定, 铁律 6 的机械落地。

对外接口: 无导出符号 (空包标记), 唯一的对外效果是让 ``pytest
evals/equivalence`` 能在包上下文中导入同目录的测试模块。

依赖与数据流: 输入是 ``evals/equivalence/snapshots/`` 与 ``fixtures/``
下的离线快照和夹具; 产物只有 pytest 的通过/失败结论, 不落盘报告。

关键契约与不变量: 守门件自身不受"零跨实验 import"约束 — 它必须 import
多个实验的 transport 才能比对它们, 这正是它作为等价性裁判的特权; 被守
的实验代码之间仍然零互相 import。等价性结论由本包内的断言固定, 不依赖
任何真实网络或模型调用 (全离线回放, rate_limit 归零)。

陷阱与边界: 这里加测试文件时不要顺手 import 被测实验之外的实验目录,
否则会把自己的守卫变成违规样本; 反过来, 本包也不该被任何实验 import,
一旦被依赖, 裁判与选手同队, 等价性断言就失去证据力。
"""
