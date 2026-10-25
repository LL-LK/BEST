#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ops/skill_cli.py — [deprecated shim] 已迁移到 ops/astro_best_cli.py (P0 命名整改)。

能力边界: 本文件只做入口转发 (runpy 以 __main__ 执行权威实现), 不含任何
实现, 登记二期删除。更名原因: "skill_cli" 是与 src/ 平级的通用名, 未说明
这是 astro-best 的本地运维 CLI; 权威实现: ops/astro_best_cli.py。
"""
# 本地: astro_best_cli 新入口再导出 (P0 兼容 Shim: 旧入口名保留, 只做转发)
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "astro_best_cli.py"),
               run_name="__main__")  # run_name 是关键: 让权威实现自己的 __main__ 守卫真的触发
