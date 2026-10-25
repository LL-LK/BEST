#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E4 三箱泄漏审计（只读，不改任何文件）。

审计五层:
    1. 结构黑名单: 盒内不得出现 evals/ temp/ docs/ answers/ 等评测侧目录与文件;
    2. 答案指纹: 从 items.yaml 抽"答案侧原文"(reject.suggest / stop.report /
       clarify.options / correction.to / fault.inject), 在盒内做子串扫描 ——
       这是比文件名更强的判据: 文件改名成 notes.txt, 这些句子仍在;
    3. 路径泄漏: 盒内不得出现沙箱根 / 源仓库 / _answers 的绝对路径;
    4. 跨箱引用: sb1 里不得出现 sb2/sb3 的名字或路径（三箱必须互不可见）;
    5. 答案面隔离: 每箱答案目录必须在盒外、且构建后为空（仅允许 batch-manifest.json）。

输出: 直接打印 + 写 `_验收/泄漏审计报告.md`（报告是脚本产物，不手写）。
命中任意一条即 exit 1。
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BOXES = ("sb1", "sb2", "sb3")
DEFAULT_SOURCE = Path(r"<USER_HOME>\OneDrive\桌面\AI-archive-pre-sinking-snapshot-20261010\E4-work")

FORBIDDEN_DIRS = {"evals", "temp", "docs", "test", ".workbuddy", "runs",
                  "nl2tool-candidate-answers", "batch_input", "leak_probe", "broken", "fixtures"}
FORBIDDEN_FILES = {"items.yaml", "rubric.yaml", "graders.py", "runner.py", "judge_tier_p.py",
                   "positive.py", "composite.py", "check_disposal_scope.py",
                   "check_spec_reachability.py", "make_answer_box.py", "make_batch_input.py",
                   "check_leakage.py", "REPORT.md", "REPORT-r1.md", "RUN-CARD.md",
                   "DELTA.md", "PATCH.diff", "report-r1.json", "report-all.json",
                   "answers.json", "e4_responses.json", "e4_p_judged.json"}
FORBIDDEN_SUFFIXES = (".diff", ".patch", ".zip")
MIN_TOKEN = 10          # 指纹最短长度: 太短的串(如 "E_BACKEND")在源码里合法存在


PUBLIC_DIRS = ("references", "src", "contracts", "static", "rag", "agents", "templates")
PUBLIC_FILES = ("SKILL.md", "README.md", "architecture.md", "manifest.yaml")


def public_corpus(source: Path) -> str:
    """被测对象自己的公开文档与源码 —— 用于区分"答案措辞"与"公共术语"。

    为什么要这一步: 标注的 correction.to 里会出现 `gaia_dr3_18` 这类**星表名**,
    它本来就写在 references/ 里, 模型读到它是正常的工具知识, 不是答案泄漏。
    不区分就会把"工具文档"报成"泄题", 而误杀会让真泄漏淹在噪声里。
    """
    chunks = []
    for name in PUBLIC_FILES:
        f = source / name
        if f.is_file():
            chunks.append(f.read_text(encoding="utf-8", errors="ignore"))
    for d in PUBLIC_DIRS:
        root = source / d
        if not root.is_dir():
            continue
        for f in root.rglob("*"):
            if f.is_file() and f.suffix.lower() in {".md", ".py", ".yaml", ".yml", ".json", ".txt"}:
                chunks.append(f.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def answer_tokens(items_path: Path, public: str = "") -> tuple[dict[str, str], list[str]]:
    """从标注抽答案侧原文 → ({原文: 出处}, 被排除的公共词)。

    规则: 若该原文在被测对象的公开面里也出现, 视为**公共术语**（如星表名）,
    排除并单列 —— 排除项要打印出来, 不能静默吞掉。
    """
    doc = yaml.safe_load(items_path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for it in doc["items"]:
        iid = it.get("id", "?")
        for s in (it.get("reject") or {}).get("suggest") or []:
            if isinstance(s, str) and len(s) >= MIN_TOKEN:
                out[s] = f"{iid}.reject.suggest"
        for s in (it.get("stop") or {}).get("report") or []:
            if isinstance(s, str) and len(s) >= MIN_TOKEN:
                out[s] = f"{iid}.stop.report"
        for s in (it.get("clarify") or {}).get("options") or []:
            if isinstance(s, str) and len(s) >= MIN_TOKEN:
                out[s] = f"{iid}.clarify.options"
        corr = (it.get("correction") or {}).get("to")
        if isinstance(corr, str) and len(corr) >= MIN_TOKEN:
            out[corr] = f"{iid}.correction.to"
        inj = (it.get("fault") or {}).get("inject")
        if isinstance(inj, str) and len(inj) >= MIN_TOKEN:
            out[inj] = f"{iid}.fault.inject"
        note = it.get("note")
        if isinstance(note, str) and len(note) >= 2 * MIN_TOKEN:
            out[note] = f"{iid}.note"
    if public:
        kept, dropped = {}, []
        for tok, src in out.items():
            (dropped.append(f"{src}: {tok[:30]}") if tok in public else kept.__setitem__(tok, src))
        return kept, dropped
    return out, []


def iter_text_files(box: Path):
    for p in box.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".md", ".txt", ".py", ".yaml", ".yml",
                                                ".json", ".csv", ".toml", ".cfg", ".ini"}:
            yield p


def check_structure(box: Path) -> list[str]:
    hits = []
    for p in box.rglob("*"):
        rel = p.relative_to(box).as_posix()
        if p.is_dir() and p.name in FORBIDDEN_DIRS:
            hits.append(f"[结构] 目录不该存在: {rel}/")
        if p.is_file():
            if p.name in FORBIDDEN_FILES:
                hits.append(f"[结构] 文件不该存在: {rel}")
            if p.name.lower().endswith(FORBIDDEN_SUFFIXES):
                hits.append(f"[结构] 产物不该存在: {rel}")
    return hits


def check_tokens(box: Path, tokens: dict[str, str]) -> list[str]:
    hits = []
    for p in iter_text_files(box):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for tok, src in tokens.items():
            if tok and tok in text:
                hits.append(f"[答案指纹] {p.relative_to(box).as_posix()} 命中 {src}: {tok[:36]}…")
    return hits


def check_paths(box: Path, source: Path) -> list[str]:
    hits = []
    needles = {"沙箱根": str(ROOT), "源仓库": str(source)}
    for p in iter_text_files(box):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, needle in needles.items():
            if needle and needle in text:
                hits.append(f"[路径泄漏] {p.relative_to(box).as_posix()} 含{label}绝对路径")
        if "_answers" in text:
            hits.append(f"[路径泄漏] {p.relative_to(box).as_posix()} 提及 _answers")
    return hits


def check_cross_box(box: Path) -> list[str]:
    """箱内不得出现任何别的箱名（含自己的）—— 三箱互不可见。"""
    hits = []
    others = [b for b in BOXES if b != box.name]
    for p in iter_text_files(box):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name in others:
            # 用词边界避免 "sb12" 之类误报; 大小写不敏感
            if re.search(rf"(?<![A-Za-z0-9_]){name}(?![A-Za-z0-9_])", text, re.I):
                hits.append(f"[跨箱] {p.relative_to(box).as_posix()} 提及 {name}")
    return hits


def check_answers(box: Path, answers: Path) -> list[str]:
    hits = []
    if not answers.exists():
        return [f"[答案面] 缺答案目录: {answers}"]
    try:
        answers.relative_to(box)
        hits.append(f"[答案面] 答案目录在盒内: {answers}")
    except ValueError:
        pass
    # 构建态答案面必须**完全为空**。上一版写成"除 batch-manifest.json 外为空",
    # 等于给了自己一个豁免口: 那张卡带着源仓库绝对路径与题面来源分类躺了两轮。
    # 现在不放任何预置件 —— 批次卡在 _batch/, 溯源在 _index/。
    extra = [p.relative_to(answers).as_posix() for p in answers.rglob("*") if p.is_file()]
    if extra:
        hits.append(f"[答案面] 构建态应为空, 实有 {len(extra)} 个文件: {extra[:5]}")
    return hits


BATCH_FORBIDDEN = ("request_sources", "shared_request_families", "items_path")


def check_batch_meta() -> list[str]:
    """批次卡（`_batch/`）不得含溯源字段, 也不得写绝对路径, 题数须与题卷一致。

    为什么单独一层: 批次卡既不在箱内也不在答案面, 前面五层都扫不到它 ——
    而它恰好是"最容易被当成无害元数据"的那类文件(上一版就泄漏了源绝对路径)。
    """
    hits = []
    batch = ROOT / "_batch"
    if not batch.is_dir():
        return [f"[批次卡] 缺目录: {batch}"]
    for name in BOXES:
        f = batch / f"{name}.json"
        if not f.is_file():
            hits.append(f"[批次卡] 缺 {name}.json")
            continue
        raw = f.read_text(encoding="utf-8")
        for kw in BATCH_FORBIDDEN:
            if kw in raw:
                hits.append(f"[批次卡] {f.name} 含溯源字段「{kw}」")
        if re.search(r"[A-Za-z]:\\\\|\\\\Users\\\\", raw):
            hits.append(f"[批次卡] {f.name} 含盘符/用户绝对路径")
        doc = json.loads(raw)
        n_q = len(list((ROOT / name / "questions" / "per_item").glob("*.txt")))
        if doc.get("n_questions") != n_q:
            hits.append(f"[批次卡] {f.name} n_questions={doc.get('n_questions')} 与题卷 {n_q} 不一致")
        if doc.get("answers_dir") != f"_answers/{name}":
            hits.append(f"[批次卡] {f.name} answers_dir 不是相对 _answers/{name}")
    return hits


def history_tokens(source: Path) -> dict[str, str]:
    """历史跑批答卷的原文指纹 —— 用户明确要求"历史跑批答案也不许进箱"。

    取每份答卷 answer_text 的前 40 字与首句。40 字足够独特, 又不会因为通用词误报;
    取不到历史答案(没跑过)就返回空, 不算失败。
    """
    out: dict[str, str] = {}
    root = source / "temp" / "robustness" / "answers"
    if not root.is_dir():
        return out
    for f in root.rglob("*.json"):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        text = str(doc.get("answer_text") or "").strip()
        if len(text) >= 40:
            out[text[:40]] = f"{f.stem}.answer_text"
    return out


# 题面里绝对不该出现的"操作手册/标注"味道的短语。它们一旦出现在 questions/,
# 就说明有人把 TASKS.md 或标注原文拷了进来 —— 那是答案提示, 不是题面。
QUESTION_FORBIDDEN = (
    "故障由注入器", "注入剧本", "答案写到", "answer_box", "判分", "disposal",
    "名称解析失败", "哨兵", "传成整数", "锥内返回", "角分级精度", "标注原话",
)


def check_question_face(box: Path, source: Path) -> list[str]:
    """题面逐字校验：每个 per_item 文件必须**恰好等于**净化后的用户原话。

    这是最强的一条判据 —— 只要多出任何一句(标注括号 / 运行说明 / 层级标签),
    字符串就不相等。比"关键词黑名单"更难绕过。
    """
    import sys as _sys
    _sys.path.insert(0, str(HERE))
    from build_sandboxes import expected_questions   # 与构建器同源, 不另抄一份

    hits = []
    doc = yaml.safe_load((source / "evals" / "robustness" / "items.yaml").read_text(encoding="utf-8"))
    expect = expected_questions(doc["items"])

    qdir = box / "questions" / "per_item"
    files = {p.stem: p for p in qdir.glob("*.txt")} if qdir.is_dir() else {}
    missing = sorted(set(expect) - set(files))
    extra = sorted(set(files) - set(expect))
    if missing:
        hits.append(f"[题面] 缺 {len(missing)} 条: {missing[:6]}")
    if extra:
        hits.append(f"[题面] 多出 {len(extra)} 条: {extra[:6]}")
    for iid, p in files.items():
        got = p.read_text(encoding="utf-8").strip()
        want = expect.get(iid)
        if want is not None and got != want:
            hits.append(f"[题面] {iid} 与净化后原话不一致: 实有「{got[:40]}」应为「{want[:40]}」")
        for phrase in QUESTION_FORBIDDEN:
            if phrase in got:
                hits.append(f"[题面] {iid} 含操作手册/标注短语「{phrase}」")
    return hits


def audit(source: Path) -> dict:
    items_path = source / "evals" / "robustness" / "items.yaml"
    tokens, dropped = answer_tokens(items_path, public_corpus(source))
    hist = history_tokens(source)          # 历史跑批原文: 单独一类, 不参与"公共术语"过滤
    tokens.update(hist)
    report = {"at": datetime.now().isoformat(timespec="seconds"),
              "n_tokens": len(tokens), "n_history": len(hist), "excluded_public": dropped,
              "boxes": {}, "ok": True}
    for name in BOXES:
        box = ROOT / name
        answers = ROOT / "_answers" / name
        if not box.is_dir():
            report["boxes"][name] = {"hits": [f"[结构] 缺沙箱: {box}"], "ok": False}
            report["ok"] = False
            continue
        hits = (check_structure(box) + check_tokens(box, tokens)
                + check_paths(box, source) + check_cross_box(box)
                + check_answers(box, answers) + check_question_face(box, source))
        report["boxes"][name] = {"hits": hits, "ok": not hits,
                                 "n_files": sum(1 for _ in box.rglob("*") if _.is_file())}
        report["ok"] = report["ok"] and not hits
    # 批次卡是第七层: 它既不在箱内也不在答案面, 前面六层都扫不到
    bh = check_batch_meta()
    report["batch_meta"] = {"hits": bh, "ok": not bh}
    if bh:
        report["ok"] = False
    return report


def render(report: dict) -> str:
    lines = ["# E4 三箱泄漏审计报告", "",
             f"- 生成时间：{report['at']}",
             f"- 答案指纹数：{report['n_tokens']}（来自 items.yaml 的 suggest / report / options / correction.to / inject）",
             f"- 被排除的公共术语：{len(report.get('excluded_public', []))}（在被测对象公开面里也出现，不算泄漏）",
             f"- 历史跑批指纹：{report.get('n_history', 0)} 条（r1 答卷 answer_text 前 40 字）",
             f"- 总判定：**{'通过' if report['ok'] else '未通过'}**", "",
             "| 箱 | 文件数 | 结果 | 命中 |", "|---|---|---|---|"]
    for name, b in report["boxes"].items():
        lines.append(f"| {name} | {b.get('n_files', '-')} | {'✅' if b['ok'] else '❌'} | {len(b['hits'])} |")
    bm = report.get("batch_meta") or {"hits": [], "ok": True}
    lines.append(f"| `_batch/` 批次卡 | 3 | {'✅' if bm['ok'] else '❌'} | {len(bm['hits'])} |")
    for name, b in report["boxes"].items():
        if b["hits"]:
            lines.append(f"\n## {name} 命中明细\n")
            lines += [f"- {h}" for h in b["hits"]]
    if bm["hits"]:
        lines.append("\n## 批次卡命中明细\n")
        lines += [f"- {h}" for h in bm["hits"]]
    if report["ok"]:
        lines.append("\n> 七层全过：结构黑名单 / 答案指纹 / 路径泄漏 / 跨箱引用 / 答案面构建态为空 / "
                     "题面逐字校验 / 批次卡无溯源字段。")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="E4 三箱泄漏审计（只读）")
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args()

    rep = audit(args.source.resolve())
    print(json.dumps({k: v for k, v in rep.items() if k != "boxes"}, ensure_ascii=False))
    for name, b in rep["boxes"].items():
        print(f"  {name}: {'OK' if b['ok'] else 'FAIL'} ({len(b['hits'])} hits, {b.get('n_files')} files)")
        for h in b["hits"][:8]:
            print(f"    - {h}")
    bm = rep.get("batch_meta") or {"hits": [], "ok": True}
    print(f"  _batch/: {'OK' if bm['ok'] else 'FAIL'} ({len(bm['hits'])} hits)")
    for h in bm["hits"][:8]:
        print(f"    - {h}")
    if not args.no_report:
        out = ROOT / "_验收" / "泄漏审计报告.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(rep), encoding="utf-8", newline="\n")
        print(f"\n报告: {out}")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
