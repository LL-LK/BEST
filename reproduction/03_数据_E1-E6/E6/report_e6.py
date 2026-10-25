"""E6 汇总交付：原始记录有效性、统计、语义卡、效率、可用性及R2条件。"""
# 标准库：命令行、CSV、JSON、时间和计数。
import argparse
import csv
import json
import time
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
# 临时及项目已有评测模块：评分不调用外部API。
from common_e6 import HERE, ROOT, config, fp, read, write, now
from trace_e6 import validate
from metrics_e6 import score_lane, score_task
from semantic_cards_e6 import semantic_card
from efficiency_usability_e6 import efficiency, usability, percentile
from statistics_e6 import cluster_ci
from wire_semantics_audit_e6 import wire_failures

def actual_dates(records):
    """报告真实尝试时间，不把初始manifest日期覆盖到跨日回放。"""
    starts = [datetime.fromisoformat(r['started_at']).astimezone(timezone.utc) for r in records if r.get('started_at')]
    ends = [datetime.fromisoformat(r['ended_at']).astimezone(timezone.utc) for r in records if r.get('ended_at')]
    first, last = min(starts) if starts else None, max(ends) if ends else None
    return {'actual_first_started_UTC':first.isoformat() if first else None,
            'actual_last_known_ended_UTC':last.isoformat() if last else None,
            'unknown_ended_at_attempts':sum(not r.get('ended_at') for r in records),
            'actual_dates_Asia_Shanghai':sorted({d.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat() for d in starts+ends}),
            'crossed_UTC_midnight':first.date()!=last.date() if first and last else None,
            'crossed_Asia_Shanghai_midnight':first.astimezone(ZoneInfo('Asia/Shanghai')).date()!=last.astimezone(ZoneInfo('Asia/Shanghai')).date() if first and last else None}

def model_api_failures(records, traces):
    """区分生成接口运营故障与BEST工具失败，未知usage不填零。"""
    attempts, statuses = [], Counter()
    for record, events in zip(records, traces):
        responses = [e['payload'] for e in events if e['type']=='model_response']
        errors = [p for p in responses if isinstance(p.get('http_status'), int) and p['http_status']>=400]
        if not errors:
            continue
        statuses.update(str(p['http_status']) for p in errors)
        balance = any(p['http_status']==402 and str((p.get('raw',{}).get('error') or {}).get('message','')).startswith('Insufficient Balance') for p in errors)
        attempts.append({'task_id':record['task_id'],'repeat':record['repeat'],'trace':record['trace'],
                         'http_statuses':[p['http_status'] for p in errors],'insufficient_balance':balance,
                         'known_usage_responses_before_failure':sum(p.get('usage') is not None for p in responses if p not in errors),
                         'native_tool_calls':sum(e['type']=='tool_call' for e in events),
                         'has_final_answer':any(e['type']=='final_answer' for e in events),
                         'errors':[p.get('raw',{}).get('error') for p in errors]})
    return {'failed_generation_responses':sum(statuses.values()),'affected_attempts':len(attempts),
            'http_status_counts':dict(statuses),'insufficient_balance_attempts':sum(a['insufficient_balance'] for a in attempts),
            'attempts':attempts,'scope':'生成模型API运营故障；不归为BEST后端或科学能力失败，未返回usage保持未知'}

def exact_canary(path):
    """独立复核原始行中的大整数ID，避免E2规范化转float丢精度。"""
    data = read(path)
    probes = []
    for probe in data['probes']:
        envelope, count = probe['envelope'], probe['count']
        rows = sorted(envelope['data'].get('rows', []), key=fp)
        probes.append({'args': probe['args'], 'rows': rows, 'status': envelope['status'],
                       'total': envelope['data'].get('total_count'), 'count': count['data'].get('total') if count else None,
                       'count_status': count['status'] if count else None})
    return 'bestfp:'+fp(probes)

def collect(batch, lane):
    """逐文件复核；失败不补答案、有效样本不足保留分母。"""
    source_lane = "R0-corrected" if lane == "R0" and (batch / "lanes/R0-corrected").exists() else lane
    grouped, runs, traces, validation = {}, [], [], []
    parameters = read(batch / "run_manifest.json")["sampling"]["actual_request_parameters"]
    for path in sorted((batch / "lanes" / source_lane).glob("*/repeat-*/success.json")):
        run = read(path)
        events = [json.loads(line) for line in (path.parent / run["trace"]).read_text().splitlines()]
        errors = validate(events, None if lane == "R0" else parameters)
        validation.append({"record": str(path.relative_to(batch)), "errors": errors})
        if errors:
            continue
        if lane != "R0":
            run['native_tool_call_count'] = sum(e['type']=='tool_call' for e in events)
            run['wire_semantic_failures'] = wire_failures(events)
            reviewed, diagnostics = semantic_card(run)
            run["reviewed_card"] = reviewed
            run["review_diagnostics"] = diagnostics
            run['retry_records'] = [e['payload'] for e in events if e['type']=='retry']
        grouped.setdefault(run["task_id"], []).append(run)
        runs.append(run)
        traces.append(events)
    attempts = list((batch / "lanes" / source_lane).glob("*/repeat-*/attempt-*.jsonl"))
    terminated = [read(p) for p in (batch / "lanes" / source_lane).glob("*/repeat-*/attempt-*-result.json")]
    if lane == 'R0':
        known = {(r['task_id'],r['repeat'],r['trace']) for r in terminated}
        terminated += [read(p) for p in (batch/'lanes'/source_lane).glob('*/repeat-*/success.json')
                       if (read(p)['task_id'],read(p)['repeat'],read(p)['trace']) not in known]
    failures = [r for r in terminated if not r.get("completed") or r.get("validation_errors")]
    failed_traces = [[json.loads(line) for line in (batch / "lanes" / source_lane / r["task_id"] / f"repeat-{r['repeat']}" / r["trace"]).read_text().splitlines()] for r in failures]
    failed_efficiency = efficiency(failures, failed_traces) if lane != "R0" and failures else None
    return grouped, runs, traces, {"validation": validation, "attempt_files": len(attempts), "failure_attempts": len(failures),
                                'actual_execution_dates':actual_dates(terminated),
                                'model_api_failures':model_api_failures(failures, failed_traces),
                                "planned_slot_attempted": len({str(p.parent) for p in attempts}),
                                "terminated_slots": len({(r['task_id'],r['repeat']) for r in terminated}),
                                "terminated_attempts": len(terminated),
                                "failure_efficiency": failed_efficiency,
                                "failures": [{k: r.get(k) for k in ("task_id", "repeat", "trace", "error", "snapshot_misses", "validation_errors")} for r in failures]}

def pilot_calibration(batch, out):
    """用10题×5真实记录标定观测量；原建议阈值不冒充校准。"""
    source = read(batch / "pilot-source.json")["batch"] if (batch / "pilot-source.json").exists() else batch.name
    pilot_batch = HERE / "batches" / source
    grouped, runs, events, audit = collect(pilot_batch, "pilot")
    all_runs, all_events = [], []
    for path in sorted((pilot_batch/'lanes/pilot').glob('*/repeat-*/attempt-*-result.json')):
        record = read(path)
        all_runs.append(record)
        all_events.append([json.loads(line) for line in (path.parent/record['trace']).read_text().splitlines()])
    metrics = efficiency(all_runs, all_events)
    valid_metrics = efficiency(runs, events)
    distributions = {"http_requests": metrics["http_requests"], "agent_wall_s": metrics["EF2"]["agent_wall_with_wait"],
                     "tool_steps": percentile([sum(e['type']=='tool_call' for e in ev) for ev in all_events])}
    lines = {k: {"warn": v["p90"], "fail": v["p90"] * 1.2 if v["p90"] is not None else None, "orientation": "higher_is_worse"}
             for k, v in distributions.items()}
    result = {"source_batch": source, "tasks": len(grouped), "records": len(runs), "complete_10x5": audit['planned_slot_attempted'] == 50,
              "all_50_valid": len(runs) == 50, "failure_attempts": audit['failure_attempts'],
              "metrics_all_attempts": metrics, "metrics_valid_records_only": valid_metrics,
              "distributions": distributions, "calibrated_observation_lines": lines,
              "initial_efficiency_ratio_thresholds": {"eta": .7, "redundancy": .1, "ineffective_retry": .05},
              "initial_threshold_status": "suggestions_only_not_calibrated_as_gate",
              "limitation": "异质任务的P90观测线仅诊断参考，不作为独立验证达标线；U7未评阅", "audit": audit}
    write(out / "pilot-calibration.json", result)
    return result

def generate(batch):
    """保存新的报告快照，不覆盖历史分数。"""
    config()
    out = batch / "reports" / str(time.time_ns())
    out.mkdir(parents=True)
    manifest = read(batch / "run_manifest.json")
    results = {}
    lanes = ['R0','R1','R3'] + (['R2'] if (batch/'lanes/R2').exists() else [])
    task_ids = sorted(p.stem for p in (batch/'frozen/tasks').glob('REPRO-*.yaml'))
    for lane in lanes:
        grouped, runs, events, audit = collect(batch, lane)
        score = score_lane(grouped, lane)
        # 零有效题必须显式列出null；宏平均仍以实际可估计题为条件，不填0或1。
        score['missing_valid_tasks'] = [t for t in task_ids if not grouped.get(t)]
        for task in task_ids:
            score['per_task'].setdefault(task,score_task([],lane))
        if lane != 'R0':
            declared_groups = {task: [{k: v for k, v in r.items() if k != 'reviewed_card'} for r in rs] for task, rs in grouped.items()}
            declared_score = score_lane(declared_groups, lane)
            declared_score['missing_valid_tasks'] = score['missing_valid_tasks']
            for task in task_ids:
                declared_score['per_task'].setdefault(task,score_task([],lane))
            write(out/f'{lane}-declared-card-consistency.json', declared_score)
        write(out / f"{lane}-consistency.json", score)
        write(out / f"{lane}-audit.json", audit)
        metrics = None
        u = None
        if lane != "R0":
            identity = manifest["best_data"]["fingerprint_before"]
            # 两路模型输入相同；快照身份另记溯源，不假装模型主动看到快照id。
            attempt_paths = sorted((batch/'lanes'/lane).glob('*/repeat-*/attempt-*-result.json'))
            all_attempt_runs = [read(p) for p in attempt_paths]
            all_attempt_events = [[json.loads(s) for s in (p.parent/r['trace']).read_text().splitlines()] for p,r in zip(attempt_paths,all_attempt_runs)]
            for run, ev in zip(all_attempt_runs,all_attempt_events):
                run['native_tool_call_count'] = sum(e['type']=='tool_call' for e in ev)
                run['wire_semantic_failures'] = wire_failures(ev)
            metrics = efficiency(all_attempt_runs,all_attempt_events)
            metrics['valid_records_only'] = efficiency(runs,events)
            metrics['denominator_policy'] = 'all_actual_attempts_including_protocol_failures; valid_only_as_supplement'
            u = usability(all_attempt_runs, identity)
            u['valid_records_only'] = usability(runs, identity)
            u['denominator_policy'] = 'all_actual_attempts_including_model_protocol_failures; valid_only_retained_as_supplement'
            write(out / f"{lane}-efficiency.json", metrics)
            write(out / f"{lane}-usability.json", u)
            write(out / f"{lane}-semantic-cards.json", [{"task_id": r["task_id"], "repeat": r["repeat"], "answer": r["answer_text"],
                  "declared_card": r["card"], "semantic_card": r["reviewed_card"], "diagnostics": r["review_diagnostics"]} for r in runs])
        results[lane] = {"score": score, "audit": audit, "efficiency": metrics, "usability": u,
                         "returned_models": dict(Counter(e['payload'].get('returned_model') for ev in all_attempt_events for e in ev if e['type']=='model_response')) if lane!='R0' else {},
                         "returned_models_valid_records_only": dict(Counter(m for r in runs for m in r.get("returned_models", []))),
                         "outcomes": dict(Counter(r["outcome"] for r in runs))}
        with (out / f"{lane}-per-task.csv").open("w") as handle:
            writer = csv.writer(handle)
            writer.writerow(["task_id", "valid_repeats", "TSC", "PAC_call", "RDC", "FCC", "TSC_mode_count", "TSC_n", "TSC_wilson95", "FCC_mode_count", "FCC_n", "FCC_wilson95"])
            for task, row in sorted(score["per_task"].items()):
                writer.writerow([task, row["runs"], row["TSC"]["point"], row["PAC_call"]["point"], row["RDC"]["point"], row["FCC"]["point"],
                                 row["TSC"]["mode_count"], row["TSC"]["n"], row["TSC"]["wilson_95"], row["FCC"]["mode_count"], row["FCC"]["n"], row["FCC"]["wilson_95"]])
    pilot = pilot_calibration(batch, out)
    gates = [read(p) for p in sorted((batch / "canary").glob("*/*-gate.json"))]
    for gate in gates:
        gate['before']['exact_raw_rows_fingerprint'] = exact_canary(gate['before']['path'])
        gate['after']['exact_raw_rows_fingerprint'] = exact_canary(gate['after']['path'])
        gate['normalized_drift_state'] = gate['drift_state']
        if gate['before']['exact_raw_rows_fingerprint'] != gate['after']['exact_raw_rows_fingerprint']:
            gate['drift_state'] = 'DRIFTED'
        if gate.get('resumed_before'):
            gate['resumed_before']['exact_raw_rows_fingerprint'] = exact_canary(gate['resumed_before']['path'])
            gate['resume_exact_stable'] = gate['before']['exact_raw_rows_fingerprint']==gate['resumed_before']['exact_raw_rows_fingerprint']
            if not gate['resume_exact_stable']:
                gate['drift_state'] = 'DRIFTED'
        if not gate['all_probes_valid']:
            gate['drift_state'] = 'UNVERIFIABLE'
    write(out/'canary-exact-rows-audit.json', gates)
    deltas = {}
    paired_deltas = {}
    for metric in ("TSC", "PAC_call", "RDC", "FCC"):
        left = results["R1"]["score"]["aggregate"][metric]["point"]
        right = results["R3"]["score"]["aggregate"][metric]["point"]
        deltas[metric] = left - right if left is not None and right is not None else None
        paired = []
        for task in sorted(set(results['R1']['score']['per_task']) & set(results['R3']['score']['per_task'])):
            a = results['R1']['score']['per_task'][task][metric]['point']
            b = results['R3']['score']['per_task'][task][metric]['point']
            if a is not None and b is not None:
                paired.append(a-b)
        paired_deltas[metric] = cluster_ci(paired)
    scripts = {p.name: fp(p.read_text()) for p in HERE.glob("*.py")}
    write(out / "scoring-manifest.json", {"code": scripts, "fp": fp(scripts), "judgement": "current_assistant_no_judge_api",
          "semantic_scope": "task_core_facts_from_actual_answer; candidate_model_card_retained_and_number_checked",
          "U7": "missing_no_independent_raters", "notes": "规则抽取与当前助手复核，不能代替独立盲评"})
    payload = {"generated_at": now(), "batch": batch.name, "manifest_fp": fp(manifest), "lanes": results,
               "collection_complete_required_lanes": all(results[l]['audit']['terminated_slots']==160 for l in ('R1','R3')) and results['R0']['score']['records']==90,
               "resumption_audits": [str(p) for p in sorted((batch/'resumption-audits').glob('*.json'))],
               "original_counterexample_selftest": read(batch/'R0-original-selftest.json') if (batch/'R0-original-selftest.json').exists() else None,
               "R2": read(batch / "R2-CONDITIONS.json") if (batch / "R2-CONDITIONS.json").exists() else {"status": "pending_R1_completion"},
               "pilot": {k: v for k, v in pilot.items() if not k.startswith("metrics")}, "canary_gates": gates, "R1_minus_R3": deltas,
               "R1_minus_R3_paired_task_bootstrap": paired_deltas,
               "formal_protocol_gate": "FAIL", "composite_score": None,
               "composite_missing_reason": "EF5/U5部分任务预算与完整场景缺失；不以默认满分填补综合分。原阻断不被加权覆盖",
               "blockers": manifest["protocol_deviations"],
               "statistics_limit": "5重复与32独立题分开；题号成组重抽；5/5的描述Wilson=[0.5655,1]；不得推广为必然稳定。McNemar未比较两系统不适用，效力0.6–0.7依赖效应量不能无依据套用。"}
    write(out / "summary.json", payload)
    lines = ["# E6 可复现性、效率与可用性实测报告", "", f"生成：{payload['generated_at']}；批次：`{batch.name}`。", "",
             f"R0/R1/R3计划采集完整：**{payload['collection_complete_required_lanes']}**。False为采集中评分快照，不是最终交付；完整也不代表160条全部有效或协议通过。", "",
             "本报告区分采集完整、轨迹有效和指标表现。原协议整体门禁为 **FAIL**，不能因某个一致率高而宣布E6通过。R2另在D+7人工复跑，本轮不等待、不创建定时任务。", "",
             "采用一套系统：冻结项目skill材料、原始32题、7个真实工具，模型自主选择工具，项目生产实现负责执行。第三方生成API已验证工具调用与续接；判断由当前助手和本地规则进行，没有评分API。", "",
             f"请求模型 `{manifest['model']['requested']}`；实际回包见每路模型分布。权重快照 opaque。请求参数 `{json.dumps(manifest['sampling']['actual_request_parameters'],ensure_ascii=False)}`；temperature 未发送，seed未请求且honored=false。", "",
             "| 路 | 有效题号（满5次） | 有效记录 | TSC | PAC_call | RDC | FCC语义卡 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for lane, result in results.items():
        score = result["score"]
        points = [score["aggregate"][key]["point"] for key in ("TSC", "PAC_call", "RDC", "FCC")]
        rendered = ["缺失" if p is None else f"{p:.4f}" for p in points]
        lines.append(f"| {lane} | {score['coverage']['tasks_with_5_valid']}/32 | {score['records']}/{160 if lane!='R0' else 90} | " + " | ".join(rendered) + " |")
    if 'R2' not in results:
        lines.append("| R2 | 待D+7 | 0/160 | 缺失 | 缺失 | 缺失 | 缺失 |")
    lines += ["", "一致性指标以有效记录为条件，采集与失败分母另列：", "",
              "| 路 | 已结束槽位 | 已结束尝试 | 有效记录 | 失败尝试 |", "|---|---:|---:|---:|---:|"]
    for lane, result in results.items():
        a = result['audit']
        lines.append(f"| {lane} | {a['terminated_slots']} | {a['terminated_attempts']} | {result['score']['records']} | {a['failure_attempts']} |")
    if payload['resumption_audits']:
        lines += ["", "R1原进程外部中断后恢复：原未闭合trace不改，侧记interrupted_execution；只该中断槽位另起一次上下文。普通已结束失败不重采。确切退出时刻及原中断尝试全墙钟未知null，已观察墙钟下界和已知usage保留，不填0或估算token；因此R1包含间隔，非连续不间断运行。前后及恢复段canary、全部尝试成本和恢复审计均保留。"]
    for lane, result in results.items():
        api_failures=result['audit']['model_api_failures']
        if api_failures['affected_attempts']:
            lines += ['', f"**{lane}生成接口故障：{api_failures['affected_attempts']}次尝试受影响，HTTP状态计数{api_failures['http_status_counts']}；其中{api_failures['insufficient_balance_attempts']}次供应商明确返回Insufficient Balance。** 属于运营故障，不是BEST后端或模型科学能力判定。失败原件和已知usage保留，未知usage不估算；不换模型或补跑。R3余额拒绝使后段未答题，并拉低全部尝试的请求/耗时中位数，不能解释为策略提效；有效记录一致率仅以实际成功子样本为条件。"]
    lines += ['', '各路实际agent轨迹时间（不以初始manifest日期代替实际日期）：', '']
    for lane,result in results.items():
        lines.append('- '+lane+'：`'+json.dumps(result['audit']['actual_execution_dates'],ensure_ascii=False)+'`。')
    selftest = payload['original_counterexample_selftest']
    if selftest:
        detected = sum(bool(r['detected']) for r in selftest['results'].values())
        lines += ["", f"原反证夹具：{detected}/{len(selftest['results'])}检出，metascore={selftest['metascore']}，pass={selftest['pass']}；原件R0-original-selftest.json。"]
    codes = ['ERR_ROUTE','ERR_PARAM_SCHEMA','ERR_PARAM_UNSTABLE','ERR_BACKEND','ERR_BACKEND_DRIFT','ERR_RETRY_INEFFECTIVE','ERR_CONCLUSION_UNSTABLE','OK']
    lines += ["", "有效记录内归因分布（无效格式/快照分支等原因另见每路audit失败清单）：", "", '| 路 | '+' | '.join(codes)+' |', '|---|'+'---:|'*len(codes)]
    for lane,result in results.items():
        counts = result['score']['attribution']
        lines.append('| '+lane+' | '+' | '.join(str(counts.get(c,0)) for c in codes)+' |')
    lines += ["",
              "归因中的硬参数错误独立检查实际sqlid合法性；生产成功包装的无效会话空表仍归ERR_PARAM_SCHEMA，不能因ok=true跳过第二条优先级。结构有效记录不代表参数正确或查询成功。", "",
              "R0仅18/32（56.25%）固化工具层任务；90次不是90个独立任务。R1/R3题号采集并不等于分页、1000坐标批量匹配、哨兵失败等意图场景均真实触发。缺上下文原题按澄清保留；没有人为补坐标或预写调用替代模型决策。", "",
              "FCC比较结论卡的类别、核心数值、实体、关键科学限定语；中英文标签、数值格式、句式差异按当前助手的规则归一。模型声明卡和答案原文同时保存，语义卡并非外部评分模型生成。非核心附加解释不进入主FCC；其差异是E3复核素材。", "",
              "冻结tools.schema.json及llms.txt已含错误的‘360倍’角度单位提示（1°=3600″），多份答复复述。上游材料缺陷与模型独有错误须分开，不能因重复答案一致就当科学正确；本轮未改提示材料/生产schema或重采。来源及其它附加缺陷见ASSISTANT-REVIEW.md。", "",
              "冻结photometric-systems.md还把官网Download栏的25G/1.4T等解读成星数/规模，多份回答据此声称数百亿/万亿行。事后[官网目录](https://nadc.china-vo.org/data/best/doc/system-en/catalog)核验仅支持下载栏标签，不支持这些星数；由该标签推断下载体量，未读取大文件或实核字节。该核验只供当前助手审阅，未改SUT输入或加入快照bank。", "",
              "每题各次、调用槽位和Wilson分母见JSON及CSV。聚合区间按题号成组重抽，不用虚构n=100或把160次视为160独立题。全一致的bootstrap区间退化不能解释为未来必然稳定；少于两次不估计稳定率。α按任务的重复构造；无类别方差记缺失。", "",
              "RDC在线主口径为规范行集加非行状态的Jaccard；回放主口径L1内容指纹。没有工具结果的澄清/拒绝题另标记为无数据，并提供data-conditioned汇总。L1/L2全等/L3及pairwise均落盘。R1−R3是描述性差值：不同RDC口径、样本误差和快照分支覆盖使其不能直接认作因果噪声量。", "",
              "R3快照按冻结request_key归一规则覆盖已观测请求；绑定SQLID的s前缀被该规则丢弃，结构上未保留该路径区别，不能无条件称为完整wire语义保真。不同页大小等同时变化时响应差异不能单因归给前缀；wire-semantics审计另列同键前缀观测范围。模型选到新分支即E_SNAPSHOT_MISS、该尝试无效。有效记录一致率因此以被快照覆盖的决策为条件，存在选择偏差，不能解释为全部模型路径的稳定率。全槽位失败和实际请求/usage仍进入主可用性、成本与审计。", "",
              "| 路 | η（请求协议下界/实测请求） | 请求P50/P90 | agent单调时钟P50/P90秒 | 冗余率 | 无效重试率 | 元数据零请求率 |", "|---|---:|---|---|---:|---:|---:|"]
    for lane in [l for l in lanes if l != 'R0']:
        e = results[lane]["efficiency"]
        lines.append(f"| {lane} | {e['EF1']['eta_ratio_of_sums']} | {e['http_requests']['p50']}/{e['http_requests']['p90']} | {e['EF2']['agent_wall_with_wait']['p50']}/{e['EF2']['agent_wall_with_wait']['p90']} | {e['EF3']['point']} | {e['EF4']['point']} | {e['EF6']['point']} |")
    lines += ["", "效率主表纳入所有实际尝试，包括协议格式失败；有效记录条件分另存。表中agent用时由time.monotonic测量且含等待，JSON同时保存扣除实测限速等待的用时、实际UTC起止跨度和跨时钟差异；不推断差额是推理耗时或确切原因；HTTP计数是Session.request层，内部重试/重定向另列真实历史。R3的HTTP次数指回放协议请求，真实站点wire请求为0。零请求η的0/0记null；EF6要求实际元数据工具和完整有效答案，失败不能算零请求完成。缺usage完整总量=null，回包已知部分仍计入observed_sum；价格和货币成本均null。", "",
              "工具步数按trace中实际派发的native tool_call计算；已派发但结果序列化失败仍计一步。模型提出function_call但参数不能解码，或同批前序调用失败使后续未执行，均属于未派发请求，原因看原trace。network_cost_audit分别列出，不把普通消息的XML/工具列表执行或计作实际工具步骤。EF5不忽略无session失败/fallback或已派发缺结果的查询，其行覆盖保留false/unknown。", "",
              "EF3沿原协议仅以重复cone_search/crossmatch_batch作分子，分母为全部工具步数；重复list/describe不进入该分子，低EF3不能证明没有元数据调用循环。所有工具同参重复另作诊断，具体原因仍以轨迹为准。", "",
              f"Pilot：{pilot['tasks']}题、{pilot['records']}记录，10×5完整={pilot['complete_10x5']}。已保存P50/P90与P90、1.2×P90观测线；原η、冗余/重试阈值仍是建议，异质任务的观测线不是经过独立验证的门禁。", "",
              "| 路 | U1 | U2 | U3 | U4 | U5 | U6 | U7 |", "|---|---:|---:|---:|---:|---:|---:|---|"]
    for lane in [l for l in lanes if l != 'R0']:
        u = results[lane]["usability"]
        lines.append("| " + lane + " | " + " | ".join(str(u["summary"][key]["point"]) for key in ("U1", "U2", "U3", "U4", "U5", "U6")) + " | 缺失；0评阅人 |")
    lines += ["", "U1含设计为澄清/拒绝的原题；U2检查实际失败答案、登记错误码、人话原因、下一步；生产E_BACKEND未在契约登记，单独列出。U4不能用任意data_hash冒充站点版本；每条答案检查实际canary标识，其单位项只检查标注存在性。U1流程/证据条件、U4标注存在以及FCC主结论一致均不保证全文科学正确；换算和附加说明错误另见ASSISTANT-REVIEW.md。U5按独立任务步骤预算，0/未知预算记null，未把元数据工具步数和网络请求混为一谈。U6将拒答、澄清与实际失败均纳入适用分母，检验肯定的not_computable/not_configured显式标签；这是降级声明的证据代理，不是全文无编造的独立判定。U7没有独立评阅人，未编造主观评分。R0不报告用户可用性分。", "",
              "明确的协议及覆盖限制：", ""]
    lines.extend("- " + item for item in manifest["protocol_deviations"])
    lines += ["", "Canary门禁及漂移证据：", ""]
    for gate in gates:
        lines.append(f"- {gate['before']['path']} → {gate['after']['path']}：{gate['drift_state']}；before={gate['before']['fingerprint']}；after={gate['after']['fingerprint']}；完整有效={gate['all_probes_valid']}。")
    lines += ["", f"R1−R3描述差值：`{json.dumps(deltas)}`。R2−R1尚无数据，不计算。跨日漂移留给E7，不隐去。", "",
              f"Skill指纹：`{manifest['skill']['fingerprint']}`；prompt：`{manifest['system_prompt']['fingerprint']}`；schema：`{manifest['tool_schema']['code_side']}`；暴露schema：`{manifest['tool_schema']['mcp_tools_list']}`。完整冻结项见run_manifest.json。", "",
              "重新生成评分快照入口（项目根目录；不调用生成API）：", "", "```bash", f"temp/e3-e6/venv/bin/python temp/e6-formal/report_e6.py --batch {batch.name}", "```", "",
              "成功记录不可覆盖，所有失败attempt保留。本轮已结束的失败槽位不重采；run_e6_formal.py普通入口会为失败另起attempt，因此不应对已结束R1/R3整路重复调用。外部中断的唯一恢复记录另见resumption-audits。未知快照请求产生E_SNAPSHOT_MISS并使该次无效，不回伪造空表。采集代码/参数/任务/材料变更必须新批次。", ""]
    conditions = payload["R2"]
    if "due_date_Asia_Shanghai" in conditions:
        lines += [f"R1完成：{conditions['r1_completed_at']}；R2准确日期：**{conditions['due_date_Asia_Shanghai']}（Asia/Shanghai）**。复查模型权限、实际回包模型、冻结参数、全部指纹及站点前后canary。", "", "```bash", conditions["command"], "```", ""]
    (out / "REPORT.md").write_text("\n".join(lines))
    write(batch / "latest-report.json", {"directory": str(out)}, exclusive=False)
    print(json.dumps({"report": str(out / 'REPORT.md'), "lanes": {l: {'valid': r['score']['records'], 'tasks': r['score']['coverage']['tasks_with_5_valid']} for l,r in results.items()}}))
    return out

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", required=True)
    args = parser.parse_args()
    generate(HERE / "batches" / args.batch)
