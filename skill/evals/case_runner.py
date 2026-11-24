# -*- coding: utf-8 -*-
"""evals.case_runner — [deprecated shim] 已迁移到 evals.case_executor (P0 命名整改)。

能力边界: 本文件只做兼容转发 (兄弟裸导入), 不含任何实现, 登记二期删除。
更名原因: "case_runner" 与 "eval_runner" 近义混淆 (一个判单条用例过不过,
一个汇总加权评分); 权威实现: evals/case_executor.py。
"""
# 本地: 行为用例执行件 (P1 抽离件; 本模块只做 CLI 装配面)
from case_executor import run_cases_eval  # noqa: F401

__all__ = ["run_cases_eval"]                                                              # 公开面只此一个符号: 其余从 case_executor 走
