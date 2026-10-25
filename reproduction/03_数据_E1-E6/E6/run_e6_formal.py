"""E6 真实 agent 编排：独立上下文、逐步实调工具、不可覆盖续跑。"""
# 标准库和第三方：CLI、JSON、时间、文件及任务 YAML。
import argparse
import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import yaml
# 项目生产工具和本轮独立实验设施。
from common_e6 import HERE, ROOT, PILOT, config, now, fp, read, write, encode
from model_e6 import ModelAPI, final_text, function_schemas
from trace_e6 import Trace, validate
from transport_e6 import Transport, freeze_bank
from src.ai_tools import ToolBox, TOOL_NAMES
from src.client import BestClient
from evals.repro.normalize import norm_args

def load_tasks():
    """读取原始 32 题，不注入坐标、会话或预写工具调用。"""
    return {p.stem: yaml.safe_load(p.read_text()) for p in sorted((ROOT / "evals/repro/tasks").glob("*.yaml"))}

def parse_final(text):
    """解码生成端声明的结论卡，保留最终原文供当前助手逐项复核。"""
    content = text.strip()
    if content.startswith("```json") and content.endswith("```"):
        content = content[7:-3].strip()
    try:
        value = json.loads(content)
    except ValueError:
        raise ValueError("最终输出不是已冻结要求的 JSON；原文保留，不当成功答案") from None
    if not isinstance(value, dict) or not isinstance(value.get("answer"), str) or not value["answer"].strip():
        raise ValueError("最终答案字段缺失")
    card = value.get("conclusion_card")
    if not isinstance(card, dict) or card.get("kind") not in ("value", "rowset", "refusal", "clarification", "none"):
        raise ValueError("结论卡类别缺失或非法")
    for key in ("key_numbers", "key_entities", "caveats"):
        if not isinstance(card.get(key), list):
            raise ValueError("结论卡缺字段 " + key)
    return value

def verify_frozen(batch, api):
    """每次启动验证采集代码、材料与请求参数没有悄悄改变。"""
    manifest = read(batch / "run_manifest.json")
    if api.parameters() != manifest["sampling"]["actual_request_parameters"]:
        raise ValueError("请求配置已改变，必须建立新批次")
    if api.endpoint != manifest['model']['endpoint']:
        raise ValueError("模型端点已改变，必须建立新批次")
    for rel, expected in manifest["collection_code"]["files"].items():
        if fp((HERE / rel).read_text()) != expected:
            raise ValueError("采集代码漂移，必须新批次：" + rel)
    for rel, expected in manifest["eval_data"]["task_files"].items():
        if fp((ROOT / rel).read_text()) != expected:
            raise ValueError("任务漂移，拒绝混批")
    from evals.repro.manifest import skill_fingerprint
    if skill_fingerprint() != manifest['skill']['fingerprint']:
        raise ValueError("生产代码/skill内容指纹漂移，拒绝混批")
    if fp((batch/'frozen/system-prompt.txt').read_text()) != manifest['system_prompt']['fingerprint']:
        raise ValueError("冻结提示被篡改")
    if fp(read(batch/'frozen/function-tools.json')) != manifest['tool_schema']['function_tools']:
        raise ValueError("冻结工具schema被篡改")
    for rel, expected in manifest['skill']['materials'].items():
        if fp((batch/'frozen/materials'/rel).read_text()) != expected:
            raise ValueError("冻结材料被篡改：" + rel)
    return manifest

def run_once(batch, lane, task_id, repeat, task, api, manifest, bank=None):
    """真正由模型决定调用；失败执行使用新的 attempt 文件。"""
    directory = batch / "lanes" / lane / task_id / f"repeat-{repeat}"
    completed = directory / "success.json"
    if completed.exists():
        previous = read(completed)
        events = [json.loads(s) for s in (directory / previous["trace"]).read_text().splitlines()]
        if validate(events, api.parameters()):
            raise ValueError("已成功记录核验失败，禁止覆盖重采")
        return "existing"
    directory.mkdir(parents=True, exist_ok=True)
    attempt = len(list(directory.glob("attempt-*.jsonl"))) + 1
    trace_name = f"attempt-{attempt}.jsonl"
    tw = Trace(directory / trace_name, f"{batch.name}-{lane}-{task_id}-{repeat}-{attempt}", task_id)
    stamp, start = now(), time.monotonic()
    tw.emit("run_start", {"manifest": manifest, "manifest_fp": fp(manifest), "lane": lane,
            "repeat": repeat, "execution_attempt": attempt, "task": task})
    client = BestClient(rate_limit=0.0 if bank is not None else 2.0)
    transport = Transport(client, tw.emit, bank)
    box = ToolBox(client)
    tools = read(batch / "frozen" / "function-tools.json")
    system = (batch / "frozen" / "system-prompt.txt").read_text()
    data_id = manifest["best_data"]["fingerprint_before"]
    context = [{"role": "system", "content": system},
               {"role": "user", "content": task["utterance"] + "\n\n实验运行数据标识（仅供引用）：" + data_id}]
    calls, envelopes, usage, models = [], [], [], []
    result = {"task_id": task_id, "lane": lane, "repeat": repeat, "trace": trace_name,
              "started_at": stamp, "generated_card_requires_assistant_review": True}
    current_call_seq = None
    try:
        for turn in range(16):
            body = api.call(context, tools, tw.emit)
            usage.append(body.get("usage"))
            models.append(body["model"])
            context.extend(body["output"])
            function_calls = [item for item in body["output"] if item.get("type") == "function_call"]
            if not function_calls:
                text = final_text(body)
                value = parse_final(text)
                card = value["conclusion_card"]
                if card["kind"] == "clarification":
                    clarification = value.get("clarification") or {}
                    tw.emit("clarification", {"missing_dims": clarification.get("missing_dims", []),
                            "options": clarification.get("options", []), "turn_index": turn})
                tw.emit("final_answer", {"answer_fp": fp(value["answer"]), "answer_text": value["answer"],
                        "raw_final_text": text, "conclusion_card": card,
                        "cited_uris": [e for e in card["key_entities"] if e.startswith("best://")]})
                result.update({"answer_text": value["answer"], "raw_final_text": text, "card": card,
                               "clarification": value.get("clarification"), "completed": True})
                break
            for call in function_calls:
                name = call["name"]
                args = json.loads(call["arguments"])
                entry = {"tool": name, "args": args, "args_norm": norm_args(args), "args_fp": fp(args),
                         "model_call": call}
                call_event = tw.emit("tool_call", entry, layer="tool")
                current_call_seq = call_event["seq"]
                before_requests, before_wait, before_miss = transport.session_requests, transport.wait_s, len(transport.misses)
                if name not in TOOL_NAMES:
                    raise ValueError("模型请求未注册工具：" + name)
                try:
                    envelope = getattr(box, name)(**args).to_dict()
                except TypeError as exc:
                    # 真实参数错误反馈，不自动修正模型参数。
                    envelope = {"data": {"error": str(exc)}, "status": {"ok": False, "error_code": "E_INVALID_INPUT", "truncated": False},
                                "cost": {"http_requests": transport.session_requests - before_requests, "elapsed_s": 0.0, "rows_returned": 0},
                                "provenance": {"session_id": None, "data_hash": fp({"error": str(exc)}), "stable_uri": "", "lineage": args}}
                tw.emit("tool_result", {"envelope": envelope, "envelope_fp": fp(envelope),
                        "status": envelope["status"], "cost": envelope["cost"], "provenance": envelope["provenance"],
                        "observed_session_requests": transport.session_requests - before_requests,
                        "rate_limit_wait_s": transport.wait_s - before_wait,
                        "snapshot_misses": transport.misses[before_miss:]}, layer="tool", parent_seq=current_call_seq)
                current_call_seq = None
                calls.append({"tool": name, "args": args})
                envelopes.append(envelope)
                if envelope["status"].get("ok") is False:
                    tw.emit("error", {"layer": "tool", "error_code": envelope["status"].get("error_code"),
                            "is_retryable": envelope["status"].get("error_code") in ("E_BACKEND", "E_SOFT_404"),
                            "detail": envelope["data"]}, layer="tool", parent_seq=call_event["seq"])
                context.append({"type": "function_call_output", "call_id": call["call_id"], "output": json.dumps(envelope, ensure_ascii=False)})
        else:
            raise RuntimeError("agent 超过冻结的 16 模型回合上限，保留未完成轨迹")
        if transport.misses:
            raise RuntimeError("R3 含未冻结的网络请求，不能算有效回放")
    except Exception as exc:
        tw.emit("error", {"layer": "harness", "error_code": type(exc).__name__, "is_retryable": False,
                "detail": str(exc)}, parent_seq=current_call_seq)
        result.update({"completed": False, "error": str(exc)})
    wall = time.monotonic() - start
    kind = result.get("card", {}).get("kind")
    outcome = ("clarify" if kind == "clarification" else "reject" if kind == "refusal" else "success") if result["completed"] else "fail"
    tw.emit("run_end", {"total_requests": transport.session_requests, "total_elapsed_s": wall, "outcome": outcome})
    errors = validate(tw.events, api.parameters())
    tw.close()
    box.client.close()
    result.update({"ended_at": now(), "wall_s": wall, "rate_limit_wait_s": transport.wait_s,
                   "tool_calls": calls, "envelopes": envelopes, "usage_raw": usage, "returned_models": models,
                   "cost": {"http_requests": transport.session_requests, "elapsed_s": sum(e["cost"]["elapsed_s"] for e in envelopes),
                            "rows_returned": sum(len(e["data"].get("rows", [])) for e in envelopes)},
                   "snapshot_misses": transport.misses, "outcome": outcome, "validation_errors": errors,
                   "events_fp": fp(tw.events)})
    valid = result["completed"] and not errors
    write(directory / f"attempt-{attempt}-result.json", result)
    if valid:
        write(completed, result)
    return "success" if valid else "failed"

def run_lane(batch, lane, selected=None):
    """同日单并发跑批；前后真实 canary、续跑保留所有失败尝试。"""
    from prepare_e6 import canary
    values = config()
    api = ModelAPI(values)
    manifest = verify_frozen(batch, api)
    tasks = load_tasks()
    selected = selected or (PILOT if lane == "pilot" else sorted(tasks))
    snapshot = read(batch / "snapshot_manifest.json") if lane == "R3" else None
    if snapshot is not None and fp(snapshot['bank']) != snapshot['fingerprint']:
        raise ValueError("冻结快照数据被篡改，拒绝回放")
    bank = snapshot['bank'] if snapshot is not None else None
    if snapshot is not None:
        manifest = {**manifest, 'eval_data': {**manifest['eval_data'], 'snapshot_status':'frozen',
                    'snapshot_id':batch.name+'-actual-request-bank', 'snapshot_manifest_fp':snapshot['fingerprint']}}
    session_id = str(time.time_ns())
    if bank is None:
        before = canary(batch / "canary" / lane / f"{session_id}-before")
        manifest = {**manifest,'actual_online_canary_before':before}
    else:
        before = None
    started = now()
    counts = {}
    for task_id in selected:
        for repeat in range(1, 6):
            if bank is None and datetime.fromisoformat(now()).date() != datetime.fromisoformat(started).date():
                write(batch / "failures" / f"{session_id}-cross-day.json", {"lane": lane, "started": started, "ended": now()})
                raise RuntimeError("在线批次跨上海日界，停止并记录，不能冒充同日 R1")
            status = run_once(batch, lane, task_id, repeat, tasks[task_id], api, manifest, bank)
            counts[status] = counts.get(status, 0) + 1
            print(json.dumps({"at": now(), "lane": lane, "task": task_id, "repeat": repeat, "status": status}), flush=True)
    if bank is None:
        after = canary(batch / "canary" / lane / f"{session_id}-after")
        rerun = canary(batch / "canary" / lane / f"{session_id}-confirm") if before["fingerprint"] != after["fingerprint"] else None
        state = "STABLE" if before["fingerprint"] == after["fingerprint"] else "DRIFTED"
        write(batch / "canary" / lane / f"{session_id}-gate.json", {"before": before, "after": after,
              "rerun": rerun, "drift_state": state, "all_probes_valid": before["all_valid"] and after["all_valid"]})
    write(batch / "sessions" / f"{lane}-{session_id}.json", {"started_at": started, "ended_at": now(), "counts": counts,
          "lane": lane, "selected": selected, "crossed_utc_midnight": datetime.fromisoformat(started).astimezone(ZoneInfo("UTC")).date() !=
          datetime.fromisoformat(now()).astimezone(ZoneInfo("UTC")).date()})
    if lane == "R1" and len({p.parent for p in (batch / "lanes/R1").glob("*/repeat-*/attempt-*-result.json")}) == 160:
        finish = datetime.fromisoformat(now())
        due = finish.date() + timedelta(days=7)
        if not (batch / "R2-CONDITIONS.json").exists():
            write(batch / "R2-CONDITIONS.json", {"r1_completed_at": finish.isoformat(), "due_date_Asia_Shanghai": due.isoformat(),
                  "timezone": "Asia/Shanghai", "repeat": 5, "tasks": 32, "automation": False,
                  "requirements": ["复查模型权限、回包模型和请求参数；权重快照 opaque", "代码、材料、任务、schema 指纹一致", "前后五星表真实 canary + count，漂移移交 E7"],
                  "command": f"temp/e3-e6/venv/bin/python temp/e6-formal/run_e6_formal.py --batch {batch.name} --lane R2"})
    return counts

def main():
    """CLI 只在明确选路后执行真实采集；R2 校验日期。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", required=True)
    parser.add_argument("--lane", choices=["pilot", "R1", "R2", "R3"])
    parser.add_argument("--freeze-snapshot", action="store_true")
    parser.add_argument("--tasks", nargs="+")
    args = parser.parse_args()
    batch = (HERE / "batches" / args.batch).resolve()
    if not batch.is_relative_to(HERE / "batches"):
        raise ValueError("批次路径越界")
    if args.freeze_snapshot:
        paths = sorted((batch / "lanes/pilot").glob("*/repeat-*/attempt-*.jsonl")) + sorted((batch / "lanes/R1").glob("*/repeat-*/attempt-*.jsonl"))
        freeze_bank(paths, batch / "snapshot_manifest.json")
    elif args.lane:
        if args.lane == "R2":
            conditions = read(batch / "R2-CONDITIONS.json")
            if datetime.fromisoformat(now()).date().isoformat() != conditions["due_date_Asia_Shanghai"]:
                raise ValueError("R2 必须在已记录 D+7 日期执行，本轮不等待、不创建自动化")
        run_lane(batch, args.lane, args.tasks)
    else:
        parser.error("需要指定 --lane 或 --freeze-snapshot")

if __name__ == "__main__":
    main()
