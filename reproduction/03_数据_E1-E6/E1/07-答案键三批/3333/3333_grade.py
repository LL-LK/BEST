# -*- coding: utf-8 -*-
"""Run the frozen E1 graders.py on the 3333 answer key (astro-best 28-question run).

Same methodology as the 4444 run (see 4444_grade.py) so the two keys are directly
comparable. Only paths + the route-label extractor changed.

Key honesty note
----------------
- toolset / param / convert / redundant are scored against the *canonical* expected
  calls (DIRECT_CALLS, identical to the 4444 run) → these dims are the same for both
  keys; they isolate the primer-blind-run effect (06/09/10/12 are gold=answer but the
  blind run can only clarify, so toolset=0 for them).
- clarify / reject are scored from each key's actual answer_text → this is where 3333
  and 4444 diverge.
No repository files are modified (graders loaded via importlib stubs; evals/__init__ absent).
"""
import os, sys, json, types, importlib.util, re

from pathlib import Path

_HERE = Path(__file__).resolve()
ANSW = str(_HERE.parent)          # 答案与脚本同目录
PROJ = str(_HERE.parents[3])      # 仓库根（不硬编码本机路径）
NL2 = os.path.join(PROJ, "evals", "nl2tool")
sys.path.insert(0, PROJ)   # so `src` resolves as a namespace package for normalizers

sys.modules.setdefault("evals", types.ModuleType("evals"))
sys.modules["evals"].__path__ = [os.path.join(PROJ, "evals")]
nl2pkg = types.ModuleType("evals.nl2tool")
nl2pkg.__path__ = [NL2]
sys.modules["evals.nl2tool"] = nl2pkg

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

norm = _load("evals.nl2tool.normalizers", os.path.join(NL2, "normalizers.py"))
gr = _load("evals.nl2tool.graders", os.path.join(NL2, "graders.py"))

import yaml
with open(os.path.join(NL2, "tasks.yaml"), encoding="utf-8") as f:
    TASKS = {t["id"]: t for t in yaml.safe_load(f)["tasks"]}

with open(os.path.join(PROJ, "references", "tools.schema.json"), encoding="utf-8") as f:
    schema = json.load(f)
schema_props = {t["name"]: t["inputSchema"]["properties"] for t in schema["tools"]}

# Canonical expected direct calls (identical to the 4444 run for fair comparison).
DIRECT_CALLS = {
    "NL2T-01": [{"tool": "list_catalogs", "args": {}}],
    "NL2T-02": [{"tool": "describe_catalog", "args": {"catalog": "ps1"}}],
    "NL2T-03": [{"tool": "resolve_name", "args": {"name": "M31"}}],
    "NL2T-04": [{"tool": "cone_search", "args": {"ra": 10.68, "dec": 41.27, "radius_arcsec": 60.0, "catalog": "ps1"}}],
    "NL2T-11": [{"tool": "cone_search", "args": {"ra": 120.3, "dec": -20.4, "radius_arcsec": 5.0, "catalog": "std"}}],
    "NL2T-14": [{"tool": "cone_search", "args": {"ra": 187.5, "dec": 20.0, "radius_arcsec": 180.0, "catalog": "ps1"}}],
    "NL2T-15": [{"tool": "cone_search", "args": {"ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0,
                                                 "catalog": "gaia_dr3_18", "columns": ["gaia_dr3_18_phot_g_mean_mag"]}}],
    "NL2T-16": [{"tool": "cone_search", "args": {"ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0,
                                                 "catalog": "splus_dr4", "columns": ["splus_dr4_r_pstotal"]}}],
    "NL2T-21": [{"tool": "cone_search", "args": {"ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0, "catalog": "ps1",
                                                 "sort": "ps1_rpsf", "order": "asc", "nearest_only": False}}],
    "NL2T-25": [{"tool": "cone_search", "args": {"ra": 180.0, "dec": 30.0, "radius_arcsec": 60.0, "catalog": "ps1"}}],
}

def read_answer(tid):
    with open(os.path.join(ANSW, f"{tid}.md"), encoding="utf-8") as f:
        return f.read()

def pred_route(text):
    # 判定 line appears as "## 1. 判定" then the route declaration paragraph.
    m = re.search(r"^##\s*1[\.、]?\s*判定\s*\n+(\s*(?:-\s*)?)(.+)$", text, re.M)
    if not m:
        return "?"
    line = m.group(2).strip()
    s = re.sub(r"^[-\s]*", "", line)          # drop leading bullet if any
    if s.startswith("**直接调用"):
        return "answer"
    if s.startswith("**应当拒绝"):
        return "reject"
    if "澄清" in s:                            # last resort: explicit clarify phrasing
        return "clarify"
    if "直接调用" in s:
        return "answer"
    if "拒绝" in s:
        return "reject"
    return "?"

grades = []
for i in range(1, 29):
    tid = f"NL2T-{i:02d}"
    task = TASKS[tid]
    text = read_answer(tid)
    pr = pred_route(text)
    calls = DIRECT_CALLS.get(tid, [])
    trace = {"tool_calls": calls, "answer_text": text, "http_requests": 0,
             "s1_events": [], "model_id": "3333-answer-key"}
    g = gr.grade_task(task, trace, schema_props=schema_props, context_bindings=None)
    g["pred_route"] = pr
    g["gold_route"] = task.get("route")
    grades.append(g)

summary = gr.score_run(grades)

print("=" * 78)
print("E1 六维加权汇总  (3333 答案键 × 冻结 gold graders)")
print("=" * 78)
W = gr.GRADER_WEIGHTS
print(f"{'维度':<10}{'权重':>7}{'均值':>9}{'样本n':>7}{'通过线':>9}{'警戒线':>9}  结果")
print("-" * 78)
for dim in W:
    v = summary["dims"].get(dim)
    n = summary["dim_n"].get(dim)
    pl = gr.DIM_PASS_LINES[dim]
    wl = gr.DIM_WARN_LINES[dim]
    res = ""
    if v is None:
        res = "不适用"
    elif n < gr.DIM_MIN_N:
        res = "样本不足(不阻断)"
    elif v < pl:
        res = "未过逐维线 ❌"
    elif v < wl:
        res = "观察区 ⚠"
    else:
        res = "达标 ✅"
    print(f"{dim:<10}{W[dim]:>7.2f}{('%.4f'%v) if v is not None else '  -  ':>9}{str(n):>7}{pl:>9.2f}{wl:>9.2f}  {res}")
print("-" * 78)
print(f"加权总分 weighted = {summary['weighted']:.4f}")
print(f"放行线 PASS_SCORE = {gr.PASS_SCORE}  观察线 WARN_SCORE = {gr.WARN_SCORE}")
print(f"pass = {summary['pass']}   warn = {summary['warn']}")
print(f"红线任务 red_line_tasks = {summary['red_line_tasks']}")
print(f"逐维未过线 dim_failures = {summary['dim_failures']}")
print(f"样本不足维 thin_dims = {summary['thin_dims']}")
print(f"任务数 n_tasks = {summary['n_tasks']}")

print()
print("=" * 78)
print("逐题维度明细")
print("=" * 78)
hdr = f"{'题':<9}{'gold':<9}{'3333':<9}{'tool':>6}{'param':>7}{'conv':>7}{'redun':>7}{'clar':>7}{'rej':>7}  redline"
print(hdr)
print("-" * 78)
def f(x):
    return "  -  " if x is None else f"{x:.2f}"
for g in grades:
    d = g["dims"]
    rl = ",".join(g["red_lines"]) if g["red_lines"] else ""
    print(f"{g['task_id']:<9}{g['gold_route']:<9}{g['pred_route']:<9}"
          f"{f(d.get('toolset')):>6}{f(d.get('param')):>7}{f(d.get('convert')):>7}"
          f"{f(d.get('redundant')):>7}{f(d.get('clarify')):>7}{f(d.get('reject')):>7}  {rl}")

out = {"summary": {k: v for k, v in summary.items()},
       "per_task": [{k: g[k] for k in ("task_id","gold_route","pred_route","dims","red_lines")} for g in grades]}
with open(os.path.join(ANSW, "3333_grade_result.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2, default=str)
print("\n→ 机器可读结果已写 3333_grade_result.json")
