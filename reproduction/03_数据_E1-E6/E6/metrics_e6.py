"""四一致率和分层归因：保留原口径对照，修复分母及空调用缺陷。"""
# 标准库：序列、语义载荷、数值与计数。
import itertools
import math
import re
from collections import Counter
# 项目归一化及本轮统计单位。
from common_e6 import fp, encode
from statistics_e6 import modal, cluster_ci, alpha_nominal
from evals.repro.normalize import norm_args, norm_card, cards_equal
from evals.groundtruth.canonical import normalize_value
from src.protocol import normalize_sqlid

def invalid_session_call(call):
    """独立依据生产输入契约，不让成功空表信封掩盖无效会话标识。"""
    if call['tool'] not in ('count','fetch_page'):
        return False
    try:
        normalize_sqlid(call['args'].get('sqlid'))
    except (ValueError,TypeError):
        return True
    return False

def exact_rows(rows):
    """沿用既有单格规范化，但标识符保持精确字符，不能转浮点合并大ID。"""
    def cell(key, value):
        """站点nan文本保留为显式非有限值，不能让严格JSON评分中断。"""
        if value is not None and re.search(r'(?:source_?id|obj_?id|identifier)$', key, re.I):
            return str(value).strip()
        normalized = normalize_value(key, value)
        if isinstance(normalized, float) and not math.isfinite(normalized):
            return {'nonfinite_numeric_text':str(value).strip().lower()}
        return normalized
    return [{key:cell(key,value) for key,value in row.items()} for row in rows]

def aliases_for(run):
    """按建立顺序归一易失 sqlid，保留未绑定会话的区别。"""
    aliases = {}
    for call, envelope in zip(run.get("tool_calls", []), run.get("envelopes", [])):
        sid = envelope["provenance"].get("session_id")
        if sid and call["tool"] in ("cone_search", "crossmatch_batch"):
            aliases[str(sid).lstrip("s")] = f"<query:{len(aliases)}>"
    return aliases

def stable_payload(value, aliases):
    """规范易失会话标识，不删除科学数据或失败状态。"""
    if isinstance(value, dict):
        return {k: (aliases.get(str(v).lstrip("s"), "unbound:" + str(v)) if k in ("sqlid", "session_id") and v is not None
                    else stable_payload(v, aliases)) for k, v in value.items()}
    if isinstance(value, list):
        return [stable_payload(v, aliases) for v in value]
    if isinstance(value, str):
        return re.sub(r"(/sqlid/)(s?\d+)", lambda m: m[1] + aliases.get(m[2].lstrip("s"), "unbound:" + m[2]), value)
    return value

def call_signature(run):
    """调用参数使用既有单位归一，工具身份和会话来源共同保留。"""
    aliases = aliases_for(run)
    return [{"tool": c["tool"], "args": stable_payload(norm_args(c["args"]), aliases)} for c in run["tool_calls"]]

def arguments_same(left, right):
    """字段容差按 E6：坐标1e-6度、半径1e-3角秒，布尔和空值严格。"""
    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            return False
        for key in left:
            a, b = left[key], right[key]
            if key in ("ra", "dec", "radius_arcsec") and isinstance(a, (int, float)) and isinstance(b, (int, float)):
                if abs(a - b) > (1e-3 if key == "radius_arcsec" else 1e-6):
                    return False
            elif not arguments_same(a, b):
                return False
        return True
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(arguments_same(a, b) for a, b in zip(left, right))
    return left == right

def dedupe(calls):
    """TSC 仅删除连续重复，PAC保持实际调用数。"""
    return [name for name, _ in itertools.groupby(c["tool"] for c in calls)]

def data_signature(run):
    """L1规范全部数据和状态；L2行集+非行语义，避免ERROR/EMPTY合并。"""
    aliases = aliases_for(run)
    payloads, tokens, key_values = [], set(), []
    for c, envelope in zip(run["tool_calls"], run["envelopes"]):
        data = stable_payload(envelope["data"], aliases)
        status = envelope["status"]
        payloads.append({"tool": c["tool"], "data": data, "status": status})
        if "rows" in data:
            for row in exact_rows(data["rows"]):
                tokens.add(encode({"catalog": c["args"].get("catalog", "ps1"), "row": row}))
            tokens.add(encode({"tool": c["tool"], "status": status,
                              "total_count": data.get("total_count"), "returned_count": data.get("returned_count")}))
        else:
            tokens.add(encode({"tool": c["tool"], "data": data, "status": status}))
        key_values.append({"tool": c["tool"], "status": status,
                           "total": data.get("total_count", data.get("total")),
                           "ra": data.get("ra"), "dec": data.get("dec")})
    return {"L1": fp(payloads), "L2": tokens, "L3": key_values, "has_outputs": bool(payloads)}

def jaccard(a, b):
    """规范行集 Jaccard，空集的确定性明确标为无数据。"""
    return len(a & b) / len(a | b) if a | b else 1.0

def score_task(runs, lane):
    """逐题返回各指标的实际重复计数与各调用槽位Wilson。"""
    sequences = [dedupe(r["tool_calls"]) for r in runs]
    calls = [call_signature(r) for r in runs]
    datasets = [data_signature(r) for r in runs]
    cards = [norm_card(r.get("reviewed_card", r["card"])) for r in runs]
    tsc = modal(sequences)
    tsc["set"] = modal([sorted(set(s)) for s in sequences])
    pac_sequence = modal(calls, arguments_same)
    slots = []
    for slot in range(max((len(c) for c in calls), default=0)):
        slots.append(modal([c[slot] if slot < len(c) else None for c in calls], arguments_same))
    pac = (sum(s["point"] for s in slots) / len(slots) if slots else 1.0) if len(runs) >= 2 else None
    l1 = modal([d["L1"] for d in datasets])
    l2 = modal([d["L2"] for d in datasets])
    l3 = modal([d["L3"] for d in datasets], arguments_same)
    jaccard_mode = sum(jaccard(d["L2"], datasets[l2["ref_index"]]["L2"]) for d in datasets) / len(datasets) if len(datasets) >= 2 else None
    jaccard_pair = [jaccard(a["L2"], b["L2"]) for a, b in itertools.combinations(datasets, 2)]
    fcc = modal(cards, cards_equal)
    # 归因前提同时检查工具和参数众数，后端数据差异不能越过前提。
    ref_calls = calls[pac_sequence["ref_index"]] if calls else []
    ref_data = datasets[l1["ref_index"]]["L1"] if datasets else None
    attribution = Counter()
    for r, seq, call, data, card in zip(runs, sequences, calls, datasets, cards):
        illegal = any(c["tool"] not in {"resolve_name", "list_catalogs", "describe_catalog", "cone_search", "crossmatch_batch", "count", "fetch_page"} for c in call)
        hard = (any(e["status"].get("error_code") == "E_INVALID_INPUT" for e in r["envelopes"])
                or any(invalid_session_call(c) for c in r['tool_calls']))
        if illegal:
            code = "ERR_ROUTE"
        elif hard:
            code = "ERR_PARAM_SCHEMA"
        elif seq != sequences[tsc["ref_index"]] or not arguments_same(call, ref_calls):
            code = "ERR_PARAM_UNSTABLE"
        elif any(e["status"].get("ok") is False for e in r["envelopes"]) or any(f['wrapped_as_success'] for f in r.get('wire_semantic_failures',[])):
            code = "ERR_BACKEND"
        elif data["L1"] != ref_data:
            code = "ERR_BACKEND_DRIFT"
        elif any(q.get('strategy_changed') is False for q in r.get('retry_records',[])):
            code = 'ERR_RETRY_INEFFECTIVE'
        elif not cards_equal(card, cards[fcc["ref_index"]]):
            code = "ERR_CONCLUSION_UNSTABLE"
        else:
            code = "OK"
        attribution[code] += 1
    return {"runs": len(runs), "TSC": tsc, "PAC_call": {"point": pac, "slots": slots, "denominator": "actual repeats per aligned call slot; macro over slots"},
            "PAC_sequence": pac_sequence,
            "RDC": {"point": l1["point"] if lane in ("R0", "R3") else jaccard_mode,
                    "level": "L1" if lane in ("R0", "R3") else "L2 Jaccard", "L1": l1, "L2_equality": l2, "L3": l3,
                    "L2_jaccard_mode": jaccard_mode, "L2_jaccard_pairwise": sum(jaccard_pair) / len(jaccard_pair) if jaccard_pair else None,
                    "data_outputs_observed": any(d["has_outputs"] for d in datasets)},
            "FCC": fcc, "attribution": dict(attribution)}

def score_lane(grouped, lane):
    """32题宏平均；题号成组区间与α保留小样本限制。"""
    per_task = {task: score_task(runs, lane) for task, runs in grouped.items()}
    aggregate = {k: cluster_ci([t[k]["point"] for t in per_task.values()]) for k in ("TSC", "PAC_call", "RDC", "FCC")}
    aggregate["RDC_data_conditioned"] = cluster_ci([t["RDC"]["point"] for t in per_task.values() if t["RDC"]["data_outputs_observed"]])
    attribution = Counter()
    for t in per_task.values():
        attribution.update(t["attribution"])
    return {"per_task": per_task, "aggregate": aggregate, "attribution": dict(attribution),
            "alpha_TSC": alpha_nominal([[encode(dedupe(r["tool_calls"])) for r in runs] for runs in grouped.values()]),
            "task_units": len(grouped), "records": sum(len(r) for r in grouped.values()),
            "coverage": {"tasks_with_5_valid": sum(len(r) == 5 for r in grouped.values()), "task_target": 32,
                         "record_target": 160, "independent_task_units": len(grouped)},
            "note": "L2为完整规范行集+非行语义的Jaccard；原实现仅主键集全等会漏掉单值/元数据变化。"}
