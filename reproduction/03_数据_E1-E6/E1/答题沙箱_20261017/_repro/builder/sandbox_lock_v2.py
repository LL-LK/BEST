#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E1 答题沙箱 · 目录锁 v2 (只读标准库, 任何 python 3.x 可跑)

五个命令:
    python _lock/sandbox_lock.py seal       封闭: 上只读属性 (+可选 ACL 硬锁) + 生成 MANIFEST
    python _lock/sandbox_lock.py verify     体检: 十道闸; 命中任一条 exit 1
    python _lock/sandbox_lock.py progress   进度: 已答 n/28, 并刷新答案基线
    python _lock/sandbox_lock.py preflight  开跑前自检: 把"能不能开始"变成机器判定
    python _lock/sandbox_lock.py unseal     解封: 解除 ACL 与只读 (重建沙箱时用)

────────────────────────────────────────────────────────────────────────────────
v2 相对 v1 (2026-10-15) 的修改 —— 每一条都对应一个实测踩过的坑
────────────────────────────────────────────────────────────────────────────────
[修 1] **preflight 计数把台账当答案** —— v1 的 `progress` 排除了 RUN-INFO.md，
       `preflight` 却没排除，于是长期报 29/28 / 清空后报 1/28。
       v2 把过滤逻辑收敛成一个函数 `iter_answer_files()`，两处共用。
[修 2] **台账"未填"守卫能被绕过** —— v1 守卫只认 `（填`，占位符写成 `（待填…`
       就能静默通过（实测出现过，提醒数为 0）。
       v2 改用显式哨兵 `<!-- UNSET -->`，且要求**哨兵消失且值非空且非占位**才算已填。
[修 3] **兄弟沙箱名判定过宽** —— v1 把父目录下所有目录都当"其他沙箱"，
       连 `_builder`/`_验收` 都算，容易误报。v2 精确匹配 `^sb\d+$` 且排除自身。
[修 4] **MANIFEST 漏掉 `_lock/`** —— v1 的 `iter_files` 直接跳过 `_lock` 目录，
       于是锁脚本自己被改、净化日志被删，verify 都发现不了。
       v2 把 `_lock/` 里的资产件纳入 MANIFEST，只排除运行时报告与 MANIFEST 自身。
[补 5] **题卷指纹闸 (G8)** —— 题面逐条 sha256 落到 `PAPERS.sha256`，题卷被改动即判红。
       （题面本就该给模型看，存它的哈希不泄答案，但能防题卷被偷改。）
[补 6] **模型可见面汇总 (G9)** —— 单独扫"模型该看到的那层"并出报告，
       把"模型可见面里有没有答案"变成可判定的事。
[补 7] **ACL 硬锁** —— `seal --acl` 对 `skill/`、`题卷/` 拒绝 Everyone 写入/删除。

────────────────────────────────────────────────────────────────────────────────
隔离的能力边界（必须讲清楚，不许含糊）
────────────────────────────────────────────────────────────────────────────────
  * **主防线是"沙箱里物理不含答案"** —— 标注 / 金标准 / 历史跑批 / 判分脚本
    一律不拷贝。找不到的东西，偷看也看不见。
  * **ACL 挡得住"误改误删"，挡不住"故意偷看"** —— 模型进程与执行会话通常
    是同一个 Windows 用户，系统无法区分它俩；deny ACE 对两者一视同仁。
    所以别把 ACL 当成防泄题的手段：防泄题靠主防线 + 模型侧不挂载仓库读取能力。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── 允许写入的目录 (其余一律只读) ────────────────────────────────────────────
WRITABLE_DIRS = {"answers"}

# _lock/ 里的运行时产物: 不进 MANIFEST 比对 (每次跑都会重写), 也不算"新增未登记"
LOCK_RUNTIME = {
    "verify_report.md", "preflight_report.md", "progress_report.md",
    "ANSWERS.sha256", "lock.log",
}
# MANIFEST 不能哈希自己；BASELINE 也不能（否则自指），但它俩**要被对方覆盖**:
#   BASELINE 由 MANIFEST 覆盖（改 BASELINE 会被完整性闸抓）
#   MANIFEST 由 BASELINE 覆盖（改 MANIFEST 会被基线闸抓）
# 于是单改任一个都会被发现；同时改需先 unseal，而 unseal 会写进 lock.log 留痕。
MANIFEST_SELF = "MANIFEST.sha256"
BASELINE_SELF = "BASELINE.sha256"
PAPERS_SELF = "PAPERS.sha256"

# ── 文件名黑名单 (子串匹配, 命中即判红) ─────────────────────────────────────
BAD_NAME_PATTERNS = [
    r"tasks\.yaml$", r"items\.yaml$", r"rubric\.yaml$",
    r"^REPORT\.md$", r"^TASKS-META", r"traces",
    r"grade", r"live-", r"scenario-", r"report.*\.json$",
    r"leak", r"broken", r"gen_golden", r"normalizers", r"graders",
    r"candidate-answers", r"snapshots", r"__pycache__", r"\.pyc$",
    r"\.env", r"\.git",
]

# ── 内容指纹: 严格区 (skill/, 规则文件) ─────────────────────────────────────
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
    (r"candidate-answers|答案键", "历史答案批次"),
]

# ── 内容指纹: 题卷区 (题号允许, 因题面必需; 答案字段一律判红) ─────────────────
PAPER_PATTERNS = [
    (r"expect_tools|anti_patterns|reason_code|must_not_call|should_call_best|key_fields",
     "答案字段泄漏进题卷"),
    (r"evals/|nl2tool|golden|live-run|traces", "评测目录指针"),
]

SCAN_SUFFIX = {".md", ".txt", ".py", ".yaml", ".yml", ".json", ".cfg", ".toml", ".ini"}
MAX_FILE_BYTES = 2_000_000

# 答案文件命名: NL2T-nn.md。只有这类文件才算"答题产物"。
ANSWER_NAME_RE = re.compile(r"^NL2T-\d+$")
# 规则件里的题号占位符（模板说明用，非定位器）
PLACEHOLDER_TASK_ID = re.compile(r"NL2T-<[^>\n]*>")
# 台账未填哨兵
UNSET_SENTINEL = "<!-- UNSET -->"

# 硬锁目标（内容区）
ACL_TARGETS = ("skill", "题卷")


# ══════════════════════════════════════════════════════════════════════════════
# 通用
# ══════════════════════════════════════════════════════════════════════════════

def sandbox_root(arg: str | None) -> Path:
    return Path(arg).resolve() if arg else Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def iter_files(root: Path):
    """遍历沙箱内所有文件（含 _lock 里的资产件，只排除 VCS/缓存）。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in {".git", "__pycache__", ".ipynb_checkpoints"}]
        for name in filenames:
            yield Path(dirpath) / name


def iter_answer_files(root: Path) -> list[Path]:
    """[修 1] 唯一权威的"哪些算答案"判定：文件名必须严格匹配 NL2T-<数字>.md。

    v1 的两处实现不一致（progress 排除 RUN-INFO.md，preflight 不排除），
    导致 preflight 长期多算一份。此处收敛成一处，两处共用。
    """
    ans = root / "answers"
    if not ans.exists():
        return []
    return sorted(p for p in ans.glob("*.md") if ANSWER_NAME_RE.match(p.stem))


def is_paper_file(r: str) -> bool:
    return r.startswith("题卷/")


def is_strict_file(r: str) -> bool:
    return r.startswith("skill/") or r in {"SANDBOX-RULES.md", "ALLOWED-FILES.md"}


def is_model_visible(r: str) -> bool:
    """模型可见面：被测对象本体 + 工具面 + 题卷 + 规则件 + 答案区。"""
    return (is_strict_file(r) or is_paper_file(r)
            or r.startswith("answers/") or r == "SANDBOX-RULES.md")


FILE_ATTRIBUTE_REPARSE_POINT = 0x0400


def is_link(path: Path) -> bool:
    """符号链接 / junction 一律算逃逸链接。

    坑（负向测试实测出来的）：Windows 的 **junction** 用 `Path.is_symlink()` 查不出来
    （返回 False），但 `mklink /J` **不需要管理员权限** —— 也就是说 junction 比 symlink
    更容易被造出来，却正好是旧闸门看不见的那种。所以这里改成查 `FILE_ATTRIBUTE_REPARSE_POINT`。
    """
    if path.is_symlink():
        return True
    if sys.platform.startswith("win"):
        try:
            return bool(os.lstat(path).st_file_attributes
                        & FILE_ATTRIBUTE_REPARSE_POINT)
        except (OSError, AttributeError):
            return False
    return False


# ══════════════════════════════════════════════════════════════════════════════
# seal / unseal
# ══════════════════════════════════════════════════════════════════════════════

def acl_deny_dir(p: Path) -> bool:
    """拒绝 Everyone 写入/删除（含继承到子对象）。

    注意: 这里**不**拒绝 WA(写属性) 与 WRITE_DAC(改 ACL) —— 否则 unseal 自己也会被挡死,
    沙箱就再也打不开了。所以 ACL 挡的是"误改内容/误删文件", 不是"故意偷看"。
    """
    if not sys.platform.startswith("win"):
        return False
    r = subprocess.run(
        ["icacls", str(p), "/deny", "Everyone:(OI)(CI)(WD,AD,DE,DC)"],
        capture_output=True)          # 不加 text=True: 中文 Windows 输出是 GBK
    return r.returncode == 0


def acl_remove_dir(p: Path) -> None:
    if sys.platform.startswith("win"):
        subprocess.run(["icacls", str(p), "/remove:d", "Everyone", "/T"],
                       capture_output=True)


def set_readonly(path: Path) -> None:
    """设只读。用 os.chmod 而不是 attrib —— 后者要 spawn 上百个进程, seal 会慢到被超时杀掉。"""
    try:
        os.chmod(path, 0o444)
    except OSError:
        pass


def clear_readonly(path: Path) -> None:
    try:
        os.chmod(path, 0o644)
    except OSError:
        pass


def append_log(root: Path, event: str) -> None:
    """封印/解封留痕。unseal 是"开门"动作，事后必须能看出门被开过。"""
    log = root / "_lock" / "lock.log"
    try:
        prev = log.read_text(encoding="utf-8") if log.exists() else ""
    except OSError:
        prev = ""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        log.write_text(prev + f"{stamp}  {event}\n", encoding="utf-8", newline="\n")
        os.chmod(log, 0o644)      # 日志要能持续追加，不能跟内容区一起上只读
    except OSError:
        pass


def cmd_seal(root: Path, use_acl: bool) -> int:
    manifest_lines, sealed = [], 0
    for path in sorted(iter_files(root)):
        r = rel(path, root)
        top = r.split("/")[0]
        if top in WRITABLE_DIRS:
            continue
        if top == "_lock" and (path.name in LOCK_RUNTIME or path.name == MANIFEST_SELF):
            continue
        manifest_lines.append(f"{sha256(path)}  {r}")
        set_readonly(path)
        sealed += 1
    mp = root / "_lock" / MANIFEST_SELF
    mp.write_text(
        "# 沙箱封闭清单: 每行 = sha256 + 相对路径; 内容区文件均已设只读\n"
        + "\n".join(manifest_lines) + "\n", encoding="utf-8", newline="\n")
    set_readonly(mp)

    acl_note = ""
    if use_acl:
        ok = [d for d in ACL_TARGETS if acl_deny_dir(root / d)]
        acl_note = f" · ACL 硬锁 {len(ok)}/{len(ACL_TARGETS)} 个内容目录"
        if not ok:
            acl_note = " · ACL 硬锁失败"
    append_log(root, f"seal(acl={int(use_acl)}) files={sealed}")

    print(f"[seal] 已封闭 {sealed} 个文件 -> _lock/MANIFEST.sha256{acl_note}")
    print(f"[seal] 可写目录: {sorted(WRITABLE_DIRS)}")
    if use_acl and "失败" in acl_note:
        print("   [warn] ACL 未施加成功 —— 可能非 Windows 或权限不足。只读属性仍在，")
        print("          但目录级删除不受阻。这不是泄题风险（沙箱内本无答案），")
        print("          只影响防误删强度。")
    return 0


def cmd_unseal(root: Path) -> int:
    for d in ACL_TARGETS:
        acl_remove_dir(root / d)
    n = 0
    for path in sorted(iter_files(root)):
        clear_readonly(path)
        n += 1
    append_log(root, f"unseal files={n}")
    print(f"[unseal] 已解除 {n} 个文件的只读属性，并移除 {len(ACL_TARGETS)} 个目录的 ACL 硬锁")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# progress
# ══════════════════════════════════════════════════════════════════════════════

def cmd_progress(root: Path) -> int:
    paper_dir = root / "题卷" / "per_task"
    expected = sorted(p.name[:-4] for p in paper_dir.glob("*.txt")) if paper_dir.exists() else []
    done_files = iter_answer_files(root)          # [修 1] 与 preflight 同源
    done = sorted(p.stem for p in done_files)
    missing = [t for t in expected if t not in done]
    extra = [t for t in done if t not in expected] if expected else []

    baseline = root / "_lock" / "ANSWERS.sha256"
    prev: dict[str, str] = {}
    if baseline.exists():
        for line in baseline.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            d, _, r = line.partition("  ")
            prev[r.strip()] = d.strip()
    now = {p.name: sha256(p) for p in done_files}
    changed = [r for r in prev if r in now and prev[r] != now[r]]
    dropped = [r for r in prev if r not in now]

    baseline.write_text(
        "# 答案基线: 跑 progress 时刷新; verify 拿它比对, 检测断点后续跑有没有动过答案\n"
        + "\n".join(f"{d}  {r}" for r, d in sorted(now.items())) + "\n",
        encoding="utf-8", newline="\n")

    lines = [
        "# 答题进度",
        "",
        f"- 沙箱: `{root}`",
        f"- 已完成: **{len(done)}/{len(expected) or N_TASKS}**",
        f"- 缺失: {', '.join(missing) if missing else '无'}",
    ]
    if extra:
        lines.append(f"- ⚠ 题号对不上: {', '.join(extra)}")
    if changed:
        lines.append(f"- ⚠ 自上次基线以来被改动: {', '.join(changed)}")
    if dropped:
        lines.append(f"- ⚠ 自上次基线以来被删除: {', '.join(dropped)}")
    lines += ["", "> 基线已刷新到 `_lock/ANSWERS.sha256`。下次 verify 会以它为参照。", ""]
    (root / "_lock" / "progress_report.md").write_text("\n".join(lines),
                                                       encoding="utf-8", newline="\n")

    print(f"[progress] {len(done)}/{len(expected) or N_TASKS} 完成"
          + (f" · 缺 {len(missing)} 题" if missing else " · 已答完")
          + (f" · 改动 {len(changed)}" if changed else "")
          + (f" · 删除 {len(dropped)}" if dropped else ""))
    if missing:
        print("   缺: " + ", ".join(missing))
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# verify —— 十道闸
# ══════════════════════════════════════════════════════════════════════════════

def cmd_verify(root: Path, manifest_path: Path, repo_hint: str = "") -> int:
    findings: list[str] = []
    stats = {"files": 0, "scanned": 0}

    # 1. 结构
    for must in ["skill", "题卷", "answers", "_lock", "SANDBOX-RULES.md"]:
        if not (root / must).exists():
            findings.append(f"[结构] 缺失必需项: {must}")

    # 2+3+4. 文件名 / 内容指纹
    for path in sorted(iter_files(root)):
        stats["files"] += 1
        r = rel(path, root)
        for pat in BAD_NAME_PATTERNS:
            if re.search(pat, path.name, re.I):
                findings.append(f"[文件名] {r} 命中黑名单 /{pat}/")
                break
        if path.suffix.lower() not in SCAN_SUFFIX:
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        stats["scanned"] += 1
        if is_strict_file(r):
            patterns = STRICT_PATTERNS
        elif is_paper_file(r):
            patterns = PAPER_PATTERNS
        else:
            patterns = []
        # 占位符形式（如 `NL2T-<题号>`）是规则件里合法的文件名模板，不算定位器，
        # 先剥掉再判红 —— 否则规则件里"照 answers/NL2T-<题号>.md 命名"这种必要说明会被误伤。
        probe = PLACEHOLDER_TASK_ID.sub("NL2T-<?>", text) if is_strict_file(r) else text
        for pat, why in patterns:
            m = re.search(pat, probe)
            if m:
                line_no = probe.count("\n", 0, m.start()) + 1
                findings.append(f"[内容] {r}:{line_no} 命中 /{pat}/ ({why})")

    # 5. 逃逸链接（symlink 与 junction 都算，见 is_link 注释）
    for path in sorted(iter_files(root)):
        if is_link(path):
            findings.append(f"[逃逸] {rel(path, root)} 是符号链接/junction")
    for dirpath, dirnames, _ in os.walk(root):
        for d in dirnames:
            p = Path(dirpath) / d
            if is_link(p):
                findings.append(f"[逃逸] {rel(p, root)} 是目录链接")

    # 6. 越界引用 [修 3] 精确匹配 sb<数字>, 排除自身
    try:
        sib_names = [p.name for p in root.parent.iterdir()
                     if p.is_dir() and re.match(r"^sb\d+$", p.name) and p.name != root.name]
    except OSError:
        sib_names = []
    for path in sorted(iter_files(root)):
        r = rel(path, root)
        # 只扫**模型可见面**: `_lock/`、`_exec/` 是执行侧工具, 它们提到兄弟沙箱名字
        # 不产生泄题通道(模型根本不该挂载这两处)。扫了只会误报。
        if not is_model_visible(r) or path.suffix.lower() not in SCAN_SUFFIX:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if repo_hint and repo_hint.lower() in text.lower():
            findings.append(f"[越界] {r} 出现仓库路径 {repo_hint}")
        for sib in sib_names:
            if sib in text:
                line_no = next((i for i, l in enumerate(text.splitlines(), 1) if sib in l), 0)
                findings.append(f"[越界] {r}:{line_no} 出现其他沙箱名 {sib}")

    # 7. 完整性 [修 4] 覆盖 _lock 资产件
    expected: dict[str, str] = {}
    if manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            digest, _, r = line.partition("  ")
            expected[r.strip()] = digest.strip()
    else:
        findings.append("[完整性] 缺 _lock/MANIFEST.sha256 —— 沙箱未封闭")
    actual: dict[str, str] = {}
    for path in sorted(iter_files(root)):
        r = rel(path, root)
        top = r.split("/")[0]
        if top in WRITABLE_DIRS:
            continue
        if top == "_lock" and (path.name in LOCK_RUNTIME or path.name == MANIFEST_SELF):
            continue
        actual[r] = sha256(path)

    # 基线比对用另一份 actual: 排除 BASELINE 自身（它不在自己的清单里）
    baseline_actual = {k: v for k, v in actual.items()
                       if not (k.startswith("_lock/") and Path(k).name == BASELINE_SELF)}
    for r, digest in actual.items():
        if r not in expected:
            findings.append(f"[完整性] 新增未登记文件: {r} (seal 之后才出现的)")
        elif expected[r] != digest:
            findings.append(f"[完整性] 内容被改动: {r}")
    for r in expected:
        if r not in actual:
            findings.append(f"[完整性] 登记文件缺失: {r}")

    # 7b. 答案基线 (断点续跑)
    answers_baseline = root / "_lock" / "ANSWERS.sha256"
    if answers_baseline.exists():
        prev: dict[str, str] = {}
        for line in answers_baseline.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            d, _, r = line.partition("  ")
            prev[r.strip()] = d.strip()
        for name, d in prev.items():
            if not ANSWER_NAME_RE.match(Path(name).stem):
                continue
            p = root / "answers" / name
            if not p.exists():
                findings.append(f"[断点] 答案被删除: answers/{name}")
            elif sha256(p) != d:
                findings.append(f"[断点] 答案被改动: answers/{name} "
                                f"(若为重做, 跑 progress 刷新基线)")

    # 7c. 只读属性
    if sys.platform.startswith("win"):
        for r in expected:
            p = root / r
            if p.exists() and os.access(p, os.W_OK):
                findings.append(f"[只读] {r} 的只读属性已被解除")

    # 7d. 构建期基线 —— 这一闸才是"篡改必被抓"的保证。
    #     MANIFEST 在 seal 时会重算, "先改再封"能骗过它; BASELINE 只在构建时生成, 骗不过。
    baseline_fp = root / "_lock" / "BASELINE.sha256"
    if baseline_fp.exists():
        want: dict[str, str] = {}
        for line in baseline_fp.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            digest, _, r = line.partition("  ")
            want[r.strip()] = digest.strip()
        for r, digest in baseline_actual.items():
            if r not in want:
                findings.append(f"[基线] 构建产物里没有这个文件（seal 后新增的）: {r}")
            elif want[r] != digest:
                findings.append(f"[基线] 内容与本次构建产物不一致: {r}")
        for r in want:
            if r not in baseline_actual:
                findings.append(f"[基线] 本次构建产物的文件缺失: {r}")
    else:
        findings.append("[基线] 缺 _lock/BASELINE.sha256 —— 沙箱不是由构建器产出的")

    # 8. 题卷指纹 [补 5]
    papers_fp = root / "_lock" / "PAPERS.sha256"
    if papers_fp.exists():
        want: dict[str, str] = {}
        for line in papers_fp.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            digest, _, r = line.partition("  ")
            want[r.strip()] = digest.strip()
        for r, digest in want.items():
            p = root / "题卷" / r
            if not p.exists():
                findings.append(f"[题卷] 缺题面/上下文: {r}")
            elif sha256(p) != digest:
                findings.append(f"[题卷] 题面被改动: {r}")
    else:
        findings.append("[题卷] 缺 _lock/PAPERS.sha256 —— 题卷无指纹可比对")

    # 9. 模型可见面汇总 [补 6]
    visible_hits = 0
    for path in sorted(iter_files(root)):
        r = rel(path, root)
        if not is_model_visible(r) or path.suffix.lower() not in SCAN_SUFFIX:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        pats = STRICT_PATTERNS if is_strict_file(r) else (
            PAPER_PATTERNS if is_paper_file(r) else [])
        for pat, _why in pats:
            if re.search(pat, text):
                visible_hits += 1
                break

    forbidden_visible = []
    for path in sorted(iter_files(root)):
        r = rel(path, root)
        if not is_model_visible(r):
            continue
        for tok in FORBIDDEN_FILENAMES:
            if tok in path.name.lower():
                forbidden_visible.append(r)
    if forbidden_visible:
        findings.append("[禁件] 模型可见面出现答案类文件名: "
                        + ", ".join(sorted(set(forbidden_visible))))

    # 报告
    ok = not findings
    lines = [
        "# 沙箱体检报告 (v2)",
        "",
        f"- 沙箱: `{root}`",
        f"- 扫描文件: {stats['files']} (文本扫描 {stats['scanned']})",
        f"- 判定: **{'PASS' if ok else 'FAIL'}** (命中 {len(findings)} 条)",
        f"- 模型可见面泄漏扫描: {'干净' if visible_hits == 0 else f'{visible_hits} 处'}",
        "",
    ]
    if ok:
        lines += ["十道闸全部通过：无黑名单文件名、无答案指纹、无逃逸链接、无越界引用、",
                  "无新增/改动/缺失文件、只读属性完好、题卷指纹一致、模型可见面干净。", ""]
    else:
        lines += ["## 命中明细", ""] + [f"- {f}" for f in findings] + [""]
    (root / "_lock" / "verify_report.md").write_text("\n".join(lines),
                                                     encoding="utf-8", newline="\n")

    print(f"[verify] {'PASS' if ok else 'FAIL'} — 命中 {len(findings)} 条 "
          f"(文件 {stats['files']}/文本扫描 {stats['scanned']}) "
          f"· 可见面 {'干净' if visible_hits == 0 else str(visible_hits) + ' 处'}")
    for f in findings[:20]:
        print("   " + f)
    if len(findings) > 20:
        print(f"   ... 其余 {len(findings) - 20} 条见 _lock/verify_report.md")
    return 0 if ok else 1


# ══════════════════════════════════════════════════════════════════════════════
# preflight
# ══════════════════════════════════════════════════════════════════════════════

def cmd_preflight(root: Path, repo_hint: str = "") -> int:
    """跑批前自检: 把"能不能开始"变成机器判定, 不让执行会话自己猜。"""
    blockers: list[str] = []
    warnings: list[str] = []

    rc = cmd_verify(root, root / "_lock" / MANIFEST_SELF, repo_hint)
    if rc != 0:
        blockers.append("沙箱体检未通过 (见 _lock/verify_report.md)")

    toolface = root / "题卷" / "TOOLFACE.md"
    if not toolface.exists():
        blockers.append("缺 `题卷/TOOLFACE.md` (工具面声明) —— 模型会以为没有可用工具")
    else:
        n_tools = sum(1 for l in toolface.read_text(encoding="utf-8").splitlines()
                      if l.startswith("| `") and l.count("|") >= 3 and "职责" not in l)
        if n_tools < 7:
            warnings.append(f"TOOLFACE.md 里只数到 {n_tools} 个工具, 期望 7 个")

    sp = root / "题卷" / "system_prompt.txt"
    if not sp.exists():
        blockers.append("缺 `题卷/system_prompt.txt`")
    else:
        body = [l for l in sp.read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.lstrip().startswith("#")]
        if not body:
            blockers.append("`题卷/system_prompt.txt` 只有注释, 没有实际 prompt 正文")

    # [修 2] 台账守卫: 哨兵必须消失 + 值非空 + 不是残留表头
    ri = root / "answers" / "RUN-INFO.md"
    if not ri.exists():
        warnings.append("缺 `answers/RUN-INFO.md` 台账")
    else:
        text = ri.read_text(encoding="utf-8")
        for field in ("run_id", "model_id", "system_prompt_version",
                      "started_at", "operator"):
            m = re.search(r"\|\s*" + field + r"\s*\|\s*(.*?)\s*\|", text)
            val = m.group(1).strip() if m else ""
            unset = (not val
                     or UNSET_SENTINEL in val
                     or val in {"|", "---"}
                     or val.startswith("例：")
                     or val.startswith("<!--"))
            if unset:
                warnings.append(f"台账 `{field}` 未填 —— 该批与别的批次不可横比")

    n_paper = len(list((root / "题卷" / "per_task").glob("*.txt"))) \
        if (root / "题卷" / "per_task").exists() else 0
    if n_paper < N_TASKS:
        blockers.append(f"`题卷/per_task/` 只有 {n_paper} 个题面, 期望 {N_TASKS} 个")

    # [修 1] 与 progress 同源
    n_ans = len(iter_answer_files(root))

    ok = not blockers
    lines = [
        "# 沙箱跑批前自检 (v2)",
        "",
        f"- 沙箱: `{root}`",
        f"- 判定: **{'可以开始' if ok else '暂不可开始'}**",
        f"- 硬阻塞: {len(blockers)} · 提醒: {len(warnings)}",
        f"- 题面: {n_paper}/{N_TASKS} · 已作答: {n_ans}/{N_TASKS}",
        "",
    ]
    if blockers:
        lines += ["## 硬阻塞（必须先解决）", ""] + [f"- {b}" for b in blockers] + [""]
    if warnings:
        lines += ["## 提醒（不阻断）", ""] + [f"- {w}" for w in warnings] + [""]
    lines += [
        "## 前置口径（别把它当故障）",
        "",
        "- 本评测**离线判决策**：不需要真连站点、不需要 BEST/MCP 在线、不需要装 requests；",
        "- 按“实际会发出的调用”给出工具名与参数即可；工具面见 `题卷/TOOLFACE.md`；",
        "- 一题一个新会话；答案写 `answers/<题号>.md`。",
        "",
    ]
    (root / "_lock" / "preflight_report.md").write_text("\n".join(lines),
                                                         encoding="utf-8", newline="\n")

    print(f"[preflight] {'可以开始' if ok else '暂不可开始'} "
          f"— 硬阻塞 {len(blockers)} · 提醒 {len(warnings)} "
          f"· 题面 {n_paper}/{N_TASKS} · 已作答 {n_ans}/{N_TASKS}")
    for b in blockers:
        print("   阻塞: " + b)
    for w in warnings:
        print("   提醒: " + w)

    print("\n下一步:")
    if ok:
        print("  1. 读 题卷/system_prompt.txt（本次 system prompt，已预填）")
        print("  2. 逐题：读 题卷/per_task/<题号>.txt（有 context 的先发 context），"
              "一题一个新会话")
        print("  3. 每题写 answers/<题号>.md（照 answers/_答题模板.md 两段式）")
        print("  4. 收尾：python _lock/sandbox_lock.py progress  然后  verify")
        print("\n口径：不需要联网、不需要 MCP、不需要任何依赖 —— 离线判决策，"
              "按“你会发出的调用”给工具名与参数即可（工具面见 题卷/TOOLFACE.md）。")
    else:
        print("  按上面的阻塞项逐条处理；改完重跑：")
        print("     python _lock/sandbox_lock.py preflight")
        print("  若缺件是构建问题，重建三个沙箱（必须一起重建，别只建一个）：")
        print("     python _builder/build_sandboxes.py --apply --force")
    return 0 if ok else 1


# 常量
N_TASKS = 28
FORBIDDEN_FILENAMES = (
    "tasks.yaml", "items.yaml", "rubric.yaml", "graders.py", "runner.py",
    "gen_golden.py", "normalizers.py", "report.json", "live-", "candidate-answers",
)


def main() -> int:
    ap = argparse.ArgumentParser(description="E1 答题沙箱目录锁 v2")
    ap.add_argument("cmd", choices=["seal", "verify", "unseal", "progress", "preflight"])
    ap.add_argument("--root", default=None, help="沙箱根 (缺省=本脚本上级目录)")
    ap.add_argument("--repo-hint", default="", help="仓库路径串, 出现在沙箱内即判越界")
    ap.add_argument("--acl", action="store_true", help="seal 时一并上 ACL 硬锁")
    ns = ap.parse_args()
    root = sandbox_root(ns.root)
    if not root.exists():
        print(f"[error] 沙箱根不存在: {root}")
        return 2
    if ns.cmd == "seal":
        return cmd_seal(root, ns.acl)
    if ns.cmd == "unseal":
        return cmd_unseal(root)
    if ns.cmd == "progress":
        return cmd_progress(root)
    if ns.cmd == "preflight":
        return cmd_preflight(root, ns.repo_hint)
    return cmd_verify(root, root / "_lock" / MANIFEST_SELF, ns.repo_hint)


if __name__ == "__main__":
    raise SystemExit(main())
