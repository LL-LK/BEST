"""E3 实验编排：连接检查、固定查询、回答续跑、模型评分及反证门槛。"""
from __future__ import annotations

# 标准库：批次互斥、运行记录、受控串行调用和错误归档。
import contextlib
import fcntl
import json
import sys
from pathlib import Path

# 本轮载体：所有网络产物只存本轮临时批次。
from common import (GROUPS, HERE, PILOT, anonymous, config, encode, fingerprint,
                    now, public_config, read_json, record_key, write_json)
from api_client import APIError, ModelAPI, parse_score, extract_text
from prepare import fixture_data, subject_input, verify_bundle
from scoring import control_passed, controls, judge_input, validate_score
from live_data import collect_live

# 仓内机器预筛：只做提示，不把规则扫描升级成模型或专家判分。
from evals.semantics.prescreen import prescreen


@contextlib.contextmanager
def batch_lock(batch: Path):
    """防止两个进程同时采集同批，保护已成功回答和计费请求。"""
    with (batch / ".run.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("该批次已有进程运行，禁止重复启动") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def configured_api(batch: Path) -> ModelAPI:
    """网络调用前核验配置与冻结清单；密钥变化不改变实验设计。"""
    values, missing = config()
    if missing:
        write_json(HERE / "needs-input.json", {"missing": missing, "checked_at": now(), "network_called": False})
        raise ValueError("需要填写 .env：" + "；".join(missing))
    manifest = read_json(batch / "manifest.json")
    if manifest["config"] != public_config(values):
        raise ValueError("API配置已改变，请先运行 prepare 创建对应的新批次")
    return ModelAPI(values)


def failed(batch: Path, label: str, exc: Exception, extra=None) -> None:
    """失败调用另存唯一记录，绝不写入成功回答目录。"""
    import time
    value = {"label": label, "at": now(), "error_type": type(exc).__name__,
             "error": str(exc), "attempts": getattr(exc, "attempts", []), "context": extra}
    write_json(batch / "failures" / f"{label}-{time.time_ns()}.json", value)


def check_model(batch: Path, role: str, result: dict) -> None:
    """实际返回模型必须与本批连接检查一致，漂移时停止。"""
    expected = read_json(batch / "connection.json")["returned_models"][role]
    if result["returned_model"] != expected:
        raise ValueError("供应商实际返回模型改变，需要新批次，不混合不同模型结果")


def connection_check(batch: Path) -> dict:
    """实测两种角色的有效参数和评分结构；不是权限猜测或空探测。"""
    bundle = verify_bundle(batch)
    api = configured_api(batch)
    path = batch / "connection.json"
    if path.exists():
        return read_json(path)
    item = next(i for i in bundle["items"] if i["id"] == "E3-A01")
    generated = judged = None
    try:
        generated = api.call("test", bundle["contexts"]["S-A"], subject_input(bundle, item))
        data = fixture_data(bundle["fixtures"][item["fixture"]])
        if api.values.get("E3_JUDGE_MODE") == "assistant":
            result = {"ok": True, "checked_at": now(), "returned_models": {"test": generated["returned_model"]},
                      "generation": generated, "judge": None, "judge_mode": "current_assistant",
                      "note": "连接检查不计入216份回答；未调用评分API；主评反证另行完成"}
            write_json(path, result)
            return result
        judged = api.call("judge", bundle["judge_system"], judge_input(bundle, item, generated["answer"], data))
        score = parse_score(judged["answer"])
        validate_score(score, item, generated["answer"])
        result = {"ok": True, "checked_at": now(), "returned_models": {
                    "test": generated["returned_model"], "judge": judged["returned_model"]},
                  "generation": generated, "judge": judged,
                  "note": "连接检查样本不计入216份实验回答；未发送的温度参数未视为固定"}
        write_json(path, result)
        return result
    except (APIError, ValueError) as exc:
        failed(batch, "connection", exc, {"generation": generated, "judge": judged})
        raise


def validate_call(batch: Path, role: str, api_record: dict, system: str, user: str) -> None:
    """请求参数与真实回包共同校验，不能只信保存的汇总字段。"""
    manifest = read_json(batch / "manifest.json")
    values = {**manifest["config"], "E3_API_KEY": ""}
    expected = ModelAPI(values).payload(role, system, user)
    if api_record["request"] != expected:
        raise ValueError("真实请求参数与冻结方案不一致")
    last = api_record["attempts"][-1]
    if not 200 <= last.get("http_status", 0) < 300:
        raise ValueError("成功记录缺少真实成功HTTP响应")
    raw = last["response"]
    if (extract_text(raw, values["E3_API_STYLE"]) != api_record["answer"]
            or raw.get("model") != api_record["returned_model"] or raw.get("usage") != api_record["usage"]):
        raise ValueError("保存的模型输出、来源或用量与原始回包不一致")
    check_model(batch, role, api_record)


def live_for(batch: Path, item: dict, repeat: int) -> dict:
    """同题同重复仅采集一次实际回包，两组共享，重跑不再次查站点。"""
    path = batch / "live" / f"{item['id']}_r{repeat}.json"
    if not path.exists():
        record = collect_live(item, repeat)
        write_json(path, record)
    record = read_json(path)
    if fingerprint(record["public_data"]) != record["data_hash"]:
        raise ValueError("在线冻结回包被修改")
    return record


def validate_answer(record: dict, batch: Path, bundle: dict) -> None:
    """核验成功记录的输入、输出和绑定数据，篡改不能进入评分。"""
    item = next(i for i in bundle["items"] if i["id"] == record["item_id"])
    group, repeat = record["group"], record["repeat"]
    if record_key(group, item["id"], repeat) != record["key"] or record["batch_id"] != batch.name:
        raise ValueError("回答记录身份不匹配")
    if record["tier"] != item["tier"] or record["axis"] != item["axis"]:
        raise ValueError("回答的主辅测类型或语义轴被修改")
    if not record.get("answer") or fingerprint(record["answer"]) != record["answer_hash"]:
        raise ValueError("回答被修改或为空")
    if record["api"]["answer"] != record["answer"]:
        raise ValueError("回答与真实模型输出不同")
    if item["tier"] == "fixture":
        data = fixture_data(bundle["fixtures"][item["fixture"]])
        user = subject_input(bundle, item)
    else:
        live_path = batch / "live" / f"{item['id']}_r{repeat}.json"
        live = read_json(live_path)
        if fingerprint(live["public_data"]) != live["data_hash"]:
            raise ValueError("在线回包内容被修改")
        data = live["public_data"]
        user = subject_input(bundle, item, live)
    if record["data_hash"] != fingerprint(data) or record["data"] != data:
        raise ValueError("回答绑定的数据发生变化")
    api_input = record["api"]["request"].get("input", record["api"]["request"].get("messages"))
    if api_input != [{"role": "system", "content": bundle["contexts"][group]}, {"role": "user", "content": user}]:
        raise ValueError("生成请求与冻结上下文不同")
    validate_call(batch, "test", record["api"], bundle["contexts"][group], user)


def collect(batch: Path, pilot=False) -> list[dict]:
    """采集独立模型回答；成功文件不可覆盖，失败保留并允许后续续跑。"""
    bundle = verify_bundle(batch)
    api = configured_api(batch)
    if not (batch / "connection.json").exists():
        raise ValueError("请先通过 check 连接检查")
    if not pilot and not read_json(batch / "pilot.json").get("passed"):
        raise ValueError("试运行未通过，禁止全量采集")
    items = [i for i in bundle["items"] if not pilot or i["id"] in PILOT]
    from concurrent.futures import ThreadPoolExecutor
    collected = []
    pending = []
    def execute(job):
        item, group, repeat, live, data, key, path = job
        print(f"采集 {key}", flush=True)
        # 每个任务独立HTTP会话与模型上下文，不共享requests.Session。
        worker = configured_api(batch)
        try:
            call = worker.call("test", bundle["contexts"][group], subject_input(bundle, item, live))
            check_model(batch, "test", call)
            record = {"batch_id": batch.name, "key": key, "group": group,
                      "item_id": item["id"], "axis": item["axis"], "tier": item["tier"],
                      "repeat": repeat, "data": data, "data_hash": fingerprint(data),
                      "answer": call["answer"], "answer_hash": fingerprint(call["answer"]), "api": call}
            write_json(path, record)
            return record
        except (APIError, ValueError) as exc:
            failed(batch, key, exc)
            raise
        finally:
            worker.session.close()
    def drain(executor):
        # 每四份为一波，失败时等待在途任务归档，不再派发后续任务。
        futures = [executor.submit(execute, job) for job in pending]
        pending.clear()
        errors = []
        for future in futures:
            try:
                collected.append(future.result())
            except (APIError, ValueError) as exc:
                errors.append(exc)
        if errors:
            raise errors[0]
    with ThreadPoolExecutor(max_workers=4) as executor:
        for repeat in (1, 2, 3):
            for item in items:
                live = live_for(batch, item, repeat) if item["tier"] == "live" else None
                data = live["public_data"] if live else fixture_data(bundle["fixtures"][item["fixture"]])
                for group in GROUPS:
                    key = record_key(group, item["id"], repeat)
                    path = batch / "answers" / f"{key}.json"
                    if path.exists():
                        record = read_json(path)
                        validate_answer(record, batch, bundle)
                        collected.append(record)
                    else:
                        pending.append((item, group, repeat, live, data, key, path))
                    if len(pending) == 4:
                        drain(executor)
        if pending:
            drain(executor)
    return collected


def all_answers(batch: Path, bundle: dict) -> list[dict]:
    """加载并核验已有回答，不把缺失回答当作空回答。"""
    records = []
    seen = set()
    for path in sorted((batch / "answers").glob("*.json")):
        record = read_json(path)
        validate_answer(record, batch, bundle)
        if path.stem != record["key"] or record["key"] in seen:
            raise ValueError("回答文件名与记录不匹配或重复")
        seen.add(record["key"])
        records.append(record)
    return records


def prescreen_all(batch: Path) -> dict:
    """预筛原始回答；在线数据动态绑定，结果始终标为机器提示。"""
    bundle = verify_bundle(batch)
    lookup = {i["id"]: i for i in bundle["items"]}
    results = {}
    for record in all_answers(batch, bundle):
        item = dict(lookup[record["item_id"]])
        fixtures = bundle["fixtures"]
        if record["tier"] == "live":
            item["fixture"] = "current_live"
            fixtures = {"current_live": record["data"]}
        results[record["key"]] = prescreen(record["answer"], item, fixtures)
    write_json(batch / "prescreen.json", {"only_flags": True, "answered": len(results), "results": results})
    return results


def score_one(batch: Path, bundle: dict, item: dict, answer: str, data: dict, key: str, api: ModelAPI) -> dict:
    """评分采用独立请求；结构错误有限重试，不使用上次分数提示。"""
    path = batch / "scores" / f"{key}.json"
    input_text = judge_input(bundle, item, answer, data)
    input_hash = fingerprint(input_text)
    if path.exists():
        record = read_json(path)
        if record["input_hash"] != input_hash:
            raise ValueError("既有评分与本次匿名输入不同，需要新批次")
        if api.values.get("E3_JUDGE_MODE") == "assistant":
            from assistant_review import verify_assistant_record
            verify_assistant_record(batch, record)
            counts = validate_score(record["score"], item, answer)
            if counts != record["counts"]:
                raise ValueError("既有评分计数被修改")
            return record
        check_model(batch, "judge", record["api"])
        validate_call(batch, "judge", record["api"], bundle["judge_system"], input_text)
        if parse_score(record["api"]["answer"]) != record["score"]:
            raise ValueError("保存的评分不是原始主评模型输出")
        counts = validate_score(record["score"], item, answer)
        if counts != record["counts"]:
            raise ValueError("既有评分计数被修改")
        return record
    if api.values.get("E3_JUDGE_MODE") == "assistant":
        from assistant_review import export_assistant
        export_assistant(batch)
        raise ValueError("当前助手评分尚未完成；见 assistant-review，禁止调用评分API")
    for trial in range(2):
        call = None
        try:
            call = api.call("judge", bundle["judge_system"], input_text)
            check_model(batch, "judge", call)
            score = parse_score(call["answer"])
            counts = validate_score(score, item, answer)
            record = {"key": key, "input_hash": input_hash, "score": score, "counts": counts, "api": call}
            write_json(path, record)
            return record
        except APIError as exc:
            failed(batch, "judge-"+key, exc)
            raise
        except ValueError as exc:
            failed(batch, "judge-"+key, exc, {"api": call, "structural_attempt": trial+1})
            if trial == 1:
                raise
    raise ValueError("评分未完成")


def judge_controls(batch: Path, bundle: dict, api: ModelAPI) -> dict:
    """主评模型必须检出三份隐藏反证；失败即阻断正式评分。"""
    results = {}
    for control in controls(bundle):
        record = score_one(batch, bundle, control["item"], control["answer"], control["data"], control["control_id"], api)
        results[control["control_id"]] = control_passed(control["control_id"], record["counts"])
    status = {"passed": all(results.values()), "metascore": sum(results.values())/3, "results": results}
    write_json(batch / "judge-selftest.json", status)
    if not status["passed"]:
        raise ValueError("GPT主评未检出全部反证；禁止正式判分，修订后必须新批次")
    return status


def grade(batch: Path, pilot=False) -> list[dict]:
    """先跑反证再评真实回答；任何缺项记录不能进入科学统计。"""
    bundle = verify_bundle(batch)
    api = configured_api(batch)
    judge_controls(batch, bundle, api)
    lookup = {i["id"]: i for i in bundle["items"]}
    records = all_answers(batch, bundle)
    records = [r for r in records if not pilot or r["item_id"] in PILOT]
    results = []
    for record in records:
        print("评分 " + record["key"], flush=True)
        result = score_one(batch, bundle, lookup[record["item_id"]], record["answer"], record["data"], record["key"], api)
        results.append({**record, "counts": result["counts"], "score": result["score"]})
    if pilot:
        status = {"answered": len(records), "scored": len(results), "expected": 42,
                  "passed": len(records) == 42 and len(results) == 42,
                  "meaning": "采集结构与反证门槛通过；不是模型表现达标，也不是双专家κ校准"}
        write_json(batch / "pilot.json", status)
        if not status["passed"]:
            raise ValueError("七题两组各三次试运行不完整")
    return results
