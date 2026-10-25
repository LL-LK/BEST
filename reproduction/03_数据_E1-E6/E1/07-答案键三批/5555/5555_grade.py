# -*- coding: utf-8 -*-
"""Run the frozen E1 graders.py on the 5555 answer key (astro-best 28-question run).

5555 ships a structured answers.json (verdict/tool/arguments) + per-task .md files.
Unlike the 4444/3333 runs (where tool_calls were hardcoded canonical calls), here we
build the *real* predicted tool_calls from answers.json, so toolset/param/convert/
redundant now reflect 5555's actual content instead of being locked to a proxy.

  verdict "call"    -> answer   -> first-round tool_calls = [{tool, args}]
  verdict "clarify"-> clarify  -> first-round tool_calls = [] (clarify first)
  verdict "refuse" -> reject   -> first-round tool_calls = []

answer_text for clarify/reject is the full per-task .md (so the grader's probe /
reason-alias matching sees real content). No repository files modified.
"""
import os, sys, json, types, importlib.util, re

from pathlib import Path

_HERE = Path(__file__).resolve()
ANSW = str(_HERE.parent)          # 答案与脚本同目录
PROJ = str(_HERE.parents[3])      # 仓库根（不硬编码本机路径）
NL2 = os.path.join(PROJ, "evals", "nl2tool")
sys.path.insert(0, PROJ)

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

# ── load 5555 structured answers ──
aj = json.load(open(os.path.join(ANSW, "answers.json"), encoding="utf-8"))
ITEMS = {it["id"]: it for it in aj["items"]}
VERDICT_MAP = {"call": "answer", "clarify": "clarify", "refuse": "reject"}

def read_md(tid):
    p = os.path.join(ANSW, f"{tid}.md")
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""

grades = []
for i in range(1, 29):
    tid = f"NL2T-{i:02d}"
    task = TASKS[tid]
    it = ITEMS.get(tid, {})
    v = it.get("verdict")
    route = VERDICT_MAP.get(v, "?")
    args = it.get("arguments") or {}
    if not isinstance(args, dict):
        args = {}
    if route == "answer":
        calls = [{"tool": it.get("tool"), "args": args}]
    else:
        calls = []   # first round: clarify/reject issue no call
    text = read_md(tid)
    trace = {"tool_calls": calls, "answer_text": text, "http_requests": 0,
             "s1_events": [], "model_id": "5555-answer-key"}
    g = gr.grade_task(task, trace, schema_props=schema_props, context_bindings=None)
    g["pred_route"] = route
    g["gold_route"] = task.get("route")
    g["pred_tool"] = it.get("tool")
    grades.append(g)

summary = gr.score_run(grades)

print("=" * 78)
print("E1 六维加权汇总  (5555 答案键 × 冻结 gold graders, 真实 tool_calls)")
print("=" * 78)
W = gr.GRADER_WEIGHTS
print(f"{'维度':<10}{'权重':>7}{'均值':>9}{'样本n':>7}{'通过线':>9}{'警戒线':>9}  结果")
print("-" * 78)
for dim in W:
    v = summary["dims"].get(dim); n = summary["dim_n"].get(dim)
    pl = gr.DIM_PASS_LINES[dim]; wl = gr.DIM_WARN_LINES[dim]
    res = ""
    if v is None: res = "不适用"
    elif n < gr.DIM_MIN_N: res = "样本不足(不阻断)"
    elif v < pl: res = "未过逐维线 ❌"
    elif v < wl: res = "观察区 ⚠"
    else: res = "达标 ✅"
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
hdr = f"{'题':<9}{'gold':<9}{'5555':<9}{'tool':>6}{'param':>7}{'conv':>7}{'redun':>7}{'clar':>7}{'rej':>7}  redline"
print(hdr); print("-" * 78)
def f(x): return "  -  " if x is None else f"{x:.2f}"
for g in grades:
    d = g["dims"]
    rl = ",".join(g["red_lines"]) if g["red_lines"] else ""
    print(f"{g['task_id']:<9}{g['gold_route']:<9}{g['pred_route']:<9}"
          f"{f(d.get('toolset')):>6}{f(d.get('param')):>7}{f(d.get('convert')):>7}"
          f"{f(d.get('redundant')):>7}{f(d.get('clarify')):>7}{f(d.get('reject')):>7}  {rl}")

out = {"summary": {k: v for k, v in summary.items()},
       "per_task": [{k: g[k] for k in ("task_id","gold_route","pred_route","pred_tool","dims","red_lines")} for g in grades]}
with open(os.path.join(ANSW, "5555_grade_result.json"), "w", encoding="utf-8") as fp:
    json.dump(out, fp, ensure_ascii=False, indent=2, default=str)
print("\n→ 机器可读结果已写 5555_grade_result.json")
