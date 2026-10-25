#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E4 答题沙箱构建器 v2 —— 一次搭出 sb1 / sb2 / sb3 三个互相隔离的答题箱。

v2 相对 v1 的关键修正（2026-10-21 下午，用户指出"箱里不该有答案"）:

    1. **不再把仓库的 TASKS.md 拷进箱**。那份是**操作手册**：写着"答案写到哪"
       "故障由注入器现场施加""注入剧本绝不写进题面" —— 模型读到就等于知道
       "本次会有故障注入"，而这正是 M5（失败包装）假绿的来源。v1 原样拷了它。
    2. **剥掉题面里的标注括号**。`RB-19` 原话是
       "查 ZZQXZ 这颗星的标准星记录 (名称解析失败, 回 ra=dec=-1000 哨兵)" ——
       括号里就是它该发现的东西。v1 把括号一起给了模型。
    3. **W 层 15 条不进模型题卷**。它们没有用户原话，题面只是一条固定查询，
       且带运行说明；给模型既答不了、又剧透"有故障在注入"。
       模型论文题 = P 35 + 复合 18 = **53 条**。
    4. 题目索引（原话 + 处置 + 净化后题面）落在**盒外** `_index/`，属操作者资产。

三条硬约束（不变）:
    * 物理不含答案: 标注/判分器/轨迹/历史跑批/注入剧本一律不拷，答案面在盒外且盒内不写路径;
    * 三箱逐字节一致: 同源、同序构建，构建后 sha256 清单必须相同;
    * 箱间互不影响: 每箱独立答案目录，盒内不得出现别的箱号或沙箱根路径。

能力边界（不吹）: ACL 只挡误改误删，**挡不住同用户下的故意读取**。
防偷看靠"物理上没有" + 盒内不写盒外路径 + 会话不告诉模型盒外路径。

用法:
    python _builder/build_sandboxes.py --dry-run
    python _builder/build_sandboxes.py --apply
    python _builder/build_sandboxes.py --apply --acl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_SOURCE = Path(r"<USER_HOME>\OneDrive\桌面\AI-archive-pre-sinking-snapshot-20261010\E4-work")
BOXES = ("sb1", "sb2", "sb3")

FORBIDDEN_NAMES = {
    "evals", "temp", "docs", "test", ".workbuddy", "runs", "answers", "_answers",
    "nl2tool-candidate-answers", "batch_input", "leak_probe", "broken", "fixtures",
    "items.yaml", "rubric.yaml", "graders.py", "runner.py", "judge_tier_p.py",
    "positive.py", "composite.py", "check_disposal_scope.py", "check_spec_reachability.py",
    "make_answer_box.py", "make_batch_input.py", "check_leakage.py",
    "REPORT.md", "REPORT-r1.md", "RUN-CARD.md", "DELTA.md", "PATCH.diff",
    "report-r1.json", "report-all.json", "TASKS.md",
}

CASE_ID_RE = re.compile(r"(E4\s+)?RB-[A-Z]?\d{2}")
PLACEHOLDER = "该场景"

# 题面里的"(…)"是标注者的场景说明，不是用户会说的话。只剥带"标注味"的括号；
# 用户本来的口语不动。每次剥都记账，供人工复核。
# 注意句末标点在括号**之后**：原文是 "…(名称解析失败, 回 -1000 哨兵)。"
# 第一版把 $ 钉在括号后，导致 5 处一处也没剥到（构建日志里"剥标注 0 处"就是这个 bug）。
ANNOTATION_PAREN = re.compile(r"\s*[（(]([^）)]*)[）)]\s*([。.!！?？]?)\s*$")
ANNOTATION_HINTS = ("名称解析", "哨兵", "候选", "锥内", "角分级", "传成整数", "返回多个")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_manifest(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha256(p)
            for p in sorted(root.rglob("*")) if p.is_file()}


def clean_utterance(text: str) -> tuple[str, str | None]:
    """返回 (给模型看的题面, 被剥掉的说明或 None)。"""
    m = ANNOTATION_PAREN.search(text or "")
    if m and any(h in m.group(1) for h in ANNOTATION_HINTS):
        tail = m.group(2) or ""          # 句末标点要还回去: "…记录。" 而不是 "…记录"
        return text[:m.start()].rstrip() + tail, m.group(0).strip()
    return (text or ""), None


FIXED_QUERY = "查 RA=180.0, Dec=30.0 附近 60.0 角秒内的 ps1 源。"


FIXED_QUERY = "查 RA=180.0, Dec=30.0 附近 60.0 角秒内的 ps1 源。"


def model_items(items: list[dict]) -> list[dict]:
    """需要模型会话的用例：Tier P(35) + 复合 18 条。Tier W 15 条不进模型题卷。"""
    return [it for it in items if it.get("tier") == "P" or it.get("second_round")]


def expected_questions(items: list[dict]) -> dict[str, str]:
    """题号 → 给模型看的题面（已净化）。

    复合 18 条**自己没写 utterance**，只写了 base_case（RB-45/46/47/48/49/50）。
    第一版只读 `utterance`，于是 18 条全写成了空文件 —— 空题比错题更危险，
    因为跑批时"没有题可答"会被误读成模型拒答。这里回溯到基础题原话；
    基础题本身也没有原话（RB-47 是线路层）时，用固定查询面。
    """
    by_id = {it["id"]: it for it in items}
    out = {}
    for it in model_items(items):
        raw = it.get("utterance")
        if not raw and it.get("base_case"):
            raw = (by_id.get(it["base_case"]) or {}).get("utterance")
        if not raw:
            raw = FIXED_QUERY
        out[it["id"]] = clean_utterance(raw)[0].strip()
    return out


def scrub_case_ids(box: Path) -> list[str]:
    """盒内 src/ 的用例号去标识：只改注释/文档串，不动代码逻辑。"""
    touched = []
    for p in sorted(box.rglob("*.py")):
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if not CASE_ID_RE.search(text):
            continue
        new_lines, hit = [], []
        for i, line in enumerate(text.splitlines(keepends=True), 1):
            if CASE_ID_RE.search(line):
                hit.append(i)
                line = CASE_ID_RE.sub(PLACEHOLDER, line)
            new_lines.append(line)
        if hit:
            p.write_text("".join(new_lines), encoding="utf-8", newline="\n")
            touched.append(f"{p.relative_to(box).as_posix()}:{','.join(map(str, hit))}")
    return touched


def write_entry_docs(box: Path, n_questions: int) -> None:
    """盒内说明件：只写规则，**不写任何盒外路径、不写箱号**。"""
    (box / "ISOLATION.md").unlink(missing_ok=True)
    (box / "SANDBOX-RULES.md").write_text(
        f"""# 答题规则

> 生成件，勿手改 —— 由 `_builder/build_sandboxes.py` 写入。
> 本件三个沙箱逐字节相同；箱号只记在盒外的 `SANDBOX-MANIFEST.json`。

## 你的世界就是这个目录

工作目录直接指向本层（不要再多给一层）。本目录之外的东西**不属于本次实验**：
不要访问、列目录、检索或推测任何盒外路径。

## 里面有什么

- 被测对象本体：`SKILL.md`、`README.md`、`manifest.yaml`、`architecture.md`、
  `contracts/`、`static/`、`references/`、`src/`、`agents/`、`templates/`、`rag/`
- 题卷：`questions/per_item/<题号>.txt`（一次只取一个文件，共 {n_questions} 个）

## 怎么答

1. **一次只答一题，一题一个会话**。整卷粘进同一会话会串题。
2. 题面**照抄**，不要自己加提示（“这题该拒”“别用某个工具”本身就是答案）。
3. 题面里没有的东西就是没有：不要编造工具、参数、站点行为或数据。
4. 有疑问就按题面说的做（问人 / 拒绝 / 报告事实），不要替用户假设。

## 不许做的事

- 不往本目录拷任何历史产物、别家答卷、判分结果；
- 不读取本目录之外的任何文件；
- 不修改 `src/`、`SKILL.md`、`references/` 等被测对象本体。
""",
        encoding="utf-8",
    )
    (box / "ALLOWED-FILES.md").write_text(
        "# 本箱允许存在的文件（白名单）\n\n"
        "顶层文件：SKILL.md、README.md、manifest.yaml、architecture.md、"
        "SANDBOX-RULES.md、ALLOWED-FILES.md\n\n"
        "目录：contracts/、static/、references/、src/、agents/、templates/、rag/、"
        "questions/per_item/\n\n"
        "除此之外的一切（评测标注、判分器、轨迹、历史跑批、答案、注入剧本、"
        "操作手册）都不应出现；出现即为构建事故，由 `_builder/audit_leak.py` 判红。\n",
        encoding="utf-8",
    )


def build_one(source: Path, box: Path, answers: Path, items_path: Path) -> dict:
    """搭一个箱：白名单拷贝 → 自建干净题卷 → 去标识 → 去路径。"""
    sys.path.insert(0, str(source))
    from evals.robustness import make_answer_box as mab   # 复用白名单与拷贝逻辑

    if box.exists():
        if box.parent != ROOT or box.name not in BOXES:
            raise SystemExit(f"拒绝清理: {box} 不在 {ROOT}/{{{','.join(BOXES)}}} 之内")
        shutil.rmtree(box)

    # 答案面在**构建态必须为空**：这里只放本次 run 的答卷，不放任何预置件。
    # 上一版把批次卡写进 _answers/<box>/batch-manifest.json，重建时又不清理，
    # 于是旧卡一直留着（还带着源仓库绝对路径与题面来源分类）。清干净。
    if answers.exists():
        if answers.parent != ROOT / "_answers":
            raise SystemExit(f"拒绝清理答案面: {answers} 不在 {ROOT}/_answers 之内")
        shutil.rmtree(answers)
    answers.mkdir(parents=True)

    info = mab.build(box=box, answers_root=answers, items_path=items_path)

    # 仓库自带 build() 会写 TASKS.md 与 questions/ —— 那两份是**操作手册**，
    # 含"答案写到哪""故障由注入器现场施加"等运行说明，不能进模型可见面。
    doc = yaml.safe_load(items_path.read_text(encoding="utf-8"))
    bundle = model_items(doc["items"])
    qdir = box / "questions"
    if qdir.exists():
        shutil.rmtree(qdir)
    (qdir / "per_item").mkdir(parents=True)
    (box / "TASKS.md").unlink(missing_ok=True)

    expected = expected_questions(doc["items"])
    by_id = {it["id"]: it for it in doc["items"]}
    rows, strips = [], []
    for it in bundle:
        iid = it["id"]
        raw = it.get("utterance") or (by_id.get(it.get("base_case")) or {}).get("utterance") or FIXED_QUERY
        _, removed = clean_utterance(raw)
        if removed:
            strips.append(f"{iid}: 剥掉 {removed}")
        (qdir / "per_item" / f"{iid}.txt").write_text(expected[iid] + "\n", encoding="utf-8")
        rows.append([iid, it.get("tier"), str(it.get("disposal")), raw, expected[iid]])

    touched = scrub_case_ids(box)
    write_entry_docs(box, len(bundle))

    leaks = []
    for p in box.rglob("*"):
        if not p.is_file() or p.suffix not in {".md", ".py", ".yaml", ".yml", ".json"}:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if str(ROOT) in text or str(answers) in text or "_answers" in text:
            leaks.append(p.relative_to(box).as_posix())

    return {"n_files": info["n_files"], "n_items": info["n_items"],
            "n_questions": len(bundle), "stripped_annotations": strips,
            "question_index": rows, "scrubbed": touched, "abs_path_leaks": leaks,
            "n_answers_files": sum(1 for p in answers.rglob("*") if p.is_file())}


def batch_card(source: Path, name: str, info: dict) -> dict:
    """批次卡（写在沙箱根的 `_batch/`，**不在答案面也不在盒内**）。

    为什么不再放 `_answers/<box>/`：那是答案面，语义上只该有"模型答出来的东西"。
    放一张预置卡进去，一是让"答案面是否干净"无法用简单判据检查（必须记白名单），
    二是它确实带了不该外露的字段（源仓库绝对路径、题面来源分类、同族映射）。
    这里只留跑批对账需要的项；溯源信息单独进 `_index/`。
    """
    qdir = ROOT / name / "questions" / "per_item"
    qsha = hashlib.sha256(
        json.dumps({p.stem: sha256(p) for p in sorted(qdir.glob("*.txt"))},
                   sort_keys=True).encode()).hexdigest()[:16]
    rubric = source / "evals" / "robustness" / "rubric.yaml"
    schema = source / "references" / "tools.schema.json"
    return {
        "box": name,
        "answers_dir": f"_answers/{name}",          # 相对路径: 不写沙箱根的绝对位置
        "n_questions": info["n_questions"],
        "question_set_sha": qsha,                   # 53 条题面的整体指纹: 改一个字就变
        "rubric_hash": sha256(rubric) if rubric.is_file() else "MISSING",
        "tools_schema_hash": sha256(schema) if schema.is_file() else "MISSING",
        "model_id": "FILL-ME",                      # 由人填: 本件不知道跑的是哪个模型
        "system_prompt_version": "FILL-ME",
        "network": "FILL-ME",
        "note": "本卡只含批次对账信息。题面来源分类与同族映射见 _index/批次溯源.md。",
    }


def apply_acl(box: Path) -> str:
    import getpass
    try:
        r = subprocess.run(["icacls", str(box), "/deny", f"{getpass.getuser()}:(W,D)"],
                           capture_output=True, text=True, timeout=60)
        return "ok" if r.returncode == 0 else f"failed: {r.stderr.strip()[:120]}"
    except Exception as exc:                      # noqa: BLE001
        return f"failed: {type(exc).__name__}: {exc}"


def main() -> int:
    ap = argparse.ArgumentParser(description="E4 三箱答题沙箱构建器")
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--apply", action="store_true", help="真构建（缺省 dry-run）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--acl", action="store_true", help="额外给模型面加只读 ACL")
    args = ap.parse_args()

    source = args.source.resolve()
    items_path = source / "evals" / "robustness" / "items.yaml"
    if not items_path.is_file():
        print(f"[FAIL] 源缺 items.yaml: {items_path}")
        return 1

    print(f"源     : {source}")
    print(f"沙箱根 : {ROOT}")
    for name in BOXES:
        print(f"  {name}: 模型面 {ROOT / name} | 答案面 {ROOT / '_answers' / name}（答案面，在 sbN 之外）")
    if not args.apply:
        print("\n[dry-run] 未落盘。加 --apply 执行。")
        return 0

    meta = {"built_at": datetime.now().isoformat(timespec="seconds"),
            "source": str(source), "boxes": {}}
    for name in BOXES:
        print(f"\n=== 构建 {name} ===")
        info = build_one(source, ROOT / name, ROOT / "_answers" / name, items_path)
        info["acl"] = apply_acl(ROOT / name) if args.acl else "skipped"
        info["n_files_total"] = sum(1 for p in (ROOT / name).rglob("*") if p.is_file())
        info["manifest_sha"] = hashlib.sha256(
            json.dumps(tree_manifest(ROOT / name), sort_keys=True).encode()).hexdigest()[:16]
        meta["boxes"][name] = info
        print(f"  文件 {info['n_files_total']} | 题卷 {info['n_questions']} 条 | 清单 {info['manifest_sha']}")
        print(f"  剥标注 {len(info['stripped_annotations'])} 处: {info['stripped_annotations']}")
        print(f"  去用例号 {len(info['scrubbed'])} 个文件 | 路径泄漏 {info['abs_path_leaks'] or '无'} | ACL {info['acl']}")
        print(f"  答案面构建态文件数: {info['n_answers_files']}（必须 0）")

    idx = ROOT / "_index"
    idx.mkdir(exist_ok=True)
    rows = meta["boxes"]["sb1"]["question_index"]
    table = "\n".join(f"| {i} | {t} | {d} | {u} | {c} |" for i, t, d, u, c in rows)
    (idx / "题目索引.md").write_text(
        "# 题目索引（操作者资产，勿拷进 sbN）\n\n"
        "| 题号 | 层 | 处置 | 原话（含标注） | 给模型的题面 |\n|---|---|---|---|---|\n"
        + table
        + "\n\n> 后两列不同的行 = 该题面剥掉了标注括号。\n",
        encoding="utf-8", newline="\n")

    # 批次卡与溯源分离落盘（都不进箱、不进答案面）
    batch = ROOT / "_batch"
    batch.mkdir(exist_ok=True)
    for name in BOXES:
        (batch / f"{name}.json").write_text(
            json.dumps(batch_card(source, name, meta["boxes"][name]),
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")

    doc = yaml.safe_load(items_path.read_text(encoding="utf-8"))
    by_id = {it["id"]: it for it in doc["items"]}
    expect = expected_questions(doc["items"])
    src_kind = {}
    for iid in expect:
        it = by_id[iid]
        src_kind[iid] = ("utterance" if it.get("utterance")
                         else f"base_case:{it.get('base_case')}" if it.get("base_case")
                         else "fixed_default_face")
    fam = {}
    for iid, q in expect.items():
        fam.setdefault(q, []).append(iid)
    fam = {q: sorted(v) for q, v in fam.items() if len(v) > 1}
    src_kind = dict(sorted(src_kind.items()))
    (idx / "批次溯源.md").write_text(
        "# 批次溯源（操作者资产，勿拷进 sbN）\n\n"
        f"- 源标注：`{items_path}`\n- 源仓库：`{source}`\n\n"
        "## 题面来源分类\n\n"
        "| 题号 | 来源 |\n|---|---|\n"
        + "\n".join(f"| {k} | {v} |" for k, v in src_kind.items())
        + "\n\n## 同题面族（合法共用，判分时不算串题）\n\n"
        + ("\n".join(f"- `{q}`：{', '.join(v)}" for q, v in fam.items()) or "（无）")
        + "\n", encoding="utf-8", newline="\n")

    shas = {n: meta["boxes"][n]["manifest_sha"] for n in BOXES}
    same = len(set(shas.values())) == 1

    # 写进沙箱根的清单必须**脱敏**：原版直接 dump meta，里面带着
    #   · question_index 的第三列 = 逐题处置标注（A/B/C/D）
    #   · stripped_annotations = 5 条被剥掉的答案括号原文
    #   · source = 源仓库绝对路径（等于告诉人去哪儿拿 items.yaml）
    # 而这份清单与 sbN 同级，是模型 cwd 的上一级。三样全移进 _index/。
    ALLOWED = ("n_files", "n_items", "n_questions", "n_files_total",
               "manifest_sha", "acl", "abs_path_leaks", "n_answers_files")
    public = {
        "built_at": meta["built_at"],
        "three_way_identical": same,
        "boxes": {
            n: {**{k: v for k, v in meta["boxes"][n].items() if k in ALLOWED},
                "question_face": {iid: face for iid, _t, face in
                                  [(r[0], r[1], r[4]) for r in meta["boxes"][n]["question_index"]]}}
            for n in BOXES
        },
    }
    (ROOT / "SANDBOX-MANIFEST.json").write_text(
        json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    # 剥标注记录含答案括号原文 → 也只进 _index/，不进根清单
    strip_lines = ["# 题面剥离记录（操作者资产，勿拷进 sbN）", "",
                   "下面每行是「把标注括号从用户原话里剥掉」的逐条凭证。",
                   "括号里的内容是标注者的场景说明（等于答案提示），不能给模型看。", ""]
    for name in BOXES:
        for s in meta["boxes"][name]["stripped_annotations"]:
            strip_lines.append(f"- {name} · {s}")
    (idx / "剥离记录.md").write_text("\n".join(strip_lines) + "\n",
                                     encoding="utf-8", newline="\n")

    print(f"\n三箱一致: {'是' if same else '否 ⚠️'}")
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main())
