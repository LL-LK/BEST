# -*- coding: utf-8 -*-
"""
E4 证据复算脚本（只读 <WORKSPACE> 的 01-10 目录；只写本目录）。

用途：把 E4 的两批数据（r1 归档批次 / v70 归档新批次）全部关键口径一次性复算出来，
供人工核对与投稿包台账引用。不修改任何原始文件，不重评分。

用法：
    python verify_e4_evidence.py
输出：
    _work_out/复算结果_E4.json
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

# ---------------------------------------------------------------- 路径常量
ROOT = Path(r"<WORKSPACE>")
E4_ARCHIVE = ROOT / r"04_实验数据\E4_鲁棒性与安全性\实验产物"
R1_RUN = E4_ARCHIVE / "07-结果(r1权威)" / "runs" / "r1"
R1_REPORT = R1_RUN / "report-r1.json"
ITEMS_YAML = E4_ARCHIVE / "01-用例集与判据表" / "items.yaml"
RUBRIC_YAML = E4_ARCHIVE / "01-用例集与判据表" / "rubric.yaml"

V70 = ROOT / r"10_脱敏复现包\BEST_v70_E4数据更新与批注核验_20261023"
V72 = ROOT / r"10_脱敏复现包\BEST_v72_图2嵌入正文确认_20261023"
V70_EVAL = V70 / "evaluation_materials"
V70_REPRO = V70 / "work" / "E4_input" / "_复现"
GRADE_R2 = V70_REPRO / "out" / "grade_r2.json"
TIERW = V70_REPRO / "out" / "official-tierW.json"
SB_ANS = {sb: V70_REPRO / "out" / f"{sb}_answers.json" for sb in ("sb1", "sb2", "sb3")}
EXPECTED_OFFICIAL = V70_REPRO / "expected" / "official.json"
EXPECTED_METRICS = V70_REPRO / "expected" / "metrics.json"
V72_FIGDATA = V72 / "E4图复现" / "source_data.json"

MAIN_TEX = V72 / "source" / "main.tex"
SUPP_TEX = V72 / "source" / "supplementary_material.tex"
V70_REVIEW = V70 / "老师修改意见与E4核验.md"

OUT_DIR = Path(__file__).resolve().parent
OUT_JSON = OUT_DIR / "_work_out" / "复算结果_E4.json"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def parse_items_yaml(path: Path) -> list[dict]:
    """items.yaml 是扁平列表（每条以 '- id:' 开头），按行扫描即可，避免引入 yaml 依赖。"""
    txt = path.read_text(encoding="utf-8")
    items: list[dict] = []
    cur: dict | None = None
    for line in txt.splitlines():
        m = re.match(r"^- id: (\S+)", line)
        if m:
            cur = {"id": m.group(1)}
            items.append(cur)
            continue
        if cur is None:
            continue
        for key in ("tier", "fault_family", "combo_with", "base_case", "disposal", "judge", "redline"):
            mm = re.match(rf"^  {key}: (.+)$", line)
            if mm:
                cur[key] = mm.group(1).strip().strip("'\"")
        mm = re.match(r"^    inject: (.+)$", line)
        if mm:
            cur["inject"] = mm.group(1).strip().strip("'\"")
        mm = re.match(r"^    target: (.+)$", line)
        if mm:
            cur["target"] = mm.group(1).strip()
        if re.match(r"^  second_round: true", line):
            cur["second_round"] = True
        if re.match(r"^  scored_in_main: false", line):
            cur["scored_in_main"] = False
    return items


def tex_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def find_tex(path: Path, needle: str) -> list[int]:
    return [i + 1 for i, l in enumerate(tex_lines(path)) if needle in l]


def main() -> None:
    out: dict = {"generated_by": "verify_e4_evidence.py", "root": str(ROOT)}

    # ---------------------------------------------------- 0. SHA256 基线
    files = {
        "r1_report_json": R1_REPORT,
        "r1_report_md": R1_RUN / "REPORT-r1.md",
        "r1_run_card": R1_RUN / "RUN-CARD.md",
        "e4_report_md": E4_ARCHIVE / "07-结果(r1权威)" / "REPORT.md",
        "items_yaml": ITEMS_YAML,
        "rubric_yaml": RUBRIC_YAML,
        "runner_py": E4_ARCHIVE / "02-判定器与执行器" / "runner.py",
        "judge_tier_p_py": E4_ARCHIVE / "02-判定器与执行器" / "judge_tier_p.py",
        "check_disposal_scope_py": E4_ARCHIVE / "02-判定器与执行器" / "check_disposal_scope.py",
        "graders_py": E4_ARCHIVE / "02-判定器与执行器" / "graders.py",
        "guards_py": E4_ARCHIVE / "02-判定器与执行器" / "guards.py",
        "wire_faults_py": E4_ARCHIVE / "03-注入器夹具与反证" / "injectors" / "wire_faults.py",
        "broken_init_py": E4_ARCHIVE / "03-注入器夹具与反证" / "broken" / "__init__.py",
        "test_e4_py": E4_ARCHIVE / "03-注入器夹具与反证" / "tests" / "test_e4.py",
        "test_isolation_py": E4_ARCHIVE / "03-注入器夹具与反证" / "tests" / "test_isolation_e4.py",
        "check_leakage_py": E4_ARCHIVE / "04-防污染与沙箱工具" / "check_leakage.py",
        "r1_answers_all": E4_ARCHIVE / "05-过程产物-r1原始答卷" / "answers-r1" / "_all.json",
        "grade_r2_json": GRADE_R2,
        "official_tierW_json": TIERW,
        "expected_official_json": EXPECTED_OFFICIAL,
        "expected_metrics_json": EXPECTED_METRICS,
        "E4_main_35_json": V70_EVAL / "E4_main_35.json",
        "E4_results_json": V70_EVAL / "E4_results.json",
        "E4_scored_records_json": V70_EVAL / "E4_scored_records.json",
        "v72_main_tex": MAIN_TEX,
        "v72_supplementary_tex": SUPP_TEX,
        "v72_fig5_source_data": V72_FIGDATA,
        "v70_review_md": V70_REVIEW,
        "e4_min_repro_zip": ROOT / r"10_脱敏复现包\E4_最小复现包.zip",
    }
    out["sha256"] = {}
    for k, p in files.items():
        out["sha256"][k] = {"path": str(p), "sha256": sha256(p), "bytes": p.stat().st_size}

    # ---------------------------------------------------- 1. items.yaml 全量解析
    items = parse_items_yaml(ITEMS_YAML)
    out["items_total"] = len(items)
    out["items_by_tier"] = dict(Counter(i.get("tier") for i in items))
    out["items_by_family"] = dict(Counter(i.get("fault_family") for i in items))
    out["compound_items"] = [
        {k: i.get(k) for k in ("id", "tier", "fault_family", "combo_with", "base_case",
                               "inject", "target", "disposal", "judge", "redline")}
        for i in items if i.get("second_round")
    ]
    out["scored_in_main_false"] = [i["id"] for i in items if i.get("scored_in_main") is False]

    # ---------------------------------------------------- 2. r1 批次复算
    r1 = read_json(R1_REPORT)
    r1p = r1["P"]
    out["r1"] = {
        "W": {k: r1["W"][k] for k in ("n_cases", "n_pass", "pass")},
        "W_blockers": r1["W"]["blockers"],
        "W_deferred_second_round": r1["W"]["deferred_second_round"],
        "P": {k: r1p[k] for k in ("n_cases", "n_answered", "n_pass", "evaluated", "pass")},
        "P_summary": {
            "n_items": r1p["summary"]["n_items"],
            "n_graded": r1p["summary"]["n_graded"],
            "disposal_ok": r1p["summary"]["disposal_ok"],
            "disposal_rate": r1p["summary"]["disposal_rate"],
            "n_weighted_graded": r1p["summary"]["n_weighted_graded"],
            "n_weighted_pass": r1p["summary"]["n_weighted_pass"],
            "must_not_call_violations": r1p["summary"]["must_not_call_violations"],
            "credential_in_params": r1p["summary"]["credential_in_params"],
            "n_blockers": r1p["summary"]["n_blockers"],
            "by_disposal": r1p["summary"]["by_disposal"],
            "by_judge": r1p["summary"]["by_judge"],
            "na_metrics": r1p["summary"]["na_metrics"],
        },
        "metascore": r1["_metascore"],
        "P_blocker_frequency": dict(Counter(b for c in r1p["cases"] for b in c.get("blockers", []))),
        "redline_case_records": {
            c["id"]: {
                "want_disposal": c["want_disposal"], "got_disposal": c["got_disposal"],
                "disposal_ok": c["disposal_ok"], "judge": c["judge"],
                "must_not_call_violated": c["must_not_call_violated"],
                "weighted": c["weighted"], "blockers": c["blockers"],
                "m5_no_masquerade": c["dims"]["m5_no_masquerade"],
                "m6_containment": c["dims"]["m6_containment"],
            }
            for c in r1p["cases"] if c.get("must_not_call_violated")
        },
    }
    # r1 是否存在"失败请求被包装成成功答案"：m5_no_masquerade 在 Tier P 全部为 None
    out["r1"]["masquerade_judged_on_TierP"] = any(
        c["dims"]["m5_no_masquerade"] is not None for c in r1p["cases"]
    )

    # ---------------------------------------------------- 3. v70 新批次复算
    grade = read_json(GRADE_R2)
    rec = read_json(V70_EVAL / "E4_scored_records.json")
    results = read_json(V70_EVAL / "E4_results.json")
    exp_off = read_json(EXPECTED_OFFICIAL)
    exp_met = read_json(EXPECTED_METRICS)
    fig = read_json(V72_FIGDATA)["E4"]

    out["v70"] = {"repeats": {}, "compound": [], "consistency": {}}
    cat_counts, cat_correct = Counter(), Counter()
    for sb in ("sb1", "sb2", "sb3"):
        P = grade[sb]["P"]          # grade_r2.json：含红线/凭据/阻断项/metrics 维度
        C = grade[sb]["C"]          # grade_r2.json：18 条复合题
        S = rec["repeats"][sb]      # E4_scored_records.json：含 category 字段
        d_ok = sum(1 for x in P if x["disposal_ok"])
        w_gr = sum(1 for x in P if x["weighted"] is not None)
        w_pass = sum(1 for x in P if x["pass"])
        c_ok = sum(1 for x in C if x["disposal_ok"])
        for x in S:
            cat_counts[x["category"]] += 1
            cat_correct[x["category"]] += bool(x["disposal_ok"])
        out["v70"]["repeats"][sb] = {
            "P_disposal": f"{d_ok}/{len(P)}",
            "P_disposal_rate": round(d_ok / len(P), 4),
            "P_weighted_pass": f"{w_pass}/{w_gr}",
            "P_n_na_weighted": sum(1 for x in P if x["weighted"] is None),
            "compound_disposal": f"{c_ok}/{len(C)}",
            "must_not_call_violations": [x["id"] for x in P + C if x.get("must_not_call_violated")],
            "credential_in_params": sum(1 for x in P + C if x.get("credential_in_params")),
            "disposal_fail_ids": [x["id"] for x in P if not x["disposal_ok"]],
            "weighted_fail_ids": [x["id"] for x in P if x["weighted"] is not None and not x["pass"]],
            "blockers": sorted({b for x in P + C for b in x.get("blockers", [])}),
            "masquerade_judged_any": any(x["dims"].get("m5_no_masquerade") is not None for x in P + C),
        }
        out["v70"]["compound"].append({
            "sb": sb,
            "rows": [{
                "id": x["id"], "want": x["want_disposal"], "got": x["got_disposal"],
                "ok": x["disposal_ok"], "weighted": x["weighted"],
                "n_applicable_metrics": x["n_applicable_metrics"],
                "status": x["status"], "blockers": x["blockers"],
                "must_not_call_violated": x["must_not_call_violated"],
                "m5_no_masquerade": x["dims"].get("m5_no_masquerade"),
                "m6_containment": x["dims"].get("m6_containment"),
                "m4_science_stop": x["dims"].get("m4_science_stop"),
                "judge": x["judge"],
            } for x in C],
        })
    out["v70"]["category_aggregate"] = {
        k: {"correct": cat_correct[k], "total": cat_counts[k]} for k in sorted(cat_counts)
    }
    out["v70"]["scored_records_agree"] = (
        rec["repeats"] and
        all(len(v) == 35 for v in rec["repeats"].values())
    )
    out["v70"]["results_json"] = results
    out["v70"]["expected_official"] = exp_off
    out["v70"]["expected_metrics"] = exp_met
    out["v70"]["fig5_source_data"] = fig
    out["v70"]["compound_digest"] = results.get("digest")

    # 一致性：scored_records / results.json / 图5 source_data 三方闭合
    out["v70"]["cross_check"] = {
        "fig5_language_matches_records":
            fig["language"] == {"correct": sum(cat_correct.values()), "total": sum(cat_counts.values())},
        "fig5_categories_match_records": all(
            fig["categories"][i]["correct"] == cat_correct[c] and
            fig["categories"][i]["total"] == cat_counts[c]
            for i, c in enumerate("ABCDE")
        ),
        "protocol_15_15": fig["protocol"] == {"correct": 15, "total": 15},
        "disposal_matches_results_json": all(
            [sum(bool(x["disposal_ok"]) for x in rec["repeats"][sb]), 35]
            == results["repeats"][sb]["disposal"] for sb in ("sb1", "sb2", "sb3")
        ),
    }

    # 复合答卷独立性：同一答卷内 18 条复合题各自的 answer_text 去重情况
    indep = {}
    for sb, p in SB_ANS.items():
        ans = read_json(p)
        ctexts = {i: ans[i]["answer_text"] for i in ans if i.startswith("RB-C")}
        groups: dict[str, list[str]] = defaultdict(list)
        for i, t in ctexts.items():
            groups[t].append(i)
        indep[sb] = {
            "n_compound": len(ctexts),
            "n_distinct_answer_text": len(groups),
            "groups": {",".join(sorted(v)): (list(groups.keys())[0][:60]) for v in groups.values()},
            "http_requests_by_item": {i: ans[i].get("http_requests") for i in sorted(ctexts)},
            "tool_calls_by_item": {
                i: [tc.get("tool") for tc in (ans[i].get("tool_calls") or [])] for i in sorted(ctexts)
            },
        }
    out["v70"]["compound_answer_independence"] = indep

    # ---------------------------------------------------- 4. 论文文本定位
    out["paper"] = {
        "main_tex": {
            "E4_disposal_34_35": find_tex(MAIN_TEX, "34/35"),
            "E4_weighted": find_tex(MAIN_TEX, "8/18"),
            "E4_15_15": find_tex(MAIN_TEX, "15/15"),
            "E4_induced_5_5": find_tex(MAIN_TEX, "诱导话术子类为 5/5"),
            "E4_table_row": find_tex(MAIN_TEX, "协议故障场景 & 15/15"),
            "contains_74_29": any("74.29" in l or "0.7429" in l for l in tex_lines(MAIN_TEX)),
            "contains_26_35": any("26/35" in l for l in tex_lines(MAIN_TEX)),
            "contains_must_not_call": any("must_not_call" in l for l in tex_lines(MAIN_TEX)),
            "contains_RBC": any("RB-C" in l for l in tex_lines(MAIN_TEX)),
        },
        "supp_tex": {
            "B7_protocol_table": find_tex(SUPP_TEX, "E4 协议故障场景（协议层 15 条）"),
            "B7_utterance_table": find_tex(SUPP_TEX, "E4 话术场景（话术层 35 条）"),
            "B8_metrics": find_tex(SUPP_TEX, "E4 七项指标定义与权重"),
            "B8_safety": find_tex(SUPP_TEX, "E4 八条安全约束"),
            "contains_RBC": any("RB-C" in l for l in tex_lines(SUPP_TEX)),
            "forbidden_call_empty_note": [
                i + 1 for i, l in enumerate(tex_lines(SUPP_TEX)) if "禁止调用约束均为空列表" in l
            ],
        },
    }

    # ---------------------------------------------------- 5. 落盘
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------------------------------------------------- 6. 控制台摘要
    print("=" * 78)
    print("E4 证据复算摘要")
    print("=" * 78)
    print(f"items.yaml: {out['items_total']} 条 = {out['items_by_tier']}")
    print(f"  second_round(复合) {len(out['compound_items'])} 条, scored_in_main=false "
          f"{len(out['scored_in_main_false'])} 条")
    r = out["r1"]
    print(f"[r1 归档批次] W {r['W']['n_pass']}/{r['W']['n_cases']} | "
          f"P disposal {r['P_summary']['disposal_ok']}/{r['P_summary']['n_items']} "
          f"= {r['P_summary']['disposal_rate']} | "
          f"weighted {r['P_summary']['n_weighted_pass']}/{r['P_summary']['n_weighted_graded']} | "
          f"红线 {r['P_summary']['must_not_call_violations']} | 阻断 {r['P_summary']['n_blockers']}")
    print(f"  Tier P 是否自动判定 m5 不伪装: {r['masquerade_judged_on_TierP']}")
    print(f"  W deferred_second_round: {len(r['W_deferred_second_round'])} 条 (纯 ID 串，无判定记录)")
    for sb, v in out["v70"]["repeats"].items():
        print(f"[v70 新批次 {sb}] P {v['P_disposal']} | weighted {v['P_weighted_pass']} | "
              f"复合 {v['compound_disposal']} | 红线 {v['must_not_call_violations']} | "
              f"masquerade自动判定 {v['masquerade_judged_any']}")
    print(f"  类别汇总: {out['v70']['category_aggregate']}")
    print(f"  三方闭合: {out['v70']['cross_check']}")
    for sb, v in indep.items():
        print(f"  复合答卷独立性 {sb}: {v['n_compound']} 题 -> {v['n_distinct_answer_text']} 份不同正文")
    print(f"  论文含 74.29/26-35/must_not_call/RB-C: "
          f"{out['paper']['main_tex']['contains_74_29']}/"
          f"{out['paper']['main_tex']['contains_26_35']}/"
          f"{out['paper']['main_tex']['contains_must_not_call']}/"
          f"{out['paper']['main_tex']['contains_RBC']}")
    print(f"\n写入: {OUT_JSON}")


if __name__ == "__main__":
    main()
