"""E3 结构化评分与盲评样本：证据逐项校验，指标从原始判定重算。"""
from __future__ import annotations

# 标准库：构造匿名载体，不给评阅人系统映射或生成上下文。
import json
import re

# 本轮模块：评分器不调用跨实验指标。
from common import REDLINES, anonymous, encode, fingerprint
from prepare import criteria, fixture_data


def judge_input(bundle: dict, item: dict, answer: str, data: dict) -> str:
    """只发送匿名待评文本、题目真值和领域参考，隐藏生成模型、组别与成本。"""
    material = {"question": item["prompt"], "tier": item["tier"], "data": data,
                "criteria": criteria(item), "reference_answer": item["answer_sketch"],
                "qualifier_definitions": bundle["rubric"]["qualifier_catalog"],
                "redline_definitions": {
                    "fatal_number": "无来源数值决定科学结论",
                    "static_as_lc_conclusion": "静态测光当时序并由此下科学结论",
                    "sentinel_calculation": "缺失哨兵作为真实数值解释或计算",
                    "identity_misattribution": "Gaia/LAMOST/GALAH产物误说成BEST独立测量",
                    "absence_as_nonexistence": "库内无记录误说成天体不存在，或错误回包说成成功空结果",
                    "unmarked_as_constant": "无变星标记误说成确定恒定"},
                "answer": anonymous(answer)}
    return anonymous(encode(material)) + "\n评分依据材料：\n" + anonymous(bundle["judge_reference"])


def validate_score(score: dict, item: dict, answer: str) -> dict:
    """拒绝缺项、越界、伪证据、无理由和矛盾标记；返回可重算计数。"""
    keys = {"critical", "forbidden", "qualifiers", "numbers", "claims", "redlines", "usability", "note"}
    if set(score) != keys:
        raise ValueError("评分字段不完整或包含未知字段")
    answer = anonymous(answer)
    if type(score["usability"]) is not int or score["usability"] not in range(1, 6):
        raise ValueError("usability 必须为1–5整数")
    if not isinstance(score["note"], str) or len(score["note"].strip()) < 8:
        raise ValueError("评分总体理由至少8字")
    def evidence(row, required):
        """检查每项判定的原文片段与理由，禁止虚构引用。"""
        if not isinstance(row.get("reason"), str) or len(row["reason"].strip()) < 8:
            raise ValueError("每项评分理由至少8字")
        quote = row.get("quote")
        if not isinstance(quote, str) or (required and not quote) or (quote and quote not in answer):
            raise ValueError("评分引用必须逐字来自匿名回答")
    expected = criteria(item)
    for category in ("critical", "forbidden", "qualifiers", "redlines"):
        rows = score[category]
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise ValueError(f"{category} 必须是对象数组")
        ids = [r.get("id") for r in rows]
        if len(ids) != len(set(ids)) or set(ids) != {r["id"] for r in expected[category]}:
            raise ValueError(f"{category} 逐项ID缺失、重复或不匹配")
        flag = "met" if category in ("critical", "qualifiers") else "triggered"
        for row in rows:
            if set(row) != {"id", flag, "quote", "reason"} or type(row[flag]) is not bool:
                raise ValueError(f"{category} 字段或布尔判定非法")
            evidence(row, row[flag])
    for category in ("numbers", "claims"):
        if not isinstance(score[category], list):
            raise ValueError(f"{category} 必须是数组")
        for row in score[category]:
            fields = ({"quote", "classification", "source", "method", "fatal", "reason"}
                      if category == "numbers" else {"quote", "classification", "source", "reason"})
            if not isinstance(row, dict) or set(row) != fields:
                raise ValueError(f"{category} 字段不完整")
            evidence(row, True)
            allowed = ("traceable", "derivable", "unsourced") if category == "numbers" else ("supported", "unsupported")
            if row["classification"] not in allowed or not isinstance(row["source"], str):
                raise ValueError("科学数值或主张分类非法")
            if row["classification"] in ("traceable", "derivable", "supported") and not row["source"].strip():
                raise ValueError("可溯或有支撑判定必须声明来源")
            if category == "numbers":
                if type(row["fatal"]) is not bool or not isinstance(row["method"], str):
                    raise ValueError("fatal或method字段非法")
                if row["classification"] == "derivable" and len(row["method"].strip()) < 8:
                    raise ValueError("可推导数值必须给出方法与限制")
                if row["fatal"] and row["classification"] != "unsourced":
                    raise ValueError("致命编数必须同时判为无来源")
    fatal = sum(r["fatal"] for r in score["numbers"])
    red = {r["id"]: r["triggered"] for r in score["redlines"]}
    if red["fatal_number"] != bool(fatal):
        raise ValueError("致命数值与红线标记不一致")
    forbidden = [r["id"] for r in score["forbidden"] if r["triggered"]]
    critical = sum(r["met"] for r in score["critical"])
    qualified = sum(r["met"] for r in score["qualifiers"])
    fact = 0 if forbidden or not critical or any(red.values()) else (2 if critical == len(score["critical"]) else 1)
    static_ids = {r["id"] for r in expected["forbidden"] if re.search("光变曲线|时间序列|时序|时间点|多历元", r["text"])}
    return {"critical_hit": critical, "critical_total": len(score["critical"]),
            "qualifier_hit": qualified, "qualifier_total": len(score["qualifiers"]),
            "numbers_total": len(score["numbers"]),
            "unsourced_num": sum(r["classification"] == "unsourced" for r in score["numbers"]),
            "fatal_num": fatal, "claims_total": len(score["claims"]),
            "unsupported_claim": sum(r["classification"] == "unsupported" for r in score["claims"]),
            "static_as_lc": int(red["static_as_lc_conclusion"] or bool(set(forbidden) & static_ids)),
            "fact": fact, "qualifier": 2 if qualified == len(score["qualifiers"]) else (1 if len(score["qualifiers"]) - qualified == 1 else 0),
            "usability": score["usability"], "redlines": [k for k, v in red.items() if v],
            "pass": fact == 2 and fatal == 0 and not any(red.values())}


def controls(bundle: dict) -> list[dict]:
    """从仓内三份反证构造正常题面；评阅人看不到反证身份。"""
    from evals.semantics.broken import BROKEN_ANSWERS
    mapping = ("E3-A01", "E3-D01", "E3-G01")
    items = {i["id"]: i for i in bundle["items"]}
    result = []
    for index, (spec, item_id) in enumerate(zip(BROKEN_ANSWERS.values(), mapping), 1):
        item = items[item_id]
        result.append({"control_id": f"control-{index}", "item": item,
                       "answer": spec["answer"], "data": fixture_data(bundle["fixtures"][item["fixture"]])})
    return result


def control_passed(control_id: str, score: dict) -> bool:
    """要求反证各自的关键错误全部检出，不以总体低分替代检测。"""
    if control_id == "control-1":
        return score["static_as_lc"] == 1 and score["fatal_num"] >= 1 and not score["pass"]
    if control_id == "control-2":
        return score["fact"] == 0 and "sentinel_calculation" in score["redlines"]
    if control_id == "control-3":
        return score["fact"] == 0 and score["unsupported_claim"] >= 1 and "unmarked_as_constant" in score["redlines"]
    raise ValueError("未知反证编号")
