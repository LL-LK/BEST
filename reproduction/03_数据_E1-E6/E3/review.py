"""E3 专家独立盲评包：匿名乱序、隐藏反证、独立导入与人机分歧记录。"""
from __future__ import annotations

# 标准库：持久化随机化种子及可填写JSON评分模板。
import copy
import csv
import io
import random
import secrets
from pathlib import Path

# 本轮模块：不把模型评分或组别映射交给专家。
from common import GROUPS, anonymous, fingerprint, now, read_json, record_key, write_json
from prepare import criteria, fixture_data, verify_bundle
from scoring import controls, control_passed, validate_score
from pipeline import all_answers
from statistics_e3 import agreement


def empty_score(item: dict) -> dict:
    """生成必须由评阅人独立填写的空模板，不预填通过或模型分数。"""
    spec = criteria(item)
    score = {"numbers": [], "claims": [], "usability": None, "note": ""}
    for category in ("critical", "forbidden", "qualifiers", "redlines"):
        flag = "met" if category in ("critical", "qualifiers") else "triggered"
        score[category] = [{"id": r["id"], flag: None, "quote": "", "reason": ""} for r in spec[category]]
    return score


def export_review(batch: Path) -> dict:
    """创建完整219项盲评模板；未采集回答明确标pending，不填假回答。"""
    bundle = verify_bundle(batch)
    answers = {r["key"]: r for r in all_answers(batch, bundle)}
    items = {i["id"]: i for i in bundle["items"]}
    controls_list = controls(bundle)
    control_map = {c["control_id"]: c for c in controls_list}
    complete_collection = len(answers) == 216
    private = batch / "operator" / "blind-map.json"
    if not private.exists():
        keys = [record_key(g, i["id"], r) for g in GROUPS for i in bundle["items"] for r in (1, 2, 3)]
        keys += list(control_map)
        random.SystemRandom().shuffle(keys)
        mapping = {secrets.token_hex(8): key for key in keys}
        write_json(private, {"mapping": mapping, "created_at": now()})
    mapping = read_json(private)["mapping"]
    package = batch / "expert-blind"
    templates = {}
    rows = []
    available = 0
    for sample_id, key in mapping.items():
        if key in control_map:
            control = control_map[key]
            item, data, answer = control["item"], control["data"], control["answer"]
        else:
            group, item_id, repetition = key.split("_")
            item = items[item_id]
            record = answers.get(key)
            data = record["data"] if record else (fixture_data(bundle["fixtures"][item["fixture"]]) if item["tier"] == "fixture" else None)
            answer = record["answer"] if record else None
        # 全量采集前不暴露任何回答，防止ready状态泄露隐藏反证身份。
        if not complete_collection:
            answer = None
        available += answer is not None
        public = {"sample_id": sample_id, "question": item["prompt"], "tier": item["tier"],
                  "data": data, "answer": answer, "criteria": criteria(item),
                  "reference_answer": item["answer_sketch"],
                  "qualifier_definitions": bundle["rubric"]["qualifier_catalog"],
                  "status": "ready" if answer is not None else "pending_collection"}
        public = read_safe(public)
        write_json(package / "samples" / f"{sample_id}.json", public)
        templates[sample_id] = empty_score(item)
        rows.append({"sample_id": sample_id, "tier": item["tier"], "status": public["status"],
                     "sample_file": f"samples/{sample_id}.json"})
    write_json(package / "scorecard.blank.json", templates)
    write_json(package / "truth-reference.json", {"material": anonymous(bundle["judge_reference"])})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    (package / "index.csv").write_text(buffer.getvalue(), encoding="utf-8-sig")
    (package / "README.md").write_text("""# 独立天文专家盲评

只接收本目录，勿接收operator目录、原始请求或模型评分。评阅人不得参与出题。
按index.csv的独立随机顺序评分。pending_collection表示尚无回答，不能评分。
fixture数值均为构造样本，live为本轮真实回包；不把未标记变星当作恒定证据。
将scorecard.blank.json复制为你自己的评分文件，逐项填写，不改sample_id。
met/triggered填true或false；usability填1–5整数；理由至少8字；quote逐字来自answer。
numbers必须列出全部科学数值，字段为quote/classification/source/method/fatal/reason。
classification为traceable、derivable或unsourced；可推导量写明公式与限制。
claims必须列出全部科学主张，字段为quote/classification/source/reason，分类supported或unsupported。
无科学数值或主张时可为空数组。缺项、空理由或无法核实的来源需指出，不用猜测补齐。
redline的fatal_number与numbers中的fatal保持一致；其余红线含义见匿名真值材料与题目标准。
不要联系模型主评核对答案，也不要查看其评分。原始专家评分独立保存，不自动覆盖模型判定。
评分结束后将自己的评分JSON文件交回，由实验主持人导入。
""", encoding="utf-8")
    status = {"expected": 219, "available": available, "complete": available == 219,
              "model_scores_in_package": False, "group_mapping_in_package": False}
    write_json(batch / "expert-package-status.json", status)
    return status


def read_safe(value):
    """对公开评分副本统一脱标识；保留私有原始回答供血缘校验。"""
    import json
    return json.loads(anonymous(json.dumps(value, ensure_ascii=False)))


def import_expert(batch: Path, path: Path) -> dict:
    """独立导入专家逐项评分，保存原始记录并检测隐藏反证。"""
    bundle = verify_bundle(batch)
    mapping = read_json(batch / "operator/blind-map.json")["mapping"]
    answers = {r["key"]: r for r in all_answers(batch, bundle)}
    lookup = {i["id"]: i for i in bundle["items"]}
    cm = {c["control_id"]: c for c in controls(bundle)}
    raw = read_json(path)
    if not isinstance(raw, dict) or set(raw) != set(mapping):
        raise ValueError("专家评分必须覆盖完整219个样本ID；缺项不作正式复核")
    records, passed = {}, {}
    for sample_id, score in raw.items():
        key = mapping[sample_id]
        if key in cm:
            item, answer = cm[key]["item"], cm[key]["answer"]
        else:
            if key not in answers:
                raise ValueError("专家评分对应的真实回答尚未采集")
            item, answer = lookup[answers[key]["item_id"]], answers[key]["answer"]
        counts = validate_score(score, item, answer)
        records[key] = {"sample_id": sample_id, "score": score, "counts": counts}
        if key in cm:
            passed[key] = control_passed(key, counts)
    result = {"imported_at": now(), "source_hash": fingerprint(raw), "records": records,
              "control_results": passed, "valid": all(passed.values()),
              "expert_note": "独立专家全量评分；不自动覆盖GPT主评结果"}
    write_json(batch / "expert-imports" / (fingerprint(raw)[:16]+".json"), {"raw": raw, **result})
    write_json(batch / "expert.json", result)
    if not result["valid"]:
        raise ValueError("专家隐藏反证未全部检出；本次专家复核无效，原始文件已保留")
    return result


def comparison(batch: Path, judged: list[dict]) -> dict:
    """输出全量人机一致性和逐轴分歧，不称作双专家一致性。"""
    if not (batch / "expert.json").exists():
        return {"status": "pending", "note": "GPT-6.1主评，专家复核待完成"}
    expert = read_json(batch / "expert.json")
    if not expert["valid"]:
        return {"status": "invalid", "note": "专家反证未通过，不计算正式人机一致性"}
    fields = ("pass", "fact", "qualifier", "unsourced_num", "unsupported_claim", "usability")
    disagreements = []
    for record in judged:
        key = record["key"]
        human = expert["records"][key]["counts"]
        changes = {f: {"model": record["counts"][f], "expert": human[f]} for f in fields if record["counts"][f] != human[f]}
        if changes:
            disagreements.append({"sample_id": expert["records"][key]["sample_id"], "item_id": record["item_id"], "differences": changes})
    def subset_stats(records):
        """对实际评分配对计算一致性，数据不足用null。"""
        return {f: agreement([r["counts"][f] for r in records],
                             [expert["records"][r["key"]]["counts"][f] for r in records]) for f in fields}
    return {"status": "complete", "meaning": "模型与一名固定专家之间的一致性，不是双专家评分一致性",
            "all": subset_stats(judged),
            "main": subset_stats([r for r in judged if r["tier"] == "fixture"]),
            "by_axis": {axis: subset_stats([r for r in judged if r["axis"] == axis and r["tier"] == "fixture"]) for axis in "ABCDEFG"},
            "disagreements": disagreements, "expert_scores_override_model": False}
