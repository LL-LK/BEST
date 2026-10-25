#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E1 三沙箱 · 隔离与一致性验收（一次性跑完全部检查，产出验收报告）

用法:
    python _builder/verify_all.py                  # 验收 + 落报告到 _验收/验收报告.md
    python _builder/verify_all.py --no-negtest     # 跳过负向测试（快）

验收分四部分:
    A. 一致性 —— 三箱的 skill/ 与 题卷/ 逐字节一致（同一次构建的三次重复）
    B. 静态隔离 —— 全箱扫描: 不含答案类文件、不含标注指纹、不含历史跑批
    C. 负向测试 —— 在**临时副本**上做篡改, verify 必须判 FAIL（闸要真的会响）
    D. 命令自检 —— 三箱的 verify / preflight / progress 都能跑通

为什么 C 必须做: 一道闸从来没响过, 和它根本不存在是一回事。上一版沙箱
从没验证过"改了题面会不会被发现", 于是"题卷未被篡改"这件事当时是没有证据的。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BOXES = ("sb1", "sb2", "sb3")
N_TASKS = 28
PY = sys.executable

# 答案 / 历史跑批 / 判分侧的文件名特征（出现在沙箱内即判红）
FORBIDDEN_NAME_TOKENS = (
    "tasks.yaml", "items.yaml", "rubric.yaml",
    "graders.py", "runner.py", "gen_golden.py", "normalizers.py",
    "candidate-answers", "snapshots", "report.json", "live-2026-",
    "traces", "broken", "golden",
)
# 内容指纹（严格区 = skill/ + 规则件）
STRICT_PATTERNS = [
    (r"NL2T-\d", "题号（答案定位器）"),
    (r"evals/", "评测目录指针"),
    (r"\bnl2tool\b", "评测模块名"),
    (r"expect_tools_after_clarify|expect_tools", "期望工具序列"),
    (r"anti_patterns", "错法清单"),
    (r"reason_aliases|reason_code|must_not_call", "拒绝理由码/禁调清单"),
    (r"should_call_best", "是否允许真实请求标记"),
    (r"key_fields", "期望返回字段"),
    (r"clarify\.probes|\bprobes:", "澄清探测词表"),
    (r"golden-from-annotation|live-run|source=live", "轨迹来源标记"),
]
PAPER_PATTERNS = [
    (r"expect_tools|anti_patterns|reason_code|must_not_call|should_call_best|key_fields",
     "答案字段泄漏进题卷"),
    (r"evals/|nl2tool|golden|live-run|traces", "评测目录指针"),
]
PLACEHOLDER_TASK_ID = re.compile(r"NL2T-<[^>\n]*>")
SCAN_SUFFIX = {".md", ".txt", ".py", ".yaml", ".yml", ".json", ".cfg", ".toml", ".ini"}
MODEL_VISIBLE_TOP = ("skill", "题卷", "answers")
MODEL_VISIBLE_ROOT_FILES = ("SANDBOX-RULES.md", "ALLOWED-FILES.md")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(p: Path, root: Path) -> str:
    return str(p.relative_to(root)).replace("\\", "/")


def walk(root: Path):
    for dp, dns, fns in __import__("os").walk(root):
        dns[:] = [d for d in dns if d not in {".git", "__pycache__", ".ipynb_checkpoints"}]
        for fn in fns:
            yield Path(dp) / fn


def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                       capture_output=True)
    out = (r.stdout + r.stderr).decode("utf-8", "replace")
    return r.returncode, out


# ══════════════════════════════════════════════════════════════════════════════
# A. 一致性
# ══════════════════════════════════════════════════════════════════════════════

def check_consistency() -> list[dict]:
    rows = []
    for scope in ("skill", "题卷"):
        per_box: dict[str, dict[str, str]] = {}
        for b in BOXES:
            base = ROOT / b / scope
            per_box[b] = {rel(p, base): sha256_file(p) for p in walk(base)}
        keys = set().union(*per_box.values())
        for k in sorted(keys):
            digs = {b: per_box[b].get(k) for b in BOXES}
            rows.append({
                "scope": scope, "path": k, "hash": (digs[BOXES[0]] or "")[:12],
                "consistent": len(set(digs.values())) == 1 and None not in digs.values(),
            })
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# B. 静态隔离
# ══════════════════════════════════════════════════════════════════════════════

def check_static() -> list[dict]:
    rows = []
    for b in BOXES:
        root = ROOT / b
        bad_names, bad_content, n_files = [], [], 0
        for p in walk(root):
            n_files += 1
            r = rel(p, root)
            low = p.name.lower()
            for tok in FORBIDDEN_NAME_TOKENS:
                if tok in low:
                    bad_names.append(f"{r} ← {tok}")
                    break
            if p.suffix.lower() not in SCAN_SUFFIX:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if r.startswith("skill/") or r in MODEL_VISIBLE_ROOT_FILES:
                pats = STRICT_PATTERNS
                probe = PLACEHOLDER_TASK_ID.sub("NL2T-<?>", text)
            elif r.startswith("题卷/"):
                pats = PAPER_PATTERNS
                probe = text
            else:
                continue
            for pat, why in pats:
                m = re.search(pat, probe)
                if m:
                    ln = probe.count("\n", 0, m.start()) + 1
                    bad_content.append(f"{r}:{ln} /{pat}/ {why}")
        rows.append({"box": b, "files": n_files,
                     "bad_names": bad_names, "bad_content": bad_content,
                     "clean": not bad_names and not bad_content})
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# C. 负向测试（在临时副本上做篡改，verify 必须 FAIL）
# ══════════════════════════════════════════════════════════════════════════════

def negative_tests() -> list[dict]:
    """在 `_验收/_tmp` 临时副本上做篡改，确认每道闸真的会响。"""
    tmp = ROOT / "_验收" / "_tmp"
    if tmp.exists():
        run([PY, str(tmp / "sb1" / "_lock" / "sandbox_lock.py"), "unseal",
             "--root", str(tmp / "sb1")])
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []

    def scenario(name: str, mutate, expect_keyword: str) -> None:
        box = tmp / "sb1"
        if box.exists():
            run([PY, str(box / "_lock" / "sandbox_lock.py"), "unseal",
                 "--root", str(box)])
            shutil.rmtree(box, ignore_errors=True)
        shutil.copytree(ROOT / "sb1", box)
        # 副本默认不带 ACL 硬锁（copytree 不保留 ACE），解封后即可篡改
        run([PY, str(box / "_lock" / "sandbox_lock.py"), "unseal",
             "--root", str(box)])
        mutate(box)
        rc, out = run([PY, str(box / "_lock" / "sandbox_lock.py"), "verify",
                       "--root", str(box)])
        failed = rc != 0
        # 判据必须读**报告全文**，不能读 stdout: verify 的 stdout 只打印前 20 条命中,
        # 而副本刚被 unseal 过, 前 20 条会被"[只读] ... 已解除"占满, 真正的命中被挤掉。
        rep = box / "_lock" / "verify_report.md"
        rep_text = rep.read_text(encoding="utf-8") if rep.exists() else ""
        hit = expect_keyword in rep_text
        detail = next((l.strip() for l in rep_text.splitlines()
                       if expect_keyword in l), "")
        results.append({
            "name": name, "verify_failed": failed, "keyword_hit": hit,
            "ok": failed and hit,
            "detail": detail or (out.splitlines()[0] if out else ""),
        })

    # ① 篡改题面 → 题卷指纹闸 + 完整性闸
    def m_paper(box: Path) -> None:
        p = box / "题卷" / "per_task" / "NL2T-13.txt"
        p.write_text(p.read_text(encoding="utf-8") + "（多加一句）", encoding="utf-8")

    # ② skill/ 内新增文件 → 完整性闸
    def m_newfile(box: Path) -> None:
        (box / "skill" / "LEAK-TEST.md").write_text("x", encoding="utf-8")

    # ③ 删除已登记文件 → 完整性闸
    def m_delete(box: Path) -> None:
        (box / "skill" / "SKILL.md").unlink()

    # ④ 塞入标注文件（答案键）→ 文件名黑名单 + 内容指纹
    def m_key(box: Path) -> None:
        (box / "answers" / "tasks.yaml").write_text(
            "expect_tools: [cone_search]\nanti_patterns: [...]\n", encoding="utf-8")

    # ⑤ 逃逸链接 → 逃逸闸
    def m_link(box: Path) -> None:
        # 先试 symlink（需管理员），失败则退回 junction（mklink /J，普通用户即可）。
        # 用相对路径 + cwd，避免中文路径经 cmd 传参被控制台代码页搅乱。
        target = box / "answers" / "link"
        try:
            target.symlink_to(ROOT / "sb2", target_is_directory=True)
            return
        except (OSError, NotImplementedError):
            pass
        subprocess.run(["cmd", "/c", "mklink", "/J", "link", r"..\..\..\sb2"],
                       cwd=str(box / "answers"), capture_output=True)

    # ⑥ 提到兄弟沙箱名 → 越界闸
    def m_sibling(box: Path) -> None:
        p = box / "SANDBOX-RULES.md"
        p.write_text(p.read_text(encoding="utf-8") + "\nsb2\n", encoding="utf-8")

    # ⑦ 解除只读 → 只读闸
    def m_unlock(box: Path) -> None:
        os.chmod(box / "skill" / "SKILL.md", 0o644)

    # ⑧ 往题卷里加答案字段 → 题卷内容闸
    def m_paper_key(box: Path) -> None:
        p = box / "题卷" / "per_task" / "NL2T-21.txt"
        p.write_text(p.read_text(encoding="utf-8") + "\nexpect_tools: [cone_search]",
                     encoding="utf-8")

    # 需要一个 sb2 兄弟目录，越界闸才会把 sb2 判为"其他沙箱"
    (tmp / "sb2").mkdir(exist_ok=True)

    scenario("① 篡改题面 → 题卷指纹闸", m_paper, "[题卷] 题面被改动")
    scenario("② skill/ 内新增文件 → 完整性闸", m_newfile, "[完整性] 新增未登记文件")
    scenario("③ 删除已登记文件 → 完整性闸", m_delete, "[完整性] 登记文件缺失")
    scenario("④ 塞入标注文件 → 文件名+内容闸", m_key, "[文件名]")
    scenario("⑤ 建逃逸符号链接 → 逃逸闸", m_link, "[逃逸]")
    scenario("⑥ 提到兄弟沙箱名 → 越界闸", m_sibling, "[越界]")
    scenario("⑦ 解除只读 → 只读闸", m_unlock, "[只读]")
    scenario("⑧ 题卷加答案字段 → 题卷内容闸", m_paper_key, "[内容]")

    shutil.rmtree(tmp, ignore_errors=True)
    return results


# ══════════════════════════════════════════════════════════════════════════════
# D. 命令自检
# ══════════════════════════════════════════════════════════════════════════════

def check_commands() -> list[dict]:
    rows = []
    for b in BOXES:
        box = ROOT / b
        lock = box / "_lock" / "sandbox_lock.py"
        rc1, o1 = run([PY, str(lock), "verify", "--root", str(box),
                       "--repo-hint", "AI-archive-pre-sinking-snapshot"])
        rc2, o2 = run([PY, str(lock), "preflight", "--root", str(box),
                       "--repo-hint", "AI-archive-pre-sinking-snapshot"])
        rc3, o3 = run([PY, str(lock), "progress", "--root", str(box)])
        m1 = re.search(r"已作答: (\d+)/(\d+)", o2)
        m2 = re.search(r"\[progress\] (\d+)/(\d+)", o3)
        rows.append({
            "box": b,
            "verify": o1.splitlines()[0] if o1 else "",
            "preflight": o2.splitlines()[-1] if rc2 == 0 else (o2.splitlines()[1] if len(o2.splitlines()) > 1 else ""),
            "progress": o3.splitlines()[0] if o3 else "",
            "ans_preflight": m1.group(0) if m1 else "",
            "ans_progress": m2.group(0) if m2 else "",
            "ok": rc1 == 0 and rc2 == 0 and rc3 == 0,
        })
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# 报告
# ══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(description="E1 三沙箱隔离与一致性验收")
    ap.add_argument("--no-negtest", action="store_true", help="跳过负向测试")
    ns = ap.parse_args()

    print(f"[验收] 沙箱根: {ROOT}")
    print()

    # A
    print("── A. 三箱一致性 ──")
    cons = check_consistency()
    n_bad = [r for r in cons if not r["consistent"]]
    print(f"   比对文件条目: {len(cons)} （skill/ + 题卷/）")
    print(f"   不一致: {len(n_bad)}")
    for r in n_bad[:10]:
        print(f"     ✗ {r['scope']}/{r['path']}")
    print()

    # B
    print("── B. 静态隔离扫描 ──")
    stat = check_static()
    for r in stat:
        flag = "干净" if r["clean"] else "命中"
        print(f"   {r['box']}: 扫描 {r['files']} 文件 · {flag}")
        for x in (r["bad_names"] + r["bad_content"])[:6]:
            print(f"       ✗ {x}")
    print()

    # C
    neg = []
    if not ns.no_negtest:
        print("── C. 负向测试（临时副本; verify 必须判红）──")
        neg = negative_tests()
        for r in neg:
            mark = "PASS" if r["ok"] else "FAIL"
            print(f"   [{mark}] {r['name']}"
                  + ("" if r["ok"] else f"  ← verify 竟然通过了！"))
            if r["detail"]:
                print(f"          {r['detail']}")
        print()

    # D
    print("── D. 命令自检 ──")
    cmds = check_commands()
    for r in cmds:
        print(f"   {r['box']}: {'OK' if r['ok'] else 'FAIL'}")
        print(f"       verify    : {r['verify']}")
        print(f"       preflight : {r['preflight']}")
        print(f"       progress  : {r['progress']}")
    print()

    # 汇总
    a_ok = not n_bad
    b_ok = all(r["clean"] for r in stat)
    c_ok = all(r["ok"] for r in neg) if neg else True
    d_ok = all(r["ok"] for r in cmds)
    all_ok = a_ok and b_ok and c_ok and d_ok

    print("════════════════════════════════════════")
    print(f"   一致性 A : {'PASS' if a_ok else 'FAIL'}")
    print(f"   静态隔离 B: {'PASS' if b_ok else 'FAIL'}")
    print(f"   负向测试 C: {'PASS' if c_ok else 'FAIL'}"
          + ("（已跳过）" if ns.no_negtest else ""))
    print(f"   命令自检 D: {'PASS' if d_ok else 'FAIL'}")
    print(f"   ── 总判定 : {'PASS' if all_ok else 'FAIL'}")
    print("════════════════════════════════════════")

    # 报告
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    L = [
        "# 三沙箱隔离与一致性 · 验收报告",
        "",
        f"- 生成时间: {stamp}",
        f"- 沙箱根: `{ROOT}`",
        f"- 构建器: `_builder/build_sandboxes.py`",
        f"- **总判定: {'PASS' if all_ok else 'FAIL'}**",
        "",
        "## A. 三箱一致性",
        "",
        f"- 比对条目: {len(cons)}（两棵内容树 skill/ 与 题卷/）",
        f"- 不一致: {len(n_bad)}",
        "",
    ]
    if n_bad:
        L += ["| 区域 | 文件 | 首箱哈希 |", "|------|------|---------|"]
        L += [f"| {r['scope']} | {r['path']} | {r['hash']} |" for r in n_bad]
        L.append("")
    else:
        L += ["三箱的 `skill/` 与 `题卷/` 逐字节一致 —— 同一次构建的三次重复。", ""]

    L += ["## B. 静态隔离扫描", "", "| 沙箱 | 扫描文件 | 判定 |", "|------|------|------|"]
    L += [f"| {r['box']} | {r['files']} | {'干净' if r['clean'] else '命中'} |" for r in stat]
    L.append("")
    for r in stat:
        if not r["clean"]:
            L += [f"### {r['box']} 命中明细", ""] + [f"- {x}" for x in (r["bad_names"] + r["bad_content"])] + [""]

    L += ["## C. 负向测试", ""]
    if neg:
        L += ["| 场景 | verify 判红 | 判定 |", "|------|------|------|"]
        L += [f"| {r['name']} | {'是' if r['verify_failed'] else '否'} | "
              f"{'PASS' if r['ok'] else 'FAIL'} |" for r in neg]
        L += ["", "> 全部在 `_验收/_tmp` 临时副本上完成，跑完即删；真实沙箱不受影响。", ""]
    else:
        L += ["（本次跳过）", ""]

    L += ["## D. 命令自检", ""]
    for r in cmds:
        L += [f"### {r['box']}", "",
              f"- verify: `{r['verify']}`",
              f"- preflight: `{r['preflight']}`",
              f"- progress: `{r['progress']}`", ""]

    L += [
        "## 隔离的能力边界（如实写明）",
        "",
        "| 防线 | 挡得住 | 挡不住 |",
        "|------|--------|--------|",
        "| 物理不含答案 | 任何偷看（沙箱里根本没有） | — |",
        "| 只读属性 + ACL | 误改内容、误删文件 | 同用户下的**故意**读取（模型与执行会话通常同一 Windows 用户） |",
        "| 软锁十道闸 | 事后发现篡改/越界并判红 | 实时阻止写入 |",
        "",
        "> 所以：**别把 ACL 当防泄题手段**。防泄题靠第一行的“物理不含”，",
        "> 以及“被测模型侧不挂载仓库文件读取 / grep / 检索能力”这条纪律。",
        "",
    ]

    out = ROOT / "_验收" / "验收报告.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8", newline="\n")
    print(f"\n[验收] 报告: {out}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
