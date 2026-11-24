# -*- coding: utf-8 -*-
"""只从**原料**核实 E5 的三项门禁与关键数字 —— 不读任何结论文档。

读的全是: 真实批次目录的输出文件与 mtime、入库采集表的 provenance 字段、
代码源码文本、git 跟踪面。每个结论后面都跟着"它是从哪个文件算出来的"。
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))  # 直跑本脚本时让仓根进 import 面
SCRATCH = pathlib.Path(tempfile.gettempdir()) / "e5_scratch"
LEGACY = ROOT / "temp" / "scratch"
FORBIDDEN = ("expect_tools", "should_call_best", "reason_code", "must_not_call",
             "anti_patterns", "gold_result", "data_anchor", "assertions",
             "items.yaml", "hypotheses.yaml", "evals/ablation")


def banner(title):
    print("\n" + "=" * 66)
    print(f"  {title}")
    print("=" * 66)


# ---------------------------------------------------------------- ① 答案键隔离
banner("① 答案键隔离: 从真实 scratch 向上走, 能不能摸到仓")
if not SCRATCH.is_dir():
    print(f"  !! scratch 根不存在: {SCRATCH}")
else:
    cursor, reached = SCRATCH.resolve(), False
    while cursor.parent != cursor:
        repo_here = (cursor / "astro-best").exists()
        key_here = (cursor / "evals" / "ablation" / "items.yaml").exists()
        print(f"  {cursor}  astro-best={repo_here}  items.yaml={key_here}")
        reached = reached or repo_here or key_here
        cursor = cursor.parent
    print(f"  结论: 从 scratch 向上{'能' if reached else '**不能**'}摸到仓/答案键 "
          f"(D-17 结构修法{'失效' if reached else '成立'})")

print("  对照: 旧位置 temp/scratch 在仓内吗? ->",
      str(LEGACY.resolve()).startswith(str(ROOT.resolve())),
      f"(==仓内, 旧批次向上三级即可到 {ROOT / 'evals' / 'ablation' / 'items.yaml'})")

print("  新位置 10 批的提示词里有没有答案键物料:")
for batch in sorted(SCRATCH.iterdir()):
    if not batch.is_dir():
        continue
    hits = [k for k in FORBIDDEN
            for p in batch.rglob("*.txt")
            if k in p.read_text(encoding="utf-8", errors="ignore")]
    print(f"    {batch.name:10s} 禁词命中: {len(hits) or '0'}")

# ---------------------------------------------------------------- ② 批次唯一 + 单写者
banner("② 批次唯一 / 并发写: 从真实输出文件的 mtime 直接重算")

def writer_stats(batch_dir):
    files = sorted((p.stat().st_mtime, p.name) for p in batch_dir.rglob("*.json"))
    if len(files) < 2:
        return len(files), 0.0, "-"
    gaps = [(b - a, files[i + 1][1]) for i, (a, b) in enumerate(zip(
        [t for t, _ in files], [t for t, _ in files][1:]))]
    worst = max(gaps)
    return len(files), round(worst[0], 3), worst[1]

print(f"  {'批次':12s} {'输出数':>5s} {'最大空档(s)':>10s}  空档出现在     判读")
for b in sorted(SCRATCH.iterdir()):
    if b.is_dir():
        n, gap, at = writer_stats(b)
        verdict = "疑似两个写者(>60s)" if gap > 60 else "单波(干净)"
        print(f"  {b.name:12s} {n:5d} {gap:10.3f}  {at:14s} {verdict}")
print("  -- 旧位置对照 (temp/scratch) --")
for b in sorted(LEGACY.iterdir()):
    if b.is_dir():
        n, gap, at = writer_stats(b)
        verdict = "疑似两个写者(>60s) <<== D-18" if gap > 60 else "单波"
        print(f"  {b.name:12s} {n:5d} {gap:10.3f}  {at:14s} {verdict}")
print("  复用批次名实测: 对新位置已有批次再投放一次 ->")
from evals.ablation.iso import paths as iso_paths  # 受管实现, 仓内
import os as _os
_os.environ[iso_paths.ENV_SCRATCH] = str(SCRATCH)
from evals.ablation.iso import stage as iso_stage
try:
    iso_stage.stage_batch(sorted(SCRATCH.iterdir())[0].name, ["B3"], source=SCRATCH)
    print("    !! 复用名竟然投放成功 —— 门禁缺失")
except iso_stage.BatchBusy as exc:
    print(f"    被拒 (exit=3): {str(exc)[:80]}...")

# ---------------------------------------------------------------- ③ 噪声底重算
banner("③ 同条件噪声底: 直接从 b3_s1/s2/s3 的 route 输出重算 (不看文档)")
routes = {}
for name in ("b3_s1", "b3_s2", "b3_s3"):
    d = SCRATCH / name / "out" / "B3"
    routes[name] = {p.stem: json.loads(p.read_text(encoding="utf-8"))["route"]
                    for p in d.glob("*.json")}
items = sorted(set.intersection(*[set(r) for r in routes.values()]))
pairwise = [("b3_s1", "b3_s2"), ("b3_s1", "b3_s3"), ("b3_s2", "b3_s3")]
agree = []
for a, b in pairwise:
    hit = sum(routes[a][i] == routes[b][i] for i in items)
    agree.append(hit / len(items))
    print(f"  {a} ↔ {b}: {hit}/{len(items)} = {hit / len(items):.3f}")
print(f"  平均一致率 {sum(agree) / len(agree):.3f} -> 噪声底 "
      f"{1 - sum(agree) / len(agree):.1%}")
print(f"  三轮全不一致的题: {[i for i in items if len({routes[n][i] for n in routes}) > 1]}")

# ---------------------------------------------------------------- ④ 代码面
banner("④ 代码面: 门禁实现到底在哪、写轨迹有没有并发保护")

def grep(path, pattern):
    return subprocess.run(["git", "grep", "-n", pattern, "--", str(path)],
                          capture_output=True, text=True, cwd=ROOT).stdout.strip()

print("  temp/stage_scratch.py 与 temp/audit_scratch.py 被 git 跟踪吗?")
tracked = subprocess.run(["git", "ls-files", "temp/stage_scratch.py",
                          "temp/audit_scratch.py"], capture_output=True,
                         text=True, cwd=ROOT).stdout.strip()
print(f"    git ls-files -> {tracked or '(空: 未跟踪, 不入交付包)'}")
print("  temp/decision_iso (逐格提示词源) 被 git 跟踪吗? ->",
      subprocess.run(["git", "ls-files", "temp/decision_iso"],
                     capture_output=True, text=True, cwd=ROOT).stdout.strip() or "(空: 未跟踪)")
print("  evals/ablation/iso/ 在工作区存在吗?",
      (ROOT / "evals" / "ablation" / "iso" / "stage.py").is_file())
rb = (ROOT / "evals" / "ablation" / "harness" / "run_batch.py").read_text(encoding="utf-8")
for probe in ("_acquire_trace_lock", "os.replace", "overwrite: bool = False",
              "FileExistsError"):
    print(f"    write_traces 相关判据 {probe!r}: {'在源码里' if probe in rb else '!! 不在'}")
print("  旧实现直写痕迹 path.write_text( 在 run_batch.py: ",
      "已被原子提交取代" if "path.write_text(json.dumps(run" not in rb else "!! 仍在直写")

# ---------------------------------------------------------------- ⑤ 两个 990
banner("⑤ '990' 到底有几个: 直接读入库件与归档件")
cap = json.loads((ROOT / "evals" / "ablation" / "captures"
                  / "all-systems-rebuild.json").read_text(encoding="utf-8"))
prov = cap.get("provenance", {})
dec = cap["decisions"]
n_units = sum(len(v) for v in dec.values())
n_runs = sum(len(attempts) for v in dec.values() for attempts in v.values())
print(f"  all-systems-rebuild.json: {len(dec)} 装配 × {n_units // len(dec)} 单元"
      f" = {n_units} 单元 × {n_runs // n_units} 轮 = {n_runs} 轮")
for k in ("model_kind", "producer", "same_family_bias", "claim_scope"):
    print(f"    provenance.{k} = {prov.get(k)}")
notes = prov.get("notes", "")
print(f"    provenance.notes 首句 = {notes[:90]}...")
arch = (ROOT / "docs" / "archive" / "e5-REPORT-live-2026-10-10.md")
head = arch.read_text(encoding="utf-8").splitlines()[:12]
for line in head:
    if any(w in line for w in ("规模", "mode", "生成时间")):
        print(f"  归档 live 报告: {line.strip()}")
print(f"  归档报告的源数据 temp/capture_live.json 还在吗? -> "
      f"{(ROOT / 'temp' / 'capture_live.json').exists()}  (=不可再生)")
indep3 = ROOT / "temp" / "indep3"
n_indep = len(list(indep3.rglob("*"))) if indep3.is_dir() else 0
print(f"  temp/indep3 真实独立会话文件数: {n_indep} (这些是表述段, 非决策段)")

# ---------------------------------------------------------------- ⑥ 轨迹写实测
banner("⑥ write_traces 原子性/拒写 现场实测")
tmp = pathlib.Path(tempfile.mkdtemp(prefix="wt_probe_"))
from evals.ablation.harness.run_batch import write_traces
report = {"runs": [{"system": "B3", "item": "E5-D01", "attempt": 1, "route": "answer"}]}
write_traces(report, tmp)
print(f"  首写成功: {sorted(p.name for p in (tmp / 'B3').iterdir())}")
try:
    write_traces(report, tmp)
    print("  !! 二次同名写入竟然成功 —— 拒写缺失")
except FileExistsError:
    print("  二次同名写入被拒 (FileExistsError) —— 只增不改有执行者")
print(f"  目录里有无半截 .tmp: {[p.name for p in (tmp / 'B3').iterdir() if '.tmp' in p.name]}")
print(f"  写锁目录是否已释放: {(tmp / '.write_lock').exists()} (False=已释放)")
print(f"  成品内容可解析: {json.loads((tmp / 'B3' / 'E5-D01__a1.json').read_text(encoding='utf-8'))}")

print("\n>>> 核实完成: 以上每行都出自原料文件/源码/实测, 未引用任何结论文档。")
