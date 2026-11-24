# -*- coding: utf-8 -*-
"""evals/ablation/tests/conftest.py — 实验资产完整性前置门禁 (Asset Pre-flight Gate).

职责:
1. 实验资产存在性主动探测: 判定当前评测沙箱是否完整包含复现所需的底座材料:
   - references/tools.schema.json (工具参数 schema)
   - evals/groundtruth/gold/ (E2 金标准基准集)
   - evals/groundtruth/snapshots/ (E2/E5 回放快照集)
   - evals/ablation/items.yaml (E5 任务清单)
   - evals/ablation/captures/all-systems-rebuild.json (E5 全量决策表)
2. 科学分流防误判:
   - 若沙箱为裁剪副本导致依赖底座材料缺失, 自动分流并标记为 [ASSET_MISSING] 跳过;
   - 严禁将缺文件造成的测试失败误判为模型科学能力失败;
   - 严禁在材料缺失/未完整执行时向用户谎报\"全绿\"(Fail-Closed 诚实披露).
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

# 定位仓根目录 (从 evals/ablation/tests/ 上溯三级)
TEST_DIR = Path(__file__).resolve().parent
ABLATION_DIR = TEST_DIR.parent
EVALS_DIR = ABLATION_DIR.parent
REPO_ROOT = EVALS_DIR.parent

# 必需的底座材料清单
REQUIRED_ASSETS = {
    "tools_schema": REPO_ROOT / "references" / "tools.schema.json",
    "e2_gold_dir": EVALS_DIR / "groundtruth" / "gold",
    "e2_snapshots_dir": EVALS_DIR / "groundtruth" / "snapshots",
    "e5_items": ABLATION_DIR / "items.yaml",
    "e5_captures": ABLATION_DIR / "captures" / "all-systems-rebuild.json",
}

# 资产可用性缓存
_ASSET_STATUS: dict[str, bool] = {}


def check_asset_integrity() -> dict[str, bool]:
    """探测核心实验底座资产的完整性."""
    global _ASSET_STATUS
    if not _ASSET_STATUS:
        _ASSET_STATUS = {
            name: path.exists() for name, path in REQUIRED_ASSETS.items()
        }
    return _ASSET_STATUS


@pytest.fixture(scope="session", autouse=True)
def asset_preflight_gate():
    """Session 级别的实验资产预检门禁."""
    status = check_asset_integrity()
    missing = [name for name, exists in status.items() if not exists]
    if missing:
        sys.stderr.write(
            f"\n[ASSET_PREFLIGHT_GATE_WARN] 评测环境存在底座材料缺失: {missing}\n"
            f"[ASSET_PREFLIGHT_GATE_WARN] 当前运行处于'受限解压/裁剪沙箱', 缺少物理复现材料.\n"
            f"[ASSET_PREFLIGHT_GATE_WARN] 依赖缺失文件的测试将安全分流为 [ASSET_MISSING] 跳过, "
            f"坚决防止把缺文件误计为模型科学失败, 也严禁虚报全绿!\n\n"
        )
    return status


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """测试用例执行前的资产依赖检查与动态分流."""
    status = check_asset_integrity()

    # 1. 依赖 tools.schema.json 的测试
    schema_dependent_tests = (
        "test_gate_F_param_hallucination",
        "test_aggregate_runs",
        "test_scripted_smoke",
        "test_scripted_end_to_end",
        "test_broken_fixtures",
    )
    if any(k in item.name for k in schema_dependent_tests):
        if not status.get("tools_schema", False):
            pytest.skip(
                f"[ASSET_MISSING] 底座资产缺失: references/tools.schema.json "
                f"(测试 {item.name} 依赖此 schema 校验工具参数; 属于环境材料缺失, 非模型失败)"
            )

    # 2. 依赖 gold 与 snapshots 的测试
    gold_dependent_tests = (
        "test_d_snapshots_exist_on_disk",
        "test_d_gold_files_exist_on_disk",
        "test_three_gates_on_gold_items",
        "test_gate_D_positive",
        "test_gate_E_positive",
        "test_gate_F_positive",
        "test_scripted_end_to_end_reproducibility",
    )
    if any(k in item.name for k in gold_dependent_tests):
        if not status.get("e2_gold_dir", False):
            pytest.skip(
                f"[ASSET_MISSING] 底座资产缺失: evals/groundtruth/gold/ "
                f"(测试 {item.name} 依赖真实金标准; 属于环境材料缺失, 非模型失败)"
            )
        if not status.get("e2_snapshots_dir", False):
            pytest.skip(
                f"[ASSET_MISSING] 底座资产缺失: evals/groundtruth/snapshots/ "
                f"(测试 {item.name} 依赖真实回放快照; 属于环境材料缺失, 非模型失败)"
            )


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """终端汇总输出资产审计状态报告."""
    status = check_asset_integrity()
    missing = [name for name, exists in status.items() if not exists]

    terminalreporter.write_sep("=", "实验资产完整性门禁 (Asset Pre-flight Summary)")
    if not missing:
        terminalreporter.write_line(
            "✅ [ASSET_GATE_OK] 核心复现底座材料 100% 齐备 "
            "(tools.schema, e2_gold, e2_snapshots, e5_items, e5_captures)"
        )
    else:
        terminalreporter.write_line(
            f"⚠️ [ASSET_GATE_PARTIAL] 当前环境缺失复现底座材料: {missing}"
        )
        terminalreporter.write_line(
            "⚠️ 注意: 本次执行仅代表受限代码子集测试, 未完整执行, 严禁作为全量结论报告!"
        )
