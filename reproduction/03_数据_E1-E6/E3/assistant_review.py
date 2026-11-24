"""当前助手直接评分的匿名载体；不调用评分API，不伪造API来源。"""
from __future__ import annotations

import secrets
from pathlib import Path
from common import anonymous, fingerprint, now, read_json, write_json
from prepare import verify_bundle
from scoring import controls, judge_input, validate_score


def targets(batch: Path, bundle: dict) -> dict:
    from pipeline import all_answers
    lookup = {i["id"]: i for i in bundle["items"]}
    rows = {r["key"]: {"item": lookup[r["item_id"]], "answer": r["answer"], "data": r["data"]}
            for r in all_answers(batch, bundle)}
    rows.update({r["control_id"]: r for r in controls(bundle)})
    return rows


def export_assistant(batch: Path) -> dict:
    bundle = verify_bundle(batch)
    rows = targets(batch, bundle)
    path = batch / "operator/assistant-map.json"
    mapping = read_json(path) if path.exists() else {}
    for key in rows:
        if key not in mapping.values():
            mapping[secrets.token_hex(8)] = key
    write_json(path, mapping)
    package = {}
    for sample, key in sorted(mapping.items()):
        row = rows[key]
        text = judge_input(bundle, row["item"], row["answer"], row["data"])
        material = __import__("json").loads(text.split("\n评分依据材料：")[0])
        package[sample] = {"input_hash": fingerprint(text), **material}
    write_json(batch / "assistant-review/samples.json", package)
    (batch / "assistant-review/instructions.txt").write_text(bundle["judge_system"] +
        "\n当前助手须逐份阅读并填写，不能用规则扫描或预写答案替代科学主评。\n" +
        anonymous(bundle["judge_reference"]))
    return {"available": len(package), "unscored": sum(not (batch / "scores" / (key+".json")).exists() for key in mapping.values())}


def verify_assistant_record(batch: Path, record: dict) -> None:
    provenance = record.get("provenance", {})
    if provenance.get("mode") != "current_assistant" or provenance.get("api_called") is not False:
        raise ValueError("缺少当前助手的真实评分来源记录")
    path = (batch / provenance["source"]).resolve()
    if not path.is_relative_to(batch / "assistant-imports"):
        raise ValueError("评分来源路径越界")
    source = read_json(path)
    if fingerprint(source) != provenance["source_hash"] or source[provenance["sample_id"]] != record["score"]:
        raise ValueError("保存的评分与助手原始评分文件不一致")


def import_assistant(batch: Path, path: Path) -> dict:
    bundle = verify_bundle(batch)
    if read_json(batch / "manifest.json")["config"].get("E3_JUDGE_MODE") != "assistant":
        raise ValueError("该批次不是当前助手主评协议")
    from api_client import parse_score
    source = parse_score(path.read_text())
    mapping = read_json(batch / "operator/assistant-map.json")
    rows = targets(batch, bundle)
    if not source or not set(source).issubset(mapping):
        raise ValueError("助手评分为空或包含未知匿名样本")
    records = []
    digest = fingerprint(source)
    relative = "assistant-imports/" + digest + ".json"
    for sample, score in source.items():
        key = mapping[sample]
        row = rows[key]
        counts = validate_score(score, row["item"], row["answer"])
        record = {"key": key, "input_hash": fingerprint(judge_input(bundle, row["item"], row["answer"], row["data"])),
                  "score": score, "counts": counts,
                  "provenance": {"mode": "current_assistant", "api_called": False, "context_isolated": False,
                                 "model_api_verified": False, "source": relative, "source_hash": digest,
                                 "sample_id": sample, "imported_at": now()}}
        existing = batch / "scores" / (key + ".json")
        if existing.exists():
            old = read_json(existing)
            verify_assistant_record(batch, old)
            if old["score"] != score or old["input_hash"] != record["input_hash"]:
                raise ValueError("禁止覆盖已成功的主评分；修订需新批次")
        else:
            records.append(record)
    write_json(batch / relative, source)
    for record in records:
        write_json(batch / "scores" / (record["key"] + ".json"), record)
    return {"imported": len(records), "api_called": False}
