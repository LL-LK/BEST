# -*- coding: utf-8 -*-
"""evals.paths — 评测层的路径与 YAML 装载中立载体。

能力边界: 只提供"评测输入在哪"与"怎么读它们" —— skill 根 / evals 目录 / src 根,
以及 YAML 装载。抽成中立模块的理由: eval_runner (汇总评分) / case_executor (用例执行)
/probes (探针) 三方都要用这两样, 任何两方互相导入都会形成环; 放中立载体后三方
单向依赖本模块。

白盒锚点: docs/architecture/file-size-budget.md §3.1 (eval_runner 拆分的配套产物)。
"""
from __future__ import annotations

# 标准库: YAML 解析 (评分量规 / 场景表 / 用例夹具 / 契约)
from pathlib import Path
from typing import Any

import yaml

EVALS_DIR = Path(__file__).resolve().parent                                              # evals 目录锚点: 全仓 evals 下的相对路径都从它算
SKILL_DIR = EVALS_DIR.parent                                                                # skill 根: 跨实验引用要出 evals/ 时用得上
SRC_DIR = SKILL_DIR  # src/ 平铺后包根即 skill 根


def load_yaml_file(path: Path) -> dict[str, Any]:
    """读一个 YAML 文件并返回 dict; 不存在/不可解析时返回空 dict。

    空 dict 是"输入缺失"的显式信号: 调用方据此判 FAIL 而不是拿默认值冒充
    (EVAL-01: 目标缺失一律 FAIL, 不出现"文件不存在即过")。
    """
    if not path.is_file():                                                                        # 文件不存在即视为不在清单内, 不静默补默认值
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}

