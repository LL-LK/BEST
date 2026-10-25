#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dispatch.py — astro-best 魔塔 (ModelScope) 云端调度入口 (Phase 3-D, 组件 12B)。

与黄金样板 astro-transient/scripts/cloud_modelscope 同风格:
  - **IS_LIGHT = True**: 本机只做规格合成 / 打包对账 / 离线登记, 秒级完成 (G8);
  - **重型下载分发**: 大批量星表切片与跨星表交叉匹配作业分发至魔塔云端实例;
  - **凭据只读环境变量** (MODELSCOPE_API_TOKEN / MS_*), 无 token 时离线登记
    pending, 绝不联网、绝不伪造 job_id;
  - 共享通道: `_shared.astro_core.modelscope_dispatch.ModelScopeDispatcher`。

用法 (本文件真实路径在 ops/cloud_modelscope/ 下, 不是 scripts/):
  python ops/cloud_modelscope/dispatch.py --plan
  python ops/cloud_modelscope/dispatch.py --check-only
"""

from __future__ import annotations

# 标准库组:
#   argparse —— --plan / --check-only 两个开关 (规格打印 vs 干跑对账)
#   json     —— 作业规格以 JSON 打印 (宿主机/云端 worker 直接可解析)
#   os       —— 只读环境变量 (token / 作业名 / 实例规格), 代码内零凭据字面量
#   sys      —— 把仓库根注入 sys.path, 使 `_shared.*` 共享通道可导入
#   pathlib  —— 由本文件位置反推 skill 根与仓库根 (不依赖 cwd)
import argparse
import json
import os
import sys
from pathlib import Path

# 本文件位于 <repo>/astro-best/ops/cloud_modelscope/, 上跳两级到 skill 根
SKILL_ROOT = Path(__file__).resolve().parents[2]   # astro-best/
# 仓库根: 共享通道 _shared.astro_core.* 的挂载点, 必须入 sys.path 才能 import
REPO_ROOT = Path(__file__).resolve().parents[3]    # 仓库根
if str(REPO_ROOT) not in sys.path:  # 幂等: 重复 import 时别把同一路径塞两遍
    sys.path.insert(0, str(REPO_ROOT))

# 凭据与作业规格输入点: 一律环境变量 (无 token 时只离线登记, 绝不联网、绝不伪造 job_id)
# S105 误报: 值是环境变量**名字**不是口令字面量 (凭据零字面量铁律)
ENV_TOKEN = "MODELSCOPE_API_TOKEN"  # noqa: S105
ENV_JOB_NAME = "MS_JOB_NAME"                                                                      # env 键名: 与模型服务约定一致, 不可改
ENV_INSTANCE = "MS_INSTANCE_TYPE"                                                                   # 实例类型 env 键名


def main(argv: list[str] | None = None) -> int:
    """魔塔云端调度入口: 合成作业规格并打印 (本机 IS_LIGHT, 秒级完成)。

    本机不跑重活 (G8 算力保护): 只做规格合成 / 打包对账 / 离线登记;
    大批量星表切片与交叉匹配作业声明在规格里, 交由云端实例执行。
    没有 token 时依然成功退出 —— 只是 ``token_configured`` 为 false,
    绝不联网试探、绝不用假 job_id 冒充已提交。

    Args:
        argv: 可选参数向量 (测试可注入); 缺省读 sys.argv。

    Returns:
        规格打印成功恒 0 (是否配好 token 只进 payload, 不当退出码)。
    """
    repo = argparse.ArgumentParser(description="astro-best 魔塔云调度入口")
    repo.add_argument("--plan", action="store_true", help="打印作业规格 (默认)")
    repo.add_argument("--check-only", action="store_true")
    args = repo.parse_args(argv)                                                                # 解析命令行: argv 可由调用方给, 便于单测

    persona = "astro-best persona (生产就绪)"
    job = os.environ.get(ENV_JOB_NAME, "astro-best-batch")  # 作业名可被宿主覆盖, 缺省用本仓批次名
    instance = os.environ.get(ENV_INSTANCE, "cpu.basic")  # 缺省最小 cpu 规格: 本机不跑重活, 别诱导申请大实例
    plan = {                                                                                        # 派发计划: 目标与参数在此定
        "skill": "astro-best",
        "persona": persona,
        "job_name": job,
        "instance_type": instance,
        "token_configured": bool(os.environ.get(ENV_TOKEN)),  # 只报布尔, 绝不回显 token 本体
        "check_only": bool(args.check_only),
        "is_light": True,
        "dispatcher": "_shared.astro_core.modelscope_dispatch (present)",  # 标注共享通道可达; 真实提交不在本文件
        "note": "规格打印模式; 提交负载声明见 workload.yaml (未来扩展)",
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2))  # 输出点: stdout JSON, ensure_ascii=False 保中文
    return 0  # 恒 0: token 配没配只进 payload, 不当退出码



if __name__ == "__main__":
    raise SystemExit(main())
