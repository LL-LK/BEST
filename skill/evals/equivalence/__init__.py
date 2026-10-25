# -*- coding: utf-8 -*-
"""evals.equivalence — 跨实验等价性断言 (防"同源功能多份实现"漂移)。

背景: 按"代码全自包含"纪律, 每个实验目录各带一份判定实现; 风险是复制件各自漂移,
对同一输入给出不同答案 (E2 §4.4 警告的"两套分数")。
本包用两类断言守住等价性:
  1. ``test_judgment_equivalence``: 各份判定实现 (行主键 ``row_key`` / 哨兵
     ``is_sentinel``) 对同一批输入必须给出**同一个答案**。本类继承的是原
     ``test_transport_equivalence`` 守的那条不变量 —— 2026-10-07「全盘删回放改实跑」
     裁定后 transport 与快照已删, 比对对象从传输实现换成判定口径
     (docs/REPLAY-RETIREMENT-CRITERIA.md §3.2 末行开下的处方), 判据实现在
     ``evals.equivalence.criteria``;
  2. ``test_sentinel_dictionary``: 各实验代码不得硬编码哨兵阈值, 必须读
     ``evals/_data/null_sentinel.yaml`` 单点 (静态扫描)。

白盒锚点: 用户 2026-09-28 裁决 (零跨实验 import + 等价性断言护航);
docs/eval-E2-groundtruth.md §4.4 (唯一允许共享的文件)。
"""
from __future__ import annotations

# 标准库: 路径
from pathlib import Path

EQUIV_DIR = Path(__file__).resolve().parent                                                         # 本包目录: 守卫的快照与夹具都在它下面
