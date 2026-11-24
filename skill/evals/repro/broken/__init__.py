# -*- coding: utf-8 -*-
"""evals.repro.broken — E6 反证夹具 (6 类已知扰动, 检测器必须全部报不一致)。

纪律 (沿用本仓 evals/ 约定 — 判定器必须先证明自己有效): 每个检测器
(TSC/PAC/RDC/FCC 比对器) 配"已知坏样本"; 坏样本没被报不一致 = 检测器
是摆设 → 该检测器 FAIL → E6 FAIL (docs/eval-E6-reproducibility.md §9;
selftest_required_metascore = 1.0)。

6 类扰动 (文档 §9 表):
  BF-1 半径 300″ → 600″        → PAC 抓
  BF-2 表 scr_galah → xpsp     → PAC (参数) + FCC (实体) 抓
  BF-3 单位错 5 角分当 5 角秒   → PAC 抓
  BF-4 结果删一行              → RDC (L2 集合) 抓
  BF-5 EMPTY 说成 ERROR        → FCC (kind) + U2 抓
  BF-6 结论数值小数点改一位    → FCC (key_numbers) 抓
"""
from __future__ import annotations

# 标准库: 路径 (夹具落盘)
from pathlib import Path

# 本地: 四一致率 + 参数/结论卡归一 + U2 (BF-5 的第二检测通道)
from evals.repro.consistency import fcc, pac, rdc, tsc
from evals.repro.normalize import norm_args, norm_card
from evals.repro.usability import u2_error_operability

# 基线运行 (N=5 全一致) 与各扰动单跑 (只改一个事实)
_BASE_CALLS = [[{"tool": "cone_search",
                 "args": {"ra": 180.0, "dec": 30.0, "radius_arcsec": 300.0,
                          "catalog": "scr_galah", "columns": ["ra", "dec"]}}] for _ in range(5)]
_BASE_CARD = {"kind": "rowset", "key_numbers": [{"field": "row_count", "value": 12}],
              "key_entities": ["scr_galah", "best://scr_galah/cone"],
              "caveats": ["合成测光非实测"]}


def _clone_calls(radius: float = None, catalog: str = None) -> list[dict]:
    """基线调用的单跑副本 (可改半径/表 — 只改一个事实)。"""
    args = {"ra": 180.0, "dec": 30.0, "radius_arcsec": 300.0,
            "catalog": "scr_galah", "columns": ["ra", "dec"]}
    if radius is not None:    # None = "不改": 0.0 本身是合法扰动值, 不能按真值判
        args["radius_arcsec"] = radius
    if catalog is not None:  # 同理: 空串也是扰动手段之一, 一样不能用真值判
        args["catalog"] = catalog
    return [{"tool": "cone_search", "args": args}]


def _base_runs_with(perturbed_call: list[dict], card: dict = None) -> tuple[list, list]:
    """构造"4 次基线 + 1 次扰动"的运行集 (返回 PAC/RDC/FCC 两个输入)。"""
    runs = [{"tool_calls": [dict(c) for c in _clone_calls()],
             "card": dict(_BASE_CARD)} for _ in range(4)]
    runs.append({"tool_calls": perturbed_call, "card": card or dict(_BASE_CARD)})
    return [r["tool_calls"] for r in runs], [r["card"] for r in runs]


FIXTURES: dict[str, dict] = {}   # 装饰器往这里登记; 插入序即报告里的展示序


def _register(fixture_id: str, perturbation: str, expect_caught_by: str):
    """装饰器: 登记一条反证夹具 (id/扰动说明/期望捕获器)。"""                                                # 只覆盖与金标准不同的维度: 每个反证只写一处差异, 归因才指得准
    def wrap(fn):
        """故障剧本的传输层包装 (把注入语义挂到 get/post 替身上)。"""
        FIXTURES[fixture_id] = {"id": fixture_id, "perturbation": perturbation,
                                "expect_caught_by": expect_caught_by, "detector": fn}
        return fn
    return wrap


@_register("BF-1", "半径 300 角秒 -> 600 角秒", "PAC")
def _bf1() -> bool:
    """BF-1: 半径漂移必须被 PAC 判不一致 (call 级)。"""
    calls, _ = _base_runs_with(_clone_calls(radius=600.0))   # 4 基线 + 1 扰动: 众数仍是基线
    result = pac([[norm_args(c["args"]) for c in run] for run in calls])
    return result["pac_call"] < 1.0   # <1.0 即"报出了不一致", 恰是反证要的结论


@_register("BF-2", "表 scr_galah -> xpsp", "PAC + FCC(key_entities)")
def _bf2() -> bool:
    """BF-2: 表漂移必须被 PAC 与 FCC(实体) 双抓。"""
    calls, cards = _base_runs_with(_clone_calls(catalog="xpsp"),
                                   {**_BASE_CARD, "key_entities": ["xpsp", "best://xpsp/cone"]})
    pac_hit = pac([[norm_args(c["args"]) for c in run] for run in calls])["pac_call"] < 1.0
    fcc_hit = fcc([{"card": c} for c in cards])["fcc"] < 1.0   # 实体串也变了 ⇒ 众数卡与基线不同
    return pac_hit and fcc_hit   # 与: 任一通道漏抓, 这条夹具就算失败


@_register("BF-3", "单位错: 5 角分当 5 角秒 (300 -> 5)", "PAC")
def _bf3() -> bool:
    """BF-3: 单位错 (300″ → 5″) 必须被 PAC 抓 (半径归一后不等)。"""
    calls, _ = _base_runs_with(_clone_calls(radius=5.0))                              # 只改半径一处: 单位错必须与其他参数无关, 否则测到的可能是别的漂移
    result = pac([[norm_args(c["args"]) for c in run] for run in calls])
    return result["pac_call"] < 1.0


@_register("BF-4", "结果删一行", "RDC(L2 行集 Jaccard)")
def _bf4() -> bool:
    """BF-4: 删一行必须被 RDC L2 抓 (行集集合不等)。"""
    runs = [{"data_hash": "sha256:" + "a" * 64, "row_keys": {f"K{i}" for i in range(12)},
             "key_values": {"n": 12}} for _ in range(4)]
    runs.append({"data_hash": "sha256:" + "b" * 64, "row_keys": {f"K{i}" for i in range(11)},
                 "key_values": {"n": 11}})
    return rdc(runs, lane="R1")["l2"] < 1.0   # lane 写死 R1: 行集判据按取数门口径分档


@_register("BF-5", "把 EMPTY 说成 ERROR / 把 ERROR 说成 EMPTY", "FCC(kind) + U2")
def _bf5() -> bool:
    """BF-5: 结论类别翻转 (rowset→refusal) 必须被 FCC kind 抓。"""
    _, cards = _base_runs_with(_clone_calls(), {**_BASE_CARD, "kind": "refusal"})
    fcc_hit = fcc([{"card": c} for c in cards])["fcc"] < 1.0   # kind 翻转 ⇒ 众数卡不一致
    u2_hit = u2_error_operability([{"outcome": "fail", "answer_text": "没有数据"}])["u2"] < 1.0
    return fcc_hit and u2_hit   # 第二通道: FCC 漏抓时 U2 仍须判出"不可操作"


@_register("BF-6", "结论数值小数点改一位", "FCC(key_numbers)")
def _bf6() -> bool:
    """BF-6: 结论数值改一位 (12 → 13) 必须被 FCC key_numbers 抓。"""
    _, cards = _base_runs_with(                                                # 只改 key_numbers 一项: 结论卡其余子项保持不变, 才能定位到数值子项
        _clone_calls(), {**_BASE_CARD, "key_numbers": [{"field": "row_count", "value": 13}]})  # 结果逐夹具攒: metascore 的分子分母都从这一份出
    result = fcc([{"card": c} for c in cards])                                            # 逐夹具跑: 注册表新增一条就自动获得同等自证覆盖, 不会漏网
    return result["fcc"] < 1.0 and "key_numbers" in result["sub_item_failures"]      # 可覆盖金标准: 有些反证要换 gold 才能构造, 不覆盖就构造不出来


# TSC 也需一条反证 (文档 §9 的 PAC/RDC/FCC 已覆盖; TSC 的序列敏感性由
# BF-2 的表漂移间接覆盖 — 工具序列不变时 TSC 本就不该报, 这是设计而非漏洞)
def tsc_order_sensitivity_check() -> bool:
    """TSC 反证: 同集合反序 (cone_search→resolve_name) 必须判不一致。"""
    runs = [["cone_search", "resolve_name"]] * 4 + [["resolve_name", "cone_search"]]
    return tsc(runs)["tsc_strict"] < 1.0   # 用 tsc_strict: 集合相同而次序不同, 宽松档本就不该报


# ── 第二组: trace 完整性扰动 (任务书六类; 检测器 = trace.validate_trace) ──
# 文档 §9 的六类扰动针对"一致率比对器"; 本组针对"trace 记录器本身" —
# 记录器若把坏记录当完整记录, 四一致率全是无源之水 (文档 §8.2 #6/#7)。


def _write_events(tmp_path, events: list[dict]) -> Path:
    """把事件列表写成 JSONL (供 validate_trace 消费的一次性夹具)。"""
    # 标准库: trace 事件序列化 (反证夹具的 JSONL 写入)
    import json

    path = tmp_path / "trace.jsonl"   # 文件名固定: 校验器侧按 .jsonl 约定读回
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events),               # 直跑即出自证报告: 不落盘, 便于人工在终端核对
                    encoding="utf-8")
    return path


def _good_events() -> list[dict]:
    """一条完整合法 trace 的事件序列 (run_start/tool_call/tool_result/final)。"""
    fp = "sha256:" + "0" * 64
    return [
        {"seq": 0, "type": "run_start", "payload": {"manifest": {}}},
        {"seq": 1, "type": "tool_call", "payload": {"tool": "cone_search", "args": {},
                                                    "args_norm": {}, "args_fp": fp}},
        {"seq": 2, "type": "tool_result", "payload": {"envelope_fp": fp,
                                                      "status": {"ok": True},
                                                      "cost": {}, "provenance": {}}},
        {"seq": 3, "type": "final_answer", "payload": {"answer_fp": fp,
                                                       "conclusion_card": {"kind": "rowset"}}},
    ]


def _bf_trace_group() -> dict:
    """六类 trace 扰动的检测结果 (各配一个坏事件序列, 必须被判不完整)。"""
    # 本地: trace 完整性校验器 (TI 组夹具的被测检测器)
    from evals.repro.trace import validate_trace

    results = {}   # 键 = 夹具 id, 值 = 是否被检出 (检测器真在跑, 不是自证式恒真)
    # TI-1 轨迹事件缺失 (删 final_answer)
    events = _good_events()                                                           # 先造一份完整轨迹: 扰动前必须先有合法基线, 否则测到的是别处的问题
    events = [e for e in events if e["type"] != "final_answer"]
    results["TI-1_event_missing"] = bool(validate_trace(events))
    # TI-2 指纹不匹配 (payload_fp 被改成错值 — validate_trace 的 payload_fp
    # 重算校验必须抓出; 修 D-2 前这里是恒 True 的自证式假检测)
    events = _good_events()                                                            # 再取一份干净轨迹: 每个扰动独立构造, 复用上一条的残缺轨迹会串味
    events[1]["payload_fp"] = "sha256:" + "f" * 64  # 与实算不符
    events[1]["payload"] = dict(events[1]["payload"], args={"ra": 999.0})
    results["TI-2_fingerprint_mismatch"] = any(
        "payload_fp_mismatch" in p for p in validate_trace(events))
    # TI-3 重跑轨迹不一致 (两次 run 的调用序列不同 — 一致性检测器的输入)
    from evals.repro.consistency import tsc as _tsc

    runs_a = [["cone_search"]] * 4 + [["cone_search", "count"]]
    results["TI-3_rerun_inconsistent"] = _tsc(runs_a)["tsc"] < 1.0
    # TI-4 成本字段造假 (tool_call>0 却上报 http_requests=0 — validate_trace
    # 的跨字段一致性校验必须抓出; 修 D-4 前这里是恒真的自证式假检测)
    events = _good_events()                                                       # 成本字段单独改: 跨字段造假的判据是「有调用却报 0 请求」, 其余必须干净
    events[2]["payload"]["cost"] = {"http_requests": 0}   # 调过工具却报 0 次请求 = 跨字段造假
    results["TI-4_cost_falsified"] = any(
        "cost_inconsistent" in p for p in validate_trace(events))
    # TI-5 时间戳乱序 (seq 断号)
    events = _good_events()                                                              # seq 单独改: 断号与乱序是两种形态, 这条只验断号被不被抓
    events[2]["seq"] = 7   # 从 2 跳到 7: 断号而非乱序, 两种形态都该被抓
    results["TI-5_timestamp_disorder"] = any("seq_gap" in p for p in validate_trace(events))
    # TI-6 脱敏遗漏 (payload 含凭据原文 — redact 必须抛)
    from evals.repro.trace import redact

    try:
        redact({"note": "Authorization: Bearer sk-live-xxx"})   # 凭据原文只在夹具里出现
        results["TI-6_redaction_miss"] = False   # 没抛 = 脱敏漏了, 记一条"未检出"
    except ValueError:
        results["TI-6_redaction_miss"] = True    # 抛了才算脱敏生效 (fail-closed 侧)
    return results


def run_broken_selftest() -> dict:
    """跑全部反证夹具 (两组); 返回 ``{metascore, results, pass}``。

    第一组 = 文档 §9 的 6 类一致性扰动 (检测器 TSC/PAC/RDC/FCC);
    第二组 = trace 完整性 6 类扰动 (检测器 trace.validate_trace/redact)。
    两组合计 12/12 检出才算 metascore 1.0 (文档 §9 + 任务书双约束)。
    """
    results = {}                                                                   # 两组结果并入一份: 报告与 metascore 都从这一份出, 不分两处记
    caught = 0   # 分子: 12 条夹具的检出计数, 两条漏检就把 metascore 拉到 11/12
    for fixture_id, fixture in FIXTURES.items():   # 第一组 (doc §9 六类): 逐个跑已登记检测器
        detected = bool(fixture["detector"]())
        results[fixture_id] = {"detected": detected,
                               "perturbation": fixture["perturbation"],
                               "expect_caught_by": fixture["expect_caught_by"],
                               "group": "consistency (doc §9)"}
        caught += 1 if detected else 0   # 累加而非取 or: 报告要逐条显示 caught/total
    trace_group = _bf_trace_group()   # 第二组 (trace 完整性六类): 换 validate_trace/redact
    for fixture_id, detected in trace_group.items():   # 两组同一计数口径, 合并成一个分数
        results[fixture_id] = {"detected": bool(detected),
                               "perturbation": fixture_id,
                               "expect_caught_by": "trace.validate_trace",
                               "group": "trace_integrity"}
        caught += 1 if detected else 0                                                     # 与第一组同口径累加: 两组的分子可相加, 分母才等于 12
    total = len(results)   # 分母 = 两组之和; 少登记一条夹具只会稀释而不报错, 登记纪律在此
    metascore = caught / total if total else 0.0   # 空集记 0.0 (阻断), 绝不记 1.0 蒙混过关
    return {"metascore": metascore, "results": results, "pass": metascore == 1.0}
