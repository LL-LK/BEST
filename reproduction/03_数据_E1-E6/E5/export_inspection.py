from pathlib import Path
import hashlib
import json
import zstandard

ROOT = Path(__file__).parent
SOURCE = Path(r"<TOOL_ROOT>\deepseek\.dsh\sessions\--<USER_HOME>-Desktop-~8BBA~6587-e2~548Ce5~91CD~6784~8BA1~5212-E5_~6267~884C_2026-10-12_v4_01--\session-dcbae0e6-b9a5-457a-8439-d88af96623ca\session.v4.jsonl.zstd")
with SOURCE.open("rb") as stream:
    raw = zstandard.ZstdDecompressor().stream_reader(stream).read()
records = [json.loads(line) for line in raw.splitlines()]

def redact(value):
    if isinstance(value, list):
        return [redact(v) for v in value if not (isinstance(v, dict) and v.get("type") in ("thinking", "reasoning"))]
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items() if k not in ("reasoningContent", "reasoning_content", "thinking", "reasoning", "thinkingSignature")}
    return value

with (ROOT / "runtime-inspection.events.redacted-v2.jsonl").open("x", encoding="utf-8") as stream:
    for record in records:
        stream.write(json.dumps(redact(record), ensure_ascii=False) + "\n")
calls = {}
catalogs = {}
catalog_errors = []
for record in records:
    if record.get("type") == "tool/call":
        calls[record["data"]["callId"]] = record["data"]
    if record.get("type") == "tool/result":
        message = record["data"]["message"]
        call_id = message.get("toolCallId") or message.get("callId")
        call = calls.get(call_id)
        if call and call["name"] == "cordis_inspect_query":
            args = json.loads(call["arguments"])
            texts = [c["text"] for c in message.get("content", []) if c.get("type") == "text"]
            if len(texts) == 1:
                key = args["provider"] + "-" + str(args.get("input", {}).get("service", args.get("input", {}).get("event", "directory"))).replace("/", "-")
                try:
                    obj = json.loads(texts[0])
                except json.JSONDecodeError as error:
                    catalog_errors.append({"key":key,"call_id":call_id,"error":str(error),"reason":"actual tool surface truncated by result/spill policy"})
                    continue
                catalogs[key] = obj
                with (ROOT / ("live-api-v2-" + key + ".json")).open("x", encoding="utf-8") as stream:
                    json.dump(obj, stream, ensure_ascii=False, indent=2)
summary = {"schema":"e5-zero-unit-inspection-export-v1", "source_sha256":hashlib.sha256(SOURCE.read_bytes()).hexdigest(), "session_id":records[0]["id"], "event_count":len(records)-1, "call_count":len(calls), "catalogs":sorted(catalogs), "catalog_errors":catalog_errors,"logical_e5_units":0, "preset":None, "science_mode_verified":False, "redaction":"remove thinking/reasoning blocks; sequence retained"}
with (ROOT / "runtime-inspection.export-summary-v2.json").open("x", encoding="utf-8") as stream:
    json.dump(summary, stream, ensure_ascii=False, indent=2)
print(json.dumps(summary, ensure_ascii=False, indent=2))
