"""E6 trace 扩展：不可覆盖写入、逐调用配对、真实网络成本与时序验证。"""
# 标准库：JSONL、单调时钟和字段检查。
import json
import time
from datetime import datetime
# 项目与临时设施：沿用事件必填字段，修正零请求误报。
from evals.repro.trace import PAYLOAD_REQUIRED
from common_e6 import fp, utc, redact, SECRETS

class Trace:
    """一次执行一个新文件，失败文件也不截断覆盖。"""
    def __init__(self, path, run_id, task_id):
        """独占创建 trace，逐事件立即刷盘。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = path.open("x", encoding="utf-8")
        path.chmod(0o600)
        self.run_id, self.task_id = run_id, task_id
        self.events = []
        self.start = time.monotonic()

    def emit(self, kind, payload, layer="harness", attempt=1, parent_seq=None):
        """写入安全事件及独立指纹。"""
        payload = redact(payload)
        missing = [k for k in PAYLOAD_REQUIRED.get(kind, ()) if k not in payload]
        if missing:
            raise ValueError(f"事件缺字段 {kind}: {missing}")
        event = {"seq": len(self.events), "ts_utc": utc(), "ts_mono": time.monotonic() - self.start,
                 "run_id": self.run_id, "task_id": self.task_id, "attempt": attempt,
                 "parent_seq": parent_seq, "layer": layer, "type": kind,
                 "payload": payload, "payload_fp": fp(payload)}
        self.handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.handle.flush()
        self.events.append(event)
        return event

    def close(self):
        """保留完整和失败轨迹原件。"""
        self.handle.close()

def validate(events, parameters=None):
    """核验配对、时间、指纹、usage 与成本；不把零网络工具视为造假。"""
    errors = []
    calls, answered = {}, set()
    previous_time, previous_utc = -1, None
    for index, event in enumerate(events):
        for key in ("seq", "ts_utc", "ts_mono", "run_id", "task_id", "attempt", "parent_seq", "layer", "type", "payload", "payload_fp"):
            if key not in event:
                errors.append(f"missing_header:{index}:{key}")
        if event.get("seq") != index:
            errors.append(f"seq_gap:{index}")
        payload = event.get("payload", {})
        if event.get("payload_fp") != fp(payload):
            errors.append(f"payload_tampered:{index}")
        for key in PAYLOAD_REQUIRED.get(event.get("type"), ()):
            if key not in payload:
                errors.append(f"missing_payload:{index}:{key}")
        mono = event.get("ts_mono", -1)
        try:
            stamp = datetime.fromisoformat(event["ts_utc"])
            if mono < previous_time or (previous_utc and stamp < previous_utc):
                errors.append(f"time_reversed:{index}")
            previous_time, previous_utc = mono, stamp
        except (ValueError, KeyError, TypeError):
            errors.append(f"bad_time:{index}")
        parent = event.get("parent_seq")
        if parent is not None and (not isinstance(parent, int) or not 0 <= parent < index):
            errors.append(f"bad_parent:{index}")
        if event.get("type") == "tool_call":
            calls[index] = event
            if payload.get("args_fp") != fp(payload.get("args")):
                errors.append(f"args_tampered:{index}")
        if event.get("type") == "tool_result":
            if parent not in calls or parent in answered:
                errors.append(f"tool_pairing:{index}")
            answered.add(parent)
            envelope = payload.get("envelope")
            if envelope is None or fp(envelope) != payload.get("envelope_fp"):
                errors.append(f"envelope_tampered:{index}")
            if payload.get("cost") != (envelope or {}).get("cost"):
                errors.append(f"cost_tampered:{index}")
            if envelope is not None and envelope.get('provenance', {}).get('data_hash') != fp(envelope.get('data')):
                errors.append(f"data_hash_mismatch:{index}")
            if payload.get("cost", {}).get("http_requests") != payload.get("observed_session_requests"):
                errors.append(f"cost_mismatch:{index}")
            if payload.get("snapshot_misses"):
                errors.append(f"snapshot_miss:{index}")
        if event.get("type") == "model_request" and parameters is not None:
            req = payload.get("request", {})
            actual = {k: v for k, v in req.items() if k not in ("input", "tools", "tool_choice")}
            if actual != parameters:
                errors.append(f"parameter_drift:{index}")
    if set(calls) != answered:
        errors.append("tool_pairing_incomplete")
    finals = [e for e in events if e.get("type") == "final_answer"]
    if len(finals) != 1:
        errors.append("final_answer_missing_or_duplicate")
    elif finals[0]["payload"].get("answer_fp") != fp(finals[0]["payload"].get("answer_text", "")):
        errors.append("answer_tampered")
    if not events or events[0].get("type") != "run_start" or events[-1].get("type") != "run_end":
        errors.append("run_boundary_missing")
    elif events[-1]['payload'].get('total_requests') != sum(e['payload'].get('cost', {}).get('http_requests', 0) for e in events if e.get('type') == 'tool_result'):
        errors.append('run_total_cost_mismatch')
    for secret in SECRETS:
        if secret and secret in json.dumps(events, ensure_ascii=False):
            errors.append("credential_leak")
    return errors
