"""R0 固化客户端调用：复用18条原序列，保存工具及网络实际回包。"""
# 标准库：CLI、JSON、时间及数据载体。
import json
import time
# 项目已有离线序列、回放及自证；不引入模型。
from common_e6 import HERE, ROOT, read, write, fp, now
from trace_e6 import Trace
from evals.repro.r0_lane import R0_SEQUENCES, FIXTURES_DIR, run_lane
from evals.repro.transport import ReplayTransport
from evals.repro.normalize import norm_args
from evals.repro.broken import run_broken_selftest
from src.client import BestClient
from src.ai_tools import ToolBox

def run(batch):
    """实际重复5次，明确与真实agent的可用性不同。"""
    if not (batch / "R0-original-runs.json").exists():
        write(batch / "R0-original-runs.json", run_lane(repeat=5))
        write(batch / "R0-original-selftest.json", run_broken_selftest())
    lane_dir = "R0-corrected" if (batch / "lanes/R0").exists() else "R0"
    write(batch / ("R0-code-" + str(time.time_ns()) + ".json"), {"code_fp": fp(__import__('pathlib').Path(__file__).read_text()),
          "lane_dir": lane_dir, "correction": "原临时R0对list_catalogs误用不存在客户端方法；失败原件保留，纠正后独立采集"})
    manifest = read(batch / "run_manifest.json")
    for task_id, (fixture, sequence) in sorted(R0_SEQUENCES.items()):
        for repeat in range(1, 6):
            directory = batch / "lanes" / lane_dir / task_id / f"repeat-{repeat}"
            tw = Trace(directory / "attempt-1.jsonl", f"R0-{task_id}-{repeat}", task_id)
            tw.emit("run_start", {"manifest": manifest, "fixture": fixture, "fixed_sequence": sequence,
                    "note": "无模型客户端工具地板；预写调用仅在R0允许"})
            transport = ReplayTransport(FIXTURES_DIR / fixture)
            client = BestClient(base_url="http://replay.local", rate_limit=0.0)
            def capture(method, url, kwargs):
                """保存夹具原文及真实固定序列请求，不虚构在线 canary。"""
                response = getattr(transport, method)(url, **kwargs)
                tw.emit("network_exchange", {"mode": "fixture", "method": method, "url": url,
                        "args": kwargs, "response": {"status": response.status_code, "text": response.text}}, layer="network")
                return response
            def get(url, **kwargs):
                """固定夹具 GET 包装器。"""
                return capture("get", url, kwargs)
            def post(url, **kwargs):
                """固定夹具 POST 包装器。"""
                return capture("post", url, kwargs)
            client.session.get, client.session.post = get, post
            start, stamp = time.monotonic(), now()
            sid, calls, envelopes = None, [], []
            for step in sequence:
                name, args = step["tool"], dict(step["args"])
                ce = tw.emit("tool_call", {"tool": name, "args": args, "args_norm": norm_args(args), "args_fp": fp(args)}, layer="tool")
                before, t0 = transport.call_count, time.monotonic()
                status = {"ok": True, "error_code": None, "truncated": False}
                try:
                    if name == "cone_search":
                        value = client.cone_search(**args)
                        sid = value.query_params.get("sqlid")
                        data = {"rows": [s.to_dict() for s in value.sources], "total_count": value.total_count,
                                "returned_count": value.returned_count}
                        status.update({"ok": value.success, "error_code": value.error_code, "truncated": value.truncated})
                    elif name == "fetch_page":
                        value = client.fetch_page(sid or "s9001", page=args.get("page", 2), page_size=args.get("page_size", 5), catalog="ps1")
                        data = {"rows": [s.to_dict() for s in value.sources], "total_count": value.total_count}
                        status.update({"ok": value.success, "error_code": value.error_code, "truncated": value.truncated})
                    elif name == "count":
                        data = {"total": client.count(sid or "s9001")}
                        status["ok"] = data["total"] is not None
                    elif name == "crossmatch_batch":
                        value = client.crossmatch_batch(**args)
                        data = {"rows": [s.to_dict() for s in value.sources], "total_count": value.total_count}
                        status.update({"ok": value.success, "error_code": value.error_code})
                    elif name == "list_catalogs":
                        data = ToolBox(client).list_catalogs().to_dict()["data"]
                    elif name == "describe_catalog":
                        data = {"columns": client.describe_columns(args["catalog"])}
                except Exception as exc:
                    status = {"ok": False, "error_code": "E_INVALID_INPUT", "truncated": False}
                    data = {"error": str(exc)}
                cost = {"http_requests": transport.call_count - before, "elapsed_s": time.monotonic() - t0,
                        "rows_returned": len(data.get("rows", []))}
                envelope = {"data": data, "status": status, "cost": cost,
                            "provenance": {"session_id": sid, "data_hash": fp(data), "stable_uri": "fixture:" + fixture, "lineage": args}}
                tw.emit("tool_result", {"envelope": envelope, "envelope_fp": fp(envelope), "status": status, "cost": cost,
                        "provenance": envelope["provenance"], "observed_session_requests": cost["http_requests"], "snapshot_misses": []},
                        layer="tool", parent_seq=ce["seq"])
                calls.append({"tool": name, "args": args})
                envelopes.append(envelope)
            failed = any(not e["status"]["ok"] for e in envelopes)
            card = {"kind": "refusal" if failed else "rowset", "key_numbers": [{"field": "row_count", "value": sum(len(e["data"].get("rows", [])) for e in envelopes)}],
                    "key_entities": ["fixture:" + fixture] + sorted({e["status"]["error_code"] for e in envelopes if e["status"]["error_code"]}), "caveats": []}
            answer = "R0固定序列地板结果；不是用户可用性或模型答案"
            tw.emit("final_answer", {"answer_text": answer, "answer_fp": fp(answer), "conclusion_card": card})
            tw.emit("run_end", {"total_requests": transport.call_count, "total_elapsed_s": time.monotonic() - start,
                    "outcome": "fail" if failed else "success"})
            tw.close()
            client.close()
            record = {"task_id": task_id, "lane": "R0", "repeat": repeat, "completed": True, "trace": "attempt-1.jsonl",
                      "started_at": stamp, "ended_at": now(), "tool_calls": calls, "envelopes": envelopes, "card": card,
                      "answer_text": answer, "wall_s": time.monotonic() - start, "rate_limit_wait_s": 0,
                      "usage_raw": [], "outcome": "fail" if failed else "success", "validation_errors": [], "events_fp": fp(tw.events)}
            write(directory / "success.json", record)
    print(json.dumps({"R0_tasks": 18, "runs": 90, "original_selftest": read(batch / "R0-original-selftest.json")["pass"]}))

if __name__ == "__main__":
    run(HERE / "batches" / read(HERE / "current.json")["batch"])
