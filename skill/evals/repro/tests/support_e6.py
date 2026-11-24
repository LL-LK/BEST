# -*- coding: utf-8 -*-
"""evals/repro/tests/support_e6.py — E6 单测共享夹具 (bootstrap/常量/构造)。

存在理由: test_e6 原单文件 743 净行超 400 预算 (budget R2), 按测试域拆成
test_e6_foundation (输入面/统计) + test_e6_metrics (指标面) 两件; 两件共用
的 bootstrap/路径常量/最小现场/篡改手段集中在此 — 共享逻辑只有一份,
不因拆分漂移 (对账口径以本文件为单点)。
"""
from __future__ import annotations

# 标准库: 深拷贝 (清单变体) / JSON / 缓存 (指纹只算一次) / 路径 / sys (bootstrap)
import copy
import json
import sys
from functools import lru_cache
from pathlib import Path

# 本地: sys.path 自挂 — evals/repro/{manifest,usability}.py 含 ``from paths import``
# 兄弟裸导入 (需 evals/ 在路径上), 与 run_e6.py 的 bootstrap 同口径; pytest 的
# prepend 导入模式恰好也会插入 evals/, 这里显式挂上以保证任何导入模式下都可用
_SKILL_ROOT = Path(__file__).resolve().parents[3]   # 仓根 astro-best/ (上溯三级)
_EVALS_DIR = _SKILL_ROOT / "evals"                 # 兄弟裸导入的宿主目录
for _anchor in (str(_EVALS_DIR), str(_SKILL_ROOT)):                                      # 两个锚点都要试: 评测可能从仓根也可能从 evals/ 被调用
    if _anchor not in sys.path:          # 幂等: pytest 也会插 evals/, 重挂会打乱优先级
        sys.path.insert(0, _anchor)

# 本地: 被测模块 (共享夹具只碰这三个入口: 清单指纹/归一/trace 写入)
from evals.repro.manifest import build_manifest, save_manifest, sha256_file  # noqa: E402
from evals.repro.normalize import norm_args, norm_card  # noqa: E402
from evals.repro.trace import TraceWriter  # noqa: E402

REPRO_DIR = Path(__file__).resolve().parents[1]  # evals/repro/ (本实验根)
FIXTURES_DIR = REPRO_DIR / "fixtures"          # 回放快照目录: 离线跑的"数据源"
RUNNER = REPRO_DIR / "run_e6.py"               # 被驱动的 CLI, 单测以子进程调它
TOOLS_SCHEMA = _SKILL_ROOT / "references" / "tools.schema.json"   # 参数面权威

# 一致率/归因共用的最小现场 (与 broken/ 基线同参: scr_galah 300″ 锥搜)
_BASE_ARGS = {"ra": 180.0, "dec": 30.0, "radius_arcsec": 300.0,
              "catalog": "scr_galah", "columns": ["ra", "dec"]}
_BASE_CARD = {"kind": "rowset", "key_numbers": [{"field": "row_count", "value": 12}],
              "key_entities": ["scr_galah", "best://scr_galah/sqlid/s9001"],
              "caveats": ["合成测光非实测"]}
_BASE_HASH = "sha256:" + "b" * 64   # 固定字面量: 跨用例同一 hash, 夹具之间才可比
# 众数调用必须是**归一后**形态 (与 run_e6._score 的 mode_calls 同口径: 列名已排序)
_MODE_CALLS = [norm_args(_BASE_ARGS)]                                                               # 基准调用样本: 归一函数的回归输入
_MODE_CARD = norm_card(_BASE_CARD)   # 归一一次: 要与 _score 里同一函数的产物比, 不各归一各的



def _manifest_kwargs() -> dict:
    """合法八项清单的构造参数 (R0 离线口径: 无模型, 回放快照, 温度钉 0.0)。"""
    schema_fp = sha256_file(TOOLS_SCHEMA)   # 现算: schema 一改就跟着变, 不硬编码哈希
    return {"lane": "R0", "repeat": 2, "canary_before": "bestfp:sha256:" + "a" * 64,
            "canary_after": "bestfp:sha256:" + "a" * 64, "drift_state": "STABLE",
            "model_id": "none-R0", "provider": "none", "endpoint": "",
            "prompt_text": "", "prompt_template_id": "r0-fixed-sequence",
            "tools_schema_fp": schema_fp, "exposed_schema_fp": schema_fp,
            "snapshot_id": "replay-fixtures", "snapshot_manifest_fp": "",
            "temperature": 0.0, "seed_requested": None, "seed_honored": False,
            "rate_limit_seconds": 0.0}


@lru_cache(maxsize=1)
def _valid_manifest() -> dict:
    """合法清单 (缓存 — skill 指纹全树扫描约 0.3s, 不该每个用例重算)。"""
    return build_manifest(**_manifest_kwargs())


def _mutated(**changes) -> dict:
    """在合法清单副本上按 "项.字段" 改值 (无点号 = 整项替换; 不污染缓存)。

    Args:
        **changes: 键为 ``项`` 或 ``项.字段`` 的篡改指令, 值为替换后的新值;
            键名写错不会报错 (dict 直写), 因此用例须只写清单里真实存在的项。

    Returns:
        深拷贝后的清单 dict; 缓存里的 :func:`_valid_manifest` 始终保持合法形态。
    """
    manifest = copy.deepcopy(_valid_manifest())      # 深拷贝: 缓存件是全局单例, 原地改会污染后续用例
    for dotted, value in changes.items():   # "项.字段" 只支持一层: 更深的路径本夹具不解析
        if "." in dotted:
            item, field = dotted.split(".", 1)   # 限量 1 次: 键名本身含点号时按第一段切
            manifest[item][field] = value       # 改字段: 模拟"清单某项某字段被改坏"
        else:
            manifest[dotted] = value             # 整项替换: 缺项 / 错项这类更粗的扰动
    return manifest


def _write_manifest_file(manifest: dict, tmp_dir: Path) -> Path:
    """把清单落到临时目录并回传路径 (绑定面用例会拿它当 --manifest 的入参)。

    刻意走 save_manifest 而不是手写 JSON: 绑定用例要验的是"跑批认的是**冻结时
    落盘的那份**", 用另一条写入路径就绕开了落盘即冻结这件事本身。
    """
    path = tmp_dir / "manifest-test.json"
    save_manifest(manifest, path)      # 先校验后写: 非法清单抛错, 与真实冻结同一条路
    return path


def _write_trace(path: Path) -> list[dict]:
    """写一条最小合法 trace (五类事件: run_start/tool_call/tool_result/final_answer/run_end)。"""
    with TraceWriter(path, run_id="run-001", task_id="REPRO-04") as writer:
        return [
            writer.emit("run_start", {"manifest": {"skill_fp": "sha256:" + "0" * 64}}, layer="harness"),
            writer.emit("tool_call", {"tool": "cone_search", "args": {"ra": 180.0},
                                      "args_norm": {"ra": 180.0}, "args_fp": "sha256:" + "1" * 64},
                        layer="tool"),
            writer.emit("tool_result", {"envelope_fp": "sha256:" + "2" * 64,
                                        "status": {"ok": True, "error_code": None},
                                        "cost": {"http_requests": 2, "elapsed_s": 0.5},
                                        "provenance": {"data_hash": _BASE_HASH,
                                                       "stable_uri": "best://ps1/cone"}},
                        layer="tool", parent_seq=1),
            writer.emit("final_answer", {"answer_fp": "sha256:" + "3" * 64,
                                         "conclusion_card": dict(_BASE_CARD)},
                        layer="harness", parent_seq=0),
            writer.emit("run_end", {"total_requests": 2, "total_elapsed_s": 0.5,
                                    "outcome": "success"}),
        ]


def _attr_run(**override) -> dict:
    """一次运行的最小记录 (默认: 工具/参数与众数一致, 结果 ok, 无重试)。

    Args:
        **override: 顶层键覆盖, 如 ``card=`` / ``retries=[...]`` / ``results=[...]``;
            每次调用只改一处, 才能把归因结论归到单个漂移因上。

    Returns:
        ``{"tool_calls", "results", "card", "retries"}`` 四键 run 记录,
        与 ``evals.repro.attribution.attribute_lane`` 的输入同形。
    """
    run = {"tool_calls": [{"tool": "cone_search", "args": dict(_BASE_ARGS)}],
           "results": [{"ok": True, "error_code": None, "data_hash": _BASE_HASH}],
           "card": dict(_BASE_CARD), "retries": []}
    run.update(override)   # 末尾统一覆盖: override 优先级高于上面的基线字面量
    return run


def _call_run(**override) -> list[dict]:
    """一次运行的调用参数列表 (PAC 输入; 可改一个字段造漂移)。

    Args:
        **override: 覆盖 ``_BASE_ARGS`` 的参数, 如 ``radius_arcsec=5.0``;
            未给的键沿用基线, 拼错的键会被 ``dict()`` 静默丢弃, 用例须自查。

    Returns:
        单元素参数字典列表 —— PAC 的输入形状是"每次运行一个参数列表",
        累积 N 次运行才构成可取众数的样本。
    """
    return [dict(_BASE_ARGS, **override)]   # 单元素: 漂移夹具只造一次运行, 众数由其余运行给出


def _cone(**override) -> dict:
    """一次 cone_search 调用记录 (归因输入; 可改一个字段造漂移)。

    Args:
        **override: 覆盖 ``_BASE_ARGS`` 的参数; 与 :func:`_call_run` 同源,
            差别只在外层多包了 ``tool`` 与 ``args`` 两键。

    Returns:
        一条调用的 dict 形态, 供 ``attribute_lane`` 的 ``tool_calls`` 列表逐条消费。
    """
    return {"tool": "cone_search", "args": dict(_BASE_ARGS, **override)}   # tool 写死: 只测同工具的漂移


def _drop_result(events: list) -> None:
    """篡改手段: 删掉 tool_result 事件 (调用与结果不再配对)。

    Args:
        events: 事件列表, **原地改写** (切片赋值), 调用方无须接收返回值。

    Returns:
        None。改完的列表应被 ``evals.repro.trace.validate_trace`` 判为不完整。
    """
    events[:] = [e for e in events if e["type"] != "tool_result"]   # 切片赋值: 原地生效


def _drop_final(events: list) -> None:
    """篡改手段: 删掉 final_answer 事件 (结论丢失)。

    Args:
        events: 事件列表, **原地改写** (切片赋值), 键为 ``type`` 的事件名。

    Returns:
        None。调用记录仍完整, 但结论缺失, 校验器仍须据"缺 final_answer"报错。
    """
    events[:] = [e for e in events if e["type"] != "final_answer"]   # 原地生效, 不重排其余 seq


def _break_seq(events: list) -> None:
    """篡改手段: 把第二个事件的 seq 改成 7 (断号)。

    Args:
        events: 事件列表, 原地改写索引 1 的 ``seq`` 字段; 长度须 >= 2。

    Returns:
        None。首事件 seq=0 不动, 于是 0 -> 7 之间出现断号。
    """
    events[1]["seq"] = 7   # 改索引 1: 让断号出现又不牵动首事件


def _drop_header(events: list) -> None:
    """篡改手段: 删掉第二个事件的 type 头字段。

    Args:
        events: 事件列表, 原地对索引 1 执行 ``pop("type")``; 长度须 >= 2。

    Returns:
        None。事件仍在但丢了类型头, 记录器本该强制写该字段, 缺了即须被抓。
    """
    events[1].pop("type")   # pop 而非置空: 逼校验器走"键缺失"那条分支

