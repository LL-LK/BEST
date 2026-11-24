"""效率与客观可用性：实测成本、明确分母、缺失不填满分。"""
# 标准库和第三方：语义模式与分位数。
import math
import re
from collections import Counter
from datetime import datetime
from urllib.parse import urlsplit, parse_qsl
import numpy as np
# 既有指标保留为审计对照，本轮纠正其分母和计时。
from evals.repro.efficiency import summarize_efficiency
from evals.repro.usability import summarize_usability
from common_e6 import fp
from semantic_cards_e6 import capability_labels
from src.protocol import parse_csv_rows
from metrics_e6 import invalid_session_call

MIN_STEPS = {1: 1, 2: 1, 3: 1, 4: 1, 7: 0, 13: 0, 15: 2, 16: 2, 17: 0, 18: 0, 19: 0,
             22: 0, 23: 0, 24: 0, 25: 1, 26: 0, 27: 1, 28: 1, 29: 1, 31: 0, 32: 2}
STABLE_CODES = {"E_INVALID_INPUT", "E_SOFT_404", "E_NAME_UNRESOLVED", "E_NO_SQLID"}

def semantic_failures(run):
    """保留生产原信封，同时披露其与实际输入校验的矛盾。"""
    return [{'call_index':i,'tool':c['tool'],'expected_code':'E_INVALID_INPUT',
             'observed_ok':e['status']['ok'],'observed_code':e['status'].get('error_code')}
            for i,(c,e) in enumerate(zip(run['tool_calls'],run['envelopes']))
            if invalid_session_call(c) and e['status']['ok']]

def percentile(values):
    """空样本返回 null，分位数使用实测数据。"""
    values = [v for v in values if isinstance(v,(int,float)) and math.isfinite(v)]
    return {"n": len(values), "p50": float(np.percentile(values, 50)) if values else None,
            "p90": float(np.percentile(values, 90)) if values else None}

def page_coverage(events):
    """按真实查询和页偏移核验实取覆盖，投影变化和重取不能累加冒充全集。"""
    queries, covered, without_session = {}, {}, []
    for event in events:
        if event['type'] != 'tool_result':
            continue
        call_event = events[event['parent_seq']]
        call, env = call_event['payload'], event['payload']['envelope']
        if call['tool'] not in ('cone_search','crossmatch_batch','fetch_page'):
            continue
        sid = str(env['provenance'].get('session_id') or call['args'].get('sqlid','')).lstrip('s')
        if not sid:
            if call['tool'] in ('cone_search','crossmatch_batch'):
                without_session.append({'call_seq':call_event['seq'],'sqlid':None,'total':None,
                    'ok':env['status']['ok'],'materialized_server_row_positions':None,
                    'complete':False if not env['status']['ok'] else None,
                    'note':'无可验证查询会话；fallback total_count可能为输入数，不能当服务端行总数或忽略该请求。'})
            continue
        if call['tool'] in ('cone_search','crossmatch_batch'):
            queries[sid] = {'sqlid':sid,'total':env['data'].get('total_count'),'ok':env['status']['ok']}
        remaining = len(env['data'].get('rows',[]))
        covered.setdefault(sid,set())
        for net_event in events[call_event['seq']+1:event['seq']]:
            if net_event['type'] != 'network_exchange':
                continue
            net = net_event['payload']
            params = dict(parse_qsl(urlsplit(net.get('original_url',net.get('url',''))).query))
            if 'page' not in params or not net.get('response') or not env['status']['ok']:
                continue
            try:
                wire_rows = len(parse_csv_rows(net['response']['text'], call['args'].get('catalog','ps1')))
            except Exception:
                continue
            size, page = int(params.get('rows',1000)), int(params['page'])
            used = min(remaining,wire_rows,size)
            start = (page-1)*size
            covered[sid].update(range(start,start+used))
            remaining -= used
    paired = {e['parent_seq'] for e in events if e['type']=='tool_result'}
    for index,event in enumerate(events):
        if event['type']=='tool_call' and event.get('seq',index) not in paired and event['payload']['tool'] in ('cone_search','crossmatch_batch'):
            without_session.append({'call_seq':event.get('seq',index),'sqlid':None,'total':None,'ok':None,
                'materialized_server_row_positions':None,'complete':None,
                'note':'已派发但工具结果未完成；网络原件保留，typed行覆盖未知，不能忽略该请求。'})
    return without_session+[{**q,'materialized_server_row_positions':len(covered.get(sid,set())),
             'complete':(q['ok'] and len(covered.get(sid,set())) >= q['total']) if isinstance(q['total'],int) else None}
            for sid,q in queries.items()]

def efficiency(runs, events_by_run):
    """修正生产query含getcount、分页含count、限速按实际等待扣除。"""
    redundancy = total_calls = retry_total = ineffective = 0
    actual, lower, token_in, token_out, observations, rows = [], [], [], [], [], []
    paging, utc_spans, clock_gaps = [], [], []
    observed_token_in = observed_token_out = model_requests_total = missing_usage_calls = 0
    exact_repeats = Counter()
    for run, events in zip(runs, events_by_run):
        span = (datetime.fromisoformat(run['ended_at'])-datetime.fromisoformat(run['started_at'])).total_seconds() if run.get('started_at') and run.get('ended_at') else None
        utc_spans.append(span)
        if span is not None and run.get('wall_s') is not None and abs(span-run['wall_s'])>1:
            clock_gaps.append({'task_id':run['task_id'],'repeat':run['repeat'],'trace':run.get('trace'),
                              'UTC_timestamp_span_s':span,'monotonic_duration_s':run['wall_s'],
                              'UTC_minus_monotonic_s':span-run['wall_s']})
        calls, envs = run["tool_calls"], run["envelopes"]
        native_calls = [e['payload'] for e in events if e['type']=='tool_call'] if events else calls
        total_calls += len(native_calls)
        run_repeats = Counter()
        seen, needed = set(), 0
        for call in native_calls:
            key = fp({'tool':call['tool'],'args':call['args']})
            if key in seen:
                run_repeats[call['tool']] += 1
                if call['tool'] in ('cone_search','crossmatch_batch'):
                    redundancy += 1
            seen.add(key)
        exact_repeats.update(run_repeats)
        seen = set()
        for call, env in zip(calls, envs):
            key = fp(call)
            if call["tool"] in ("cone_search", "crossmatch_batch") and key in seen:
                continue
            seen.add(key)
            name, count = call["tool"], env["cost"]["http_requests"]
            if name in ("list_catalogs", "describe_catalog") or env["status"].get("error_code") == "E_INVALID_INPUT" or invalid_session_call(call):
                required = 0
            elif name in ("cone_search", "crossmatch_batch"):
                required = 3 if env["status"]["ok"] else min(1, count)
            elif name == "fetch_page":
                required = 2
            else:
                required = 1
            needed += required
        enveloped_count = sum(e["cost"]["http_requests"] for e in envs)
        # 实际run结束计数还包含已取到网络回包、却因NaN等没能写tool_result的请求。
        count = run.get('cost',{}).get('http_requests',enveloped_count)
        actual.append(count)
        lower.append(needed)
        responses = [e["payload"] for e in events if e["type"] == "model_response"]
        requested_functions = sum(o.get('type')=='function_call' for r in responses for o in r.get('raw',{}).get('output',[]))
        inputs = [(r.get("usage") or {}).get("input_tokens") for r in responses]
        outputs = [(r.get("usage") or {}).get("output_tokens") for r in responses]
        requested = sum(e['type']=='model_request' for e in events)
        known_in, known_out = [v for v in inputs if isinstance(v,int)], [v for v in outputs if isinstance(v,int)]
        observed_token_in += sum(known_in)
        observed_token_out += sum(known_out)
        model_requests_total += requested
        complete_usage_calls = sum(isinstance(a,int) and isinstance(b,int) for a,b in zip(inputs,outputs))
        missing_usage_calls += max(0,requested-complete_usage_calls)
        token_in.append(sum(known_in) if requested and len(known_in)==requested else None)
        token_out.append(sum(known_out) if requested and len(known_out)==requested else None)
        retries = [e["payload"] for e in events if e["type"] == "retry"]
        retry_total += len(retries)
        ineffective += sum(r.get("strategy_changed") is False for r in retries)
        queries = [env for c, env in zip(calls, envs) if c["tool"] in ("cone_search", "crossmatch_batch")]
        pages = [c for c in native_calls if c["tool"] == "fetch_page"]
        complete_rows = len({fp(r) for e in envs for r in e["data"].get("rows", [])})
        true_totals = [e["data"].get("total_count") for e in queries if isinstance(e["data"].get("total_count"), int)]
        rows.append(complete_rows)
        network = [e["payload"] for e in events if e["type"] == "network_exchange"]
        totals_by_sid = {str(e['provenance'].get('session_id')).lstrip('s'): e['data'].get('total_count',e['data'].get('total')) for e in envs
                         if e['provenance'].get('session_id') and isinstance(e['data'].get('total_count',e['data'].get('total')),int)}
        page_records = []
        for net in network:
            url = net.get('original_url',net.get('url',''))
            match = re.search(r'/sqlid/(s?\d+)', url)
            params = dict(parse_qsl(urlsplit(url).query))
            if not match or 'page' not in params:
                continue
            total = totals_by_sid.get(match[1].lstrip('s'))
            page, size = int(params['page']), int(params.get('rows',1000))
            page_records.append({'page':page,'page_size':size,'total_count':total,
                                 'over': (page-1)*size >= total if total is not None and total > 0 else (page > 1 if total == 0 else None)})
        measured_over = sum(p['over'] for p in page_records if p['over'] is not None) if page_records else None
        query_coverage = page_coverage(events)
        completeness = all(q['complete'] for q in query_coverage) if query_coverage and all(q['complete'] is not None for q in query_coverage) else None
        paging.append({"task_id": run["task_id"], "repeat": run["repeat"], "fetch_page_calls": len(pages),
                       "true_totals": true_totals, "rows_materialized_distinct": complete_rows,
                       "truncated_observed": any(e["status"].get("truncated") for e in queries),
                       "all_requested_data_materialized": completeness, 'all_query_rows_materialized':completeness,
                       'per_query_materialization':query_coverage,
                       "pagination_exercised": bool(pages), "over_paging": measured_over,
                       "actual_page_requests": page_records,
                       "note": "依据真实session总数/page_size检查越界；逐查询实取覆盖指全集，REPRO-28只要求首页，全集未取不等于用户任务未完成。未知总数null。"})
        wire = 0
        for net in network:
            if net.get("mode") == "live":
                response = net.get("response", {})
                wire += 1 + len(response.get("retries", [])) + len(response.get("redirects", []))
        observations.append({"task_id": run["task_id"], "repeat": run["repeat"], "session_requests": count,
                             'native_tool_calls':len(native_calls),'completed_tool_results':len(envs),
                             'all_tools_exact_repeats':dict(run_repeats),
                             'native_calls_without_recorded_tool_result':max(0,len(native_calls)-len(envs)),
                             'model_requested_function_call_items':requested_functions,
                             'model_function_call_items_without_dispatch':max(0,requested_functions-len(native_calls)),
                             "requests_without_recorded_tool_result": max(0,count-enveloped_count),
                             "observed_wire_attempts_or_lower_bound": wire, "has_network_error": any("error" in n for n in network)})
    metadata = [r for r in runs if r["task_id"] in ("REPRO-01", "REPRO-02", "REPRO-32")]
    required_metadata = {'REPRO-01':{'list_catalogs'},'REPRO-02':{'describe_catalog'},'REPRO-32':{'list_catalogs','describe_catalog'}}
    zeros = sum(bool(r.get('completed') and not r.get('validation_errors')) and
                required_metadata[r['task_id']] <= {c['tool'] for c,e in zip(r['tool_calls'],r['envelopes']) if e['status']['ok']} and
                sum(e['cost']['http_requests'] for e in r['envelopes'])==0 for r in metadata)
    denominator = sum(actual)
    per_eta = [min(1,n/a) if a else None for n,a in zip(lower,actual)]
    legacy_runs = [{**r, "usage": {"tokens_in": ti, "tokens_out": to}} for r, ti, to in zip(runs, token_in, token_out)]
    return {"EF1": {"eta_ratio_of_sums": min(1, sum(lower) / denominator) if denominator else None,
                     "actual_session_requests": denominator, "protocol_lower_bound_requests": sum(lower), "per_run": per_eta,
                     "limitation": "按观测成功工具协议下界；非独立任务最优策略oracle，不能把错误零请求当高效率"},
            "EF2": {"agent_wall_with_wait": percentile([r["wall_s"] for r in runs]),
                     'agent_monotonic_with_wait':percentile([r['wall_s'] for r in runs]),
                     'agent_utc_timestamp_span':percentile(utc_spans),'cross_clock_discrepancies':clock_gaps,
                     'timing_scope':'run.wall_s is measured time.monotonic duration; UTC span separately reported, gap cause unverified; mismatch threshold 1s diagnostic only',
                     "agent_wall_without_measured_wait": percentile([max(0, r["wall_s"] - r["rate_limit_wait_s"]) if r.get('wall_s') is not None else None for r in runs]),
                     "agent_wall_missing_runs": sum(r.get('wall_s') is None for r in runs),
                     "interrupted_wall_observed_lower_bounds": [r['wall_s_observed_lower_bound'] for r in runs if 'wall_s_observed_lower_bound' in r],
                     "tool_elapsed_with_wait": percentile([sum(e["cost"]["elapsed_s"] for e in r["envelopes"]) for r in runs]),
                     "measured_wait_s": sum(r["rate_limit_wait_s"] for r in runs)},
            "http_requests": percentile(actual), "EF3": {"point": redundancy / total_calls if total_calls else None, "redundant": redundancy, "tool_calls": total_calls,
                'scope':'原协议分子仅重复cone_search/crossmatch_batch，分母所有派发工具。所有工具同参重复另列诊断，不自动断言重复无用。',
                'all_tools_exact_repeat_count':sum(exact_repeats.values()),'exact_repeats_by_tool':dict(exact_repeats)},
            "EF4": {"point": ineffective / retry_total if retry_total else None, "ineffective": ineffective, "retries": retry_total,
                    "scope": "显式trace retry（模型HTTP瞬时重试）；原样不变策略是协议代理指标，不证明瞬时重试无益。BEST内部历史另计，agent重复调用未自动标记retry。"},
            "EF5": {"per_run": paging, "over_paging": sum(p['over_paging'] for p in paging if p['over_paging'] is not None) if any(p['over_paging'] is not None for p in paging) else None,
                    "runs_with_measured_page_budget": sum(p['over_paging'] is not None for p in paging),
                    "scope_exercised_runs": sum(p["pagination_exercised"] for p in paging)},
            "EF6": {"point": zeros / len(metadata) if metadata else None, "zero_request_runs": zeros, "metadata_runs": len(metadata)},
            "EF7": {"tokens_in_per_run": token_in, "tokens_out_per_run": token_out,
                    "tokens_in_observed_sum": observed_token_in, "tokens_out_observed_sum": observed_token_out,
                    "missing_usage_runs": sum(v is None for v in token_in), 'model_requests':model_requests_total,
                    'model_requests_without_complete_usage':missing_usage_calls,
                    'usage_policy':'回包已知usage全部相加；超时/缺usage使该次完整总量null，已知部分仍进入observed_sum。',
                    "price": None, "currency_cost": None},
            "network_cost_audit": observations, "legacy_efficiency_unfit_for_primary": summarize_efficiency(legacy_runs, rate_limit_seconds=0.0)}

def usability_run(run, data_identity):
    """直接检查答案，不把生成端自评或错误信封当评分。"""
    answer = run.get("answer_text", "")
    kind = run.get("reviewed_card", run.get("card", {'kind':'none'}))["kind"]
    semantic_errors = semantic_failures(run)+[f for f in run.get('wire_semantic_failures',[]) if f['wrapped_as_success']]
    failure = any(not e["status"]["ok"] or e["data"].get("total", 1) is None for e in run["envelopes"]) or run["outcome"] == "fail" or bool(semantic_errors)
    invalid_refusal = run["task_id"] in ("REPRO-13", "REPRO-31")
    applicable_u2 = failure or invalid_refusal
    codes = re.findall(r"\bE_[A-Z_]+\b", answer)
    reason = bool(re.search(r"原因|因为|失败|无法|超过|超出|不支持|越界|无效|未(?:解析|配置)|缺少|不(?:在|是).{0,12}(?:范围|星表)|拒绝|(?:HTTP|Error|error)", answer))
    next_action = bool(re.search(r"建议|下一步|请|可以|改为|改用|重新|尝试|缩小|提供|确认", answer))
    u2 = bool(set(codes) & STABLE_CODES) and reason and next_action if applicable_u2 else None
    clarification = run.get("clarification") or {}
    dims = clarification.get("missing_dims", [])
    options = clarification.get("options", [])
    u3 = bool(dims) and len(options) >= 2 if kind == "clarification" else None
    has_units = bool(re.search(r"角秒|角分|度|°|mag|星等|单位|deg|arcsec", answer, re.I))
    has_identity = data_identity in answer
    has_uri = "best://" in answer
    has_trust = "untrusted" in answer
    u4 = {"units": has_units, "actual_data_identity": has_identity, "stable_uri": has_uri, "content_trust": has_trust}
    degraded = kind in ('refusal','clarification') or failure
    # 输入不足的澄清同样尚不能完成原请求，不能用kind切换规避降级分母。
    positive_labels = capability_labels(answer)
    u6 = bool(positive_labels) if degraded else None
    task_no = int(run["task_id"][-2:])
    requires_data_tool = task_no in (3,4,11,14,15,16,21,25,27,28,29)
    evidence_present = any(e['status']['ok'] and c['tool'] not in ('list_catalogs','describe_catalog') for c,e in zip(run['tool_calls'],run['envelopes']))
    if task_no in (1,2,32):
        requires_data_tool = True
        needed = {1:{'list_catalogs'},2:{'describe_catalog'},32:{'list_catalogs','describe_catalog'}}[task_no]
        evidence_present = needed <= {c['tool'] for c,e in zip(run['tool_calls'],run['envelopes']) if e['status']['ok']}
    actual_steps = run.get('native_tool_call_count',len(run['tool_calls']))
    minimum = MIN_STEPS.get(task_no)
    if minimum and task_no in (27, 28):
        # 实际总数低于首页上限不需要续页；跨页预算未知时U5记缺失。
        if any(c['tool'] in ('cone_search','crossmatch_batch') and e['status'].get('truncated')
               for c,e in zip(run['tool_calls'],run['envelopes'])):
            minimum = None
    return {"task_id": run["task_id"], "repeat": run["repeat"], "U1": kind in ("value", "rowset") and not failure and (not requires_data_tool or evidence_present),
            "U2": u2, "U2_applicable": applicable_u2, "U2_elements": {"registered_code": bool(set(codes) & STABLE_CODES), "reason": reason, "action": next_action},
            "unregistered_codes": sorted(set(codes) - STABLE_CODES), "U3": u3, "clarification_dims": dims,
            "U4": sum(u4.values()) / 4, "U4_elements": u4,
            "U5": actual_steps / minimum if minimum and run.get('completed') else None,
            "U5_actual_steps": actual_steps, "U5_task_min_steps": minimum,
            "tool_result_semantic_errors": semantic_errors,
            "zero_step_task_extra_steps": actual_steps if minimum == 0 else None,
            "U6": u6, "U6_applicable": degraded,
            "U6_elements": {'positive_explicit_labels':positive_labels,'scope':'refusal_or_clarification_or_actual_failure; label/evidence_proxy_not_full_scientific_truth'},
            "review_limit": "L0文本语义规则由当前助手抽查复核；无独立评分API、无主观用户评阅"}

def usability(runs, identity):
    """逐题逐次保留可用性依据，无适用样本不填满分。"""
    records = [usability_run(r, identity) for r in runs]
    summary = {}
    for metric in ("U1", "U2", "U3", "U4", "U5", "U6"):
        values = [r[metric] for r in records if r[metric] is not None]
        summary[metric] = {"point": sum(values) / len(values) if values else None, "observations": len(values)}
    return {"summary": summary, "per_run": records, "U7": None, "U7_raters": 0,
            "notes": ["U1分母包括澄清/拒绝设计题；另报告题类别，不能把不可回答题伪报首次可用",
                      "U2需契约登记码；E_BACKEND在生产实现有但契约未登记，单独披露",
                      "U4数据标识必须是实际canary/snapshot，不以任意data_hash冒充数据版本",
                      "U1流程/证据条件及U4单位标注存在性不是全文科学正确性检验；换算和附加说明错误另见助手原文复核材料",
                      "U5最小工具步数独立于HTTP请求数；不明上下文/零最小步数的比值记null",
                      "U6拒答/澄清/实际失败均入分母；检查肯定的not_computable/not_configured显式标签，非全文无幻觉证明",
                      "U7无人评阅，缺失，不赋主观分"]}
