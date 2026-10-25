#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ops/cloud_modelscope/run.py — [deprecated shim] 已迁移到 dispatch.py (P0 命名整改)。

能力边界: 本文件只做入口转发 (runpy 以 __main__ 执行权威实现), 不含任何
实现, 登记二期删除。更名原因: "run" 未说明跑的是什么 — 实际职责是云端
算力作业的规格合成与分发调度; 权威实现: ops/cloud_modelscope/dispatch.py。
"""
# 本地: dispatch 新模块再导出 (P0 兼容 Shim: 旧模块名保留, 只做转发)
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "dispatch.py"),
               run_name="__main__")
