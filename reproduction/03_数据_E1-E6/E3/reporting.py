"""E3 状态和科学报告：不完整采集、无效评分与科学红线分别报告。"""
from __future__ import annotations

# 标准库：输出脱敏Markdown及独立计数报告。
from pathlib import Path

# 本轮模块：只统计完整主测，在线结果单列。
from common import GROUPS, HERE, anonymous, fingerprint, now, read_json, write_json
from prepare import verify_bundle
from pipeline import all_answers, check_model, validate_call
from api_client import parse_score
from scoring import judge_input, validate_score
from statistics_e3 import summarize, metrics
from review import comparison


def load_judged(batch: Path, bundle: dict, answers: list[dict]) -> list[dict]:
    """独立重算已保存评分并验证绑定，不依赖评分JSON的汇总值。"""
    items = {i["id"]: i for i in bundle["items"]}
    judged = []
    for record in answers:
        path = batch / "scores" / (record["key"]+".json")
        if not path.exists():
            continue
        score = read_json(path)
        expected = fingerprint(judge_input(bundle, items[record["item_id"]], record["answer"], record["data"]))
        if expected != score["input_hash"]:
            raise ValueError("评分和匿名输入的指纹不匹配")
        if read_json(batch / "manifest.json")["config"].get("E3_JUDGE_MODE") == "assistant":
            from assistant_review import verify_assistant_record
            verify_assistant_record(batch, score)
        else:
            check_model(batch, "judge", score["api"])
            validate_call(batch, "judge", score["api"], bundle["judge_system"],
                          judge_input(bundle, items[record["item_id"]], record["answer"], record["data"]))
            if parse_score(score["api"]["answer"]) != score["score"]:
                raise ValueError("保存的评分与主评模型原始输出不一致")
        counts = validate_score(score["score"], items[record["item_id"]], record["answer"])
        if counts != score["counts"]:
            raise ValueError("已保存评分计数与逐项判定不一致")
        judged.append({**record, "counts": counts, "score": score["score"]})
    return judged


def cost_usage(batch: Path) -> dict:
    """保存API真实用量；包含连接检查、反证及失败，不估算缺失usage。"""
    rows = []
    seen = set()
    def add_attempts(attempts, label):
        for index, attempt in enumerate(attempts):
            raw = attempt.get("response") or {}
            identifier = raw.get("id") or fingerprint(attempt)
            if identifier in seen:
                continue
            seen.add(identifier)
            rows.append({"record": label, "attempt": index+1, "response_id": raw.get("id"),
                         "http_status": attempt.get("http_status"), "status": raw.get("status"),
                         "returned_model": raw.get("model"), "usage": raw.get("usage"),
                         "incomplete_details": raw.get("incomplete_details"), "error_type": attempt.get("error_type")})
    def visit(data, label):
        if isinstance(data, dict):
            if isinstance(data.get("attempts"), list):
                add_attempts(data["attempts"], label)
            for key, value in data.items():
                if key not in ("attempts", "response", "request"):
                    visit(value, label+"/"+key)
        elif isinstance(data, list):
            for index, value in enumerate(data):
                visit(value, label+"/"+str(index))
    for directory in ("answers", "scores", "failures", "diagnostics"):
        for path in sorted((batch / directory).glob("*.json")):
            visit(read_json(path), str(path.relative_to(batch)))
    if (batch / "connection.json").exists():
        visit(read_json(batch / "connection.json"), "connection")
    return {"real_usage_only": True, "records": rows, "note": "包括实际成功、失败及诊断HTTP尝试；缺失usage记null，不估算费用或token"}


def report(batch: Path) -> dict:
    """生成可随时更新的真实状态报告，缺回答或评分时不输出正式主指标。"""
    bundle = verify_bundle(batch)
    answers = all_answers(batch, bundle)
    judged = load_judged(batch, bundle, answers)
    main = [r for r in judged if r["tier"] == "fixture"]
    live = [r for r in judged if r["tier"] == "live"]
    main_ids = [i["id"] for i in bundle["items"] if i["tier"] == "fixture"]
    gate_path = batch / "judge-selftest.json"
    from scoring import controls, control_passed
    from pipeline import score_one
    from api_client import ModelAPI
    case_rows = controls(bundle)
    if all((batch / "scores" / (c["control_id"]+".json")).exists() for c in case_rows):
        values = {**read_json(batch / "manifest.json")["config"], "E3_API_KEY": ""}
        api = ModelAPI(values)
        try:
            checked = {c["control_id"]: control_passed(c["control_id"], score_one(
                batch, bundle, c["item"], c["answer"], c["data"], c["control_id"], api)["counts"]) for c in case_rows}
        finally:
            api.session.close()
        gate = {"passed": all(checked.values()), "metascore": sum(checked.values())/3, "results": checked}
        if gate_path.exists() and read_json(gate_path) != gate:
            raise ValueError("反证门槛记录与逐项原始评分不一致")
    else:
        gate = {"passed": False, "status": "pending"}
    complete = len(answers) == 216
    valid = complete and len(judged) == 216 and gate["passed"]
    blocked = sorted({flag for r in judged for flag in r["counts"]["redlines"]})
    result = {"batch_id": batch.name, "generated_at": now(),
              "collection": {"expected": 216, "actual": len(answers), "complete": complete,
                             "main_actual": sum(r["tier"] == "fixture" for r in answers),
                             "live_actual": sum(r["tier"] == "live" for r in answers)},
              "rating": {"expected": 216, "actual": len(judged), "valid": valid, "selftest": gate},
              "scientific_performance": {"redlines": blocked, "status": "pending" if not valid else ("FAIL" if blocked else "no_redline_detected")},
              "expert": comparison(batch, judged), "main": None, "live": None,
              "failures_recorded": len(list((batch / "failures").glob("*.json"))),
              "limitations": ["当前对话助手主评，未调用评分API；不是原双专家方案", "助手参与准备，无独立评分上下文且已见组别映射；匿名副本不保证盲性",
                              "主测仅32个独立题号，三次重复不增加独立题目样本量",
                              "辅测使用固定查询回包，不评价模型工具选择", "不宣称未进行的专家复核已完成", "服务商返回模型标签不能证明权重快照不变；未发送温度参数，不宣称固定温度"]}
    if len(main) == 192 and gate["passed"]:
        result["main"] = summarize(main, main_ids, bundle["slr_ids"])
    if len(live) == 24 and gate["passed"]:
        result["live"] = {g: [metrics([r for r in live if r["group"] == g and r["repeat"] == repetition],
                                         [i["id"] for i in bundle["items"] if i["tier"] == "live" and i["axis"] in "ABG"])
                              for repetition in (1, 2, 3)] for g in GROUPS}
    errors = [{"item_id": r["item_id"], "group": r["group"], "repeat": r["repeat"],
               "quote": row["quote"], "reason": row["reason"], "redline": row["id"]}
              for r in judged for row in r["score"]["redlines"] if row["triggered"]]
    result["error_taxonomy"] = errors
    write_json(batch / "report.json", result)
    write_json(batch / "usage.json", cost_usage(batch))
    write_json(batch / "agreement.json", result["expert"])
    lines = ["# E3 本轮准备与实验报告", "", f"- 批次：{batch.name}", f"- 更新时间：{result['generated_at']}", f"- 被测模型（配置）：{read_json(batch / 'manifest.json')['config']['E3_TEST_MODEL']}",
             f"- 采集：{len(answers)}/216（主测 {result['collection']['main_actual']}/192，辅测 {result['collection']['live_actual']}/24）",
             f"- 有效结构评分：{len(judged)}/216；反证门槛：{'通过' if gate['passed'] else '未通过/未执行'}",
             f"- 评分完整有效：{valid}；科学红线状态：{result['scientific_performance']['status']}",
             f"- 专家状态：{result['expert']['status']}。当前对话助手主评，专家复核待完成。", "",
             "## 待补充", ""]
    from common import config
    _, missing = config()
    lines += ["- " + value for value in missing]
    if not missing:
        lines.append("- 模型配置字段已填写；是否可调用仍以连接检查为准。")
    if result["expert"]["status"] != "complete":
        lines.append("- 一名未参与出题的天文专家独立完成全量盲评并返回评分JSON。")
    lines += ["", "## 主指标（仅离线32题）", ""]
    if result["main"]:
        lines += ["| 指标 | S-A 中位数 | S-B 中位数 |", "|---|---|---|"]
        for field in ("sfa", "ungr", "ucr", "slr", "rqc"):
            values = [result["main"]["systems"][g]["metrics"][field]["median"] for g in GROUPS]
            lines.append(f"| {field.upper()} | {values[0]} | {values[1]} |")
        lines += ["", "三次重复极差、逐轴统计、配对McNemar和题号成组bootstrap区间见report.json。"]
    else:
        lines.append("尚未满足192份主测有效评分及反证门槛；不输出主指标。")
    lines += ["", "## 方法与限制", ""] + ["- " + x for x in result["limitations"]]
    lines += ["- 主测SLR分母为14题；无科学数值或主张时对应比例记null。",
              "- 对评分对象保留原文和指纹，评分只用匿名副本；人工分数独立保留、不自动覆盖主评。",
              "", "## 产物", "", "- manifest.json / bundle.json / PROTOCOL.md：冻结清单与材料。",
              "- answers/ / live/ / scores/ / failures/：真实请求、回答、回包、评分和失败。",
              "- prescreen.json：机器预筛提示。", "- expert-blind/：独立专家盲评包（全量采集完成后才能交给专家）。",
              "- operator/：主持人私有映射，不能交给评阅人。",
              "- report.json / agreement.json / usage.json：可重算统计、人机一致性与实际API用量。", ""]
    text = "\n".join(lines)
    (batch / "REPORT.md").write_text(text, encoding="utf-8")
    (HERE / "REPORT.md").write_text(text+"\n当前完整产物目录：`"+str(batch)+"`\n", encoding="utf-8")
    return result
