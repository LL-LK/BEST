# -*- coding: utf-8 -*-
"""evals.repro.consistency — E6 四个一致率包 (TSC/PAC/RDC/FCC)。

四指标各占一个文件 (守单文件预算); 本包只做再导出与共同口径说明:
**全部以众数为参照并同时报 pairwise 均值** (防"五五开"分布被众数掩盖,
docs/eval-E6-reproducibility.md §5); 只判"是否一致", 不判"谁对"。
"""
from __future__ import annotations

# 本地: 四一致率再导出 (tsc/pac/rdc/fcc — 包面单点, 消费方只认此层)
from evals.repro.consistency.fcc import fcc
from evals.repro.consistency.pac import pac
from evals.repro.consistency.rdc import rdc
from evals.repro.consistency.tsc import tsc

__all__ = ["tsc", "pac", "rdc", "fcc"]                                                              # 四个一致率检测器是本包的公开面
