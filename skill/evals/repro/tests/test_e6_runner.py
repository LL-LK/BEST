# -*- coding: utf-8 -*-
"""evals/repro/tests/test_e6_runner.py — E6 runner CLI 冒烟 (拆分件 3/3)。

覆盖 (docs/eval-E6-reproducibility.md §11):
  - ``--lane R0 --repeat 2 --selftest``: 反证夹具放行 + 四一致率地板线, 退出码 0;
  - ``--lane R0 --repeat 2 --score --json``: means 全 1.0, 退出码 0。

拆分缘由 (budget R2): E6 单测原单文件 743 净行 → foundation (输入面/统计) +
metrics (指标面) 两件后 metrics 仍 409 净行; 冒烟段独立成件, 三片都回
400 预算内。共享夹具构造落 support_e6.py (对账单点)。
"""
from __future__ import annotations

# 标准库: JSON (报告解析) / 环境变量 (子进程编码) / 子进程 (CLI 冒烟) /
#         sys (解释器路径) / 路径
import json
import os
import subprocess
import sys
from pathlib import Path

# 本地: 路径常量 (runner 入口与 skill 根)
from evals.repro.tests.support_e6 import _SKILL_ROOT, RUNNER  # noqa: E402

# ── 12. runner 冒烟 ──────────────────────────────────────────────────────

class TestRunnerSmoke:
    """runner: CLI 退出码 0 (反证夹具放行 + R0 实跑四一致率全 1.0)。"""

    @staticmethod
    def _run_cli(*extra: str) -> subprocess.CompletedProcess:
        """以子进程跑 run_e6.py (脚本直跑自挂 sys.path; UTF-8 输出防中文乱码)。"""
        return subprocess.run(   # 子进程而非同进程调 main(): 冒烟要验的正是"脚本直跑"这条路
            [sys.executable, str(RUNNER), *extra],   # sys.executable: 不假设 PATH 上有 python3
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(_SKILL_ROOT), env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=300,
        )

    def test_selftest_cli_exit_zero(self):
        """`--lane R0 --repeat 2 --selftest` 必须退出码 0 (metascore=1.0 才放行)。"""
        # repeat 取 2 够用: 冒烟验的是 CLI 通路, 样本量归正式跑批管
        proc = self._run_cli("--lane", "R0", "--repeat", "2", "--selftest")
        assert proc.returncode == 0, proc.stdout + proc.stderr   # 消息带两路输出: 只看退出码定位不到原因
        assert "metascore" in proc.stdout                      # 键在即证明自证真跑过, 缺了会静默通过

    def test_score_cli_exit_zero_and_means_one(self, tmp_path):
        """R0 实跑 + 计分: 退出码 0 且四一致率全 1.0 (地板线, 文档 §8.2 #3)。"""
        report_path = tmp_path / "score.json"   # 落 tmp_path: 报告是本次跑批的临时产物, 不进仓内
        # --json 必须真落盘: 只截 stdout 验不到"写文件"这条腿
        proc = self._run_cli("--lane", "R0", "--repeat", "2", "--score", "--json",
                             str(report_path))
        assert proc.returncode == 0, proc.stdout + proc.stderr   # 地板线: 任一致率 <1.0 即退出码 1
        report = json.loads(report_path.read_text(encoding="utf-8"))   # 回读文件而非截 stdout
        assert report["means"] == {"tsc": 1.0, "pac": 1.0, "rdc": 1.0, "fcc": 1.0}
        assert report["coverage"]["covered"] == 18   # 覆盖面也断言: 全 1.0 但只跑 1 个任务是假绿

    def test_unconnected_lane_is_not_exit_zero(self):
        """R1/R2/R3 未接模型时**必须**非 0 退出 (铁律 5 禁 fail-open)。

        历史缺陷: 这条分支原本 ``return 0`` —— 要一条根本没跑的 lane 却拿到
        退出码 0, CI 里「E6 通过」与「E6 压根没跑」长得一模一样。
        """
        for lane in ("R1", "R2", "R3"):
            proc = self._run_cli("--lane", lane)
            assert proc.returncode != 0, f"{lane} 未接模型却退出码 0: {proc.stdout}"
            assert "adapter_required" in proc.stdout      # 契约仍要打出来: 阻断不等于失声

    def test_allow_adapter_required_is_explicit_opt_in(self):
        """反向自证: 闸门不是「永远拦」—— 显式 --allow-adapter-required 可放行。"""
        proc = self._run_cli("--lane", "R1", "--allow-adapter-required")
        assert proc.returncode == 0, proc.stdout + proc.stderr   # 「仅探接口」语义由命令行显式表达
        assert "adapter_required" in proc.stdout

    def test_require_full_coverage_blocks_uncovered_tasks(self):
        """R0 覆盖 18/32: 开了 --require-full-coverage 即阻断, 不许拿 18 条的全 1.0 冒充 32 条。"""
        proc = self._run_cli("--lane", "R0", "--repeat", "2", "--score", "--require-full-coverage")
        assert proc.returncode != 0, f"14 条未覆盖却退出码 0: {proc.stdout}"
        assert "tasks_uncovered" in proc.stdout    # 阻断项要随分数同出, 不能只写在注释里

    def test_full_coverage_gate_is_opt_in(self):
        """反向自证: 不开闸门时 R0 仍照常通过 (离线自检不该被新门禁打红)。"""
        proc = self._run_cli("--lane", "R0", "--repeat", "2", "--score")
        assert proc.returncode == 0, proc.stdout + proc.stderr

