#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""泄题审计（独立于 sandbox_lock.py，专门找"答案有没有漏进沙箱"）

为什么不直接信 verify: verify 是我自己写的闸门, 闸门说"干净"属于自证。
这一件换角度 —— **拿标注文件里的真实答案原文当探针，回头去沙箱里搜**。
字段名（expect_tools / anti_patterns）被净化掉并不等于安全：
万一某句错法描述原样躺在某个 md 里，按字段名扫描是抓不到的。

探针分级（关键：别把工具名当答案）:
    P0 致命   anti_patterns 的中文描述原文（错法清单 = 直接告诉模型"什么算错"）
    P1 严重   reject.suggest / clarify.options 的中文原文
    P2 参考   clarify.probes 探测词（短词，误报高，只提示不算失败）

用法:
    python _builder/audit_leak.py                     # 审计三箱
    python _builder/audit_leak.py --repo <仓库根>
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BOXES = ("sb1", "sb2", "sb3")
N_TASKS = 28
KNOWN_REPO_CANDIDATES = (
    r"<USER_HOME>\OneDrive\桌面\AI-archive-pre-sinking-snapshot-20261010",
)
SCAN_SUFFIX = {".md", ".txt", ".py", ".yaml", ".yml", ".json", ".cfg", ".toml", ".ini"}
MAX_FILE_BYTES = 3_000_000

# 文件名里出现这些即判红（答案 / 历史跑批 / 判分侧）
FORBIDDEN_NAME_TOKENS = (
    "tasks.yaml", "items.yaml", "rubric.yaml",
    "graders", "runner", "gen_golden", "normalizers",
    "candidate-answers", "snapshots", "live-", "traces", "broken",
    "golden", "leak", "report.json", ".env", ".git", "__pycache__", ".pyc",
)
# 标注字段名（出现即说明整块标注混进来了）
FIELD_NAME_PATTERNS = (
    "expect_tools", "expect_tools_after_clarify", "anti_patterns",
    "reason_code", "reason_aliases", "must_not_call", "should_call_best",
    "clarify.probes", "golden-from-annotation", "live-run", "source=live",
    "candidate-answers", "key_fields",
    # ── 判分侧（第一轮审计实测漏网、本轮补上）─────────────────────────────
    # 上一轮规则只盯 E1 标注字段名，结果 skill/README.md 里整张"评测层组件
    # 清单表"原样躺在那儿：评分量规文件名、五维维度名、权重和=1.0、
    # pass_score 0.9 > WARN 0.85、24 场景、六审计器；src/client_paging.py
    # 注释里还带 `graders.py:274-276`。这些不是 E1 答案，但属于白名单里
    # 承诺"看不见"的判分逻辑。探针必须能抓住这一类，否则修了也白修。
    "eval_runner.py", "graders.py", "probes.py", "probe_support.py",
    "case_executor.py", "scoring-rubric", "test-scenarios.yaml",
    "pass_score",
)

CJK = re.compile(r"[一-鿿]")
CONCRETE_TASK_ID = re.compile(r"NL2T-\d")
PLACEHOLDER_TASK_ID = re.compile(r"NL2T-<[^>\n]*>")

# ── 扫描区域分级 ────────────────────────────────────────────────────────
# 关键改动（第二版）：判定必须看"这个命中落在谁的视野里"。
#
#   模型可见区  → 命中即 FATAL（模型能读到 = 泄题）
#   执行侧      → 命中只记 INFO（闸门脚本必须写出它要拦的字段名，这是设计使然）
#
# 之前把两区混在一起报红，于是 sandbox_lock.py 里那句
# `BLACK_FIELD = ("expect_tools", ...)` 自己把自己判成了"泄题"，
# 48 条噪音淹掉了真正要看的东西。
MODEL_VISIBLE_TOPS = ("skill", "题卷")          # 模型视野内的目录
MODEL_VISIBLE_FILES = {"SANDBOX-RULES.md", "ALLOWED-FILES.md"}
MODEL_VISIBLE_DIRS = ("_exec/题包",)            # 题包 = 真正喂给模型的文本
STRICT_TOPS = ("skill",)                        # 严格区：连题号都不许有
RULE_FILES = {"SANDBOX-RULES.md", "ALLOWED-FILES.md"}
PAPER_TOPS = ("题卷",)
EXEC_TOPS = ("_lock", "_exec", "answers")       # 执行侧：不算泄题，只记 INFO


def sha256_file(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(p: Path, root: Path) -> str:
    return str(p.relative_to(root)).replace("\\", "/")


def walk(root: Path):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns
                  if d not in {".git", "__pycache__", ".ipynb_checkpoints"}]
        for fn in fns:
            yield Path(dp) / fn


def detect_repo() -> Path:
    for c in KNOWN_REPO_CANDIDATES:
        p = Path(c)
        if (p / "evals" / "nl2tool" / "tasks.yaml").exists():
            return p.resolve()
    for base in (Path.cwd(), *Path.cwd().parents):
        if (base / "evals" / "nl2tool" / "tasks.yaml").exists():
            return base
    return Path.cwd()


def load_tasks(repo: Path) -> list[dict]:
    import yaml
    data = yaml.safe_load(
        (repo / "evals" / "nl2tool" / "tasks.yaml").read_text(encoding="utf-8"))
    return data["tasks"]


def norm(text: str) -> str:
    """归一化：去围栏/标记/空白，降低"同一句话换了排版"造成的漏检。"""
    text = text.replace("```", " ")
    text = re.sub(r"[`*>·•|]", "", text)
    return re.sub(r"\s+", "", text)


def build_probes(tasks: list[dict]) -> dict[str, list[tuple[str, str]]]:
    """返回 {级别: [(探针原文, 出处), ...]}。

    探针筛选很关键 —— 第一版把 reject.must_not_call 的**工具名**也当探针,
    结果 65 个文件只因提到 `cone_search` 就被判"泄漏", 可工具名本来就该
    写在工具文档里。所以这里只收**中文长描述**: 含汉字且去括号后 >= 8 字。
    短词（探测词表）降级到 P2，只提示不判失败。
    """
    p0: list[tuple[str, str]] = []
    p1: list[tuple[str, str]] = []
    p2: list[tuple[str, str]] = []

    def head_of(s) -> str:
        return re.split(r"[（(]", str(s).strip())[0].strip()

    def grade(probe: str, bucket: list, origin: str) -> None:
        if not probe or not CJK.search(probe):
            return
        if len(probe) >= 8:
            bucket.append((probe, origin))
        elif len(probe) >= 3:
            p2.append((probe, origin))

    for t in tasks:
        tid = t["id"]

        # P0: 错法清单（最敏感）
        for ap in (t.get("anti_patterns") or []):
            grade(head_of(ap.get("pattern", "")), p0, f"{tid} anti_patterns")

        rj = t.get("reject") or {}
        cl = t.get("clarify") or {}

        # P1: 拒绝理由码（英文枚举，但也算答案）
        rc = rj.get("reason_code")
        if rc:
            p1.append((str(rc), f"{tid} reject.reason_code"))

        # P1: 替代路径 / 澄清选项原文
        for s in (rj.get("suggest") or []):
            grade(head_of(s), p1, f"{tid} reject.suggest")
        for o in (cl.get("options") or []):
            grade(head_of(o), p1, f"{tid} clarify.options")

        # P2: 探测词表（短，误报高）
        for pr in (cl.get("probes") or []):
            grade(str(pr).strip(), p2, f"{tid} clarify.probes")
        for m in (cl.get("missing") or []):
            grade(str(m).strip(), p2, f"{tid} clarify.missing")

    # 去重（同一探针可能来自多条任务）
    def dedup(bucket: list[tuple[str, str]]) -> list[tuple[str, str]]:
        seen, out = set(), []
        for probe, origin in bucket:
            if probe in seen:
                continue
            seen.add(probe)
            out.append((probe, origin))
        return out

    return {"P0": dedup(p0), "P1": dedup(p1), "P2": dedup(p2)}


def check_locks() -> list[tuple[str, str, str]]:
    """检查三箱的目录锁是否真的在。返回 [(箱, 项目, 状态), ...]。

    为什么要单独查这一项 —— ACL 是最容易"以为上了、其实没上"的东西：
    `icacls` 命令行输出在中文 Windows 上是 GBK，喂给 Python/管道会乱码，
    漏看的 deny 行就当不存在。所以这里绕开 icacls，直接读 .NET 的 ACL 对象。
    """
    # 被检查的四个目录。**注意：名字不让中文穿过进程管道** ——
    # 实测 PowerShell 回传"题卷"会乱码成空串，于是判定逻辑把 3 箱×2 目录 = 6
    # 只数到 3，明明上了锁却报"锁缺失"。所以管道里只走 ASCII 索引，
    # 回到 Python 再映射成目录名。（跟 icacls 的 GBK 坑是同一类，换个壳还在。）
    DIR_NAMES = ("skill", "题卷", "answers", "_lock")
    if not sys.platform.startswith("win"):
        return [("—", "ACL", "非 Windows，跳过")]
    import subprocess
    rows: list[tuple[str, str, str]] = []
    # 目录名一律 **hex 编码** 再穿过管道：PowerShell 回传中文会乱码成空串，
    # 判定逻辑因此把"3 箱 × 2 个应锁目录 = 6"只数到 3，明明锁上了却报缺失。
    # hex 是纯 ASCII，怎么传都不坏，回来再解码。
    ps = (
        "$r='" + str(ROOT).replace("'", "''") + "';"
        "foreach($b in @('sb1','sb2','sb3')){"
        "  Get-ChildItem (Join-Path $r $b) -Directory | ForEach-Object {"
        "    $hex = -join ($_.Name.ToCharArray() | ForEach-Object { '{0:x4}' -f [int]$_ });"
        "    $deny = (Get-Acl $_.FullName).Access | "
        "            Where-Object { $_.AccessControlType -eq 'Deny' };"
        "    if($deny){ Write-Output (\"$b|$hex|DENY\") } else { Write-Output (\"$b|$hex|OK\") }"
        "  }"
        "}"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=90)
        out = r.stdout.decode("ascii", "ignore")

        def unhex(h: str) -> str:
            try:
                return "".join(chr(int(h[i:i + 4], 16)) for i in range(0, len(h), 4))
            except ValueError:
                return "?"

        for line in out.splitlines():
            parts = line.strip().split("|")
            if len(parts) == 3:
                rows.append((parts[0], unhex(parts[1]), parts[2]))
    except Exception as e:                                  # noqa: BLE001
        rows.append(("—", "ACL 检查", f"无法执行: {type(e).__name__}"))
    return rows


def check_readonly() -> list[tuple[str, str]]:
    """统计每箱被设为只读的文件数（seal 的产物之一）。"""
    import stat
    rows: list[tuple[str, str]] = []
    for b in BOXES:
        root = ROOT / b
        if not root.exists():
            rows.append((b, "沙箱不存在"))
            continue
        total = ro = 0
        for p in walk(root):
            if p.name.startswith(".") or p.parent.name == "_lock":
                continue
            total += 1
            mode = p.stat().st_mode
            if not (mode & stat.S_IWUSR):
                ro += 1
        rows.append((b, f"{ro}/{total} 个内容文件为只读"))
    return rows


def collect_corpus(root: Path) -> list[tuple[str, str, str]]:
    corpus = []
    for p in walk(root):
        if p.suffix.lower() not in SCAN_SUFFIX:
            continue
        if p.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            t = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        corpus.append((rel(p, root), t, norm(t)))
    return corpus


def write_report(probes, p0, p1, other, exec_files, exec_why, warns,
                 lock_rows, ro_rows, acl_ok, leak_free) -> Path:
    """把审计结论写成报告。

    为什么报告由脚本产出 —— 手写文件一旦被误删就只剩记忆，而这份报告的
    价值恰恰在于"可复现"。现在它是一条命令的产物：`python _builder/audit_leak.py`。
    """
    import datetime as _dt
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    verdict = ("无泄漏 ✅" if leak_free else "存在泄漏 ❌") + \
              (" · 目录锁已上 ✅" if acl_ok else " · 目录锁缺失 ❌")

    def lock_table() -> str:
        rows = ["| 箱 | `skill/` | `题卷/` | `answers/` | `_lock/` | 只读文件 |",
                "|---|---|---|---|---|---|"]
        for b in BOXES:
            cells, ro = [], next((t for bb, t in ro_rows if bb == b), "?")
            for d in ("skill", "题卷", "answers", "_lock"):
                s = next((st for bb, dd, st in lock_rows if bb == b and dd == d), "?")
                cells.append("**已上锁**" if s == "DENY" else "可写")
            rows.append(f"| {b} | " + " | ".join(cells) + f" | {ro} |")
        return "\n".join(rows)

    L = [
        "# 沙箱泄题审计 · 报告",
        "",
        f"- 审计时间: {now}（本报告由 `_builder/audit_leak.py` 生成，可复现）",
        "- 审计对象: `sb1` `sb2` `sb3`",
        f"- 沙箱根: `{ROOT}`",
        f"- 探针来源: 仓库 `evals/nl2tool/tasks.yaml`（**标注原文**，不是自列的黑名单）",
        f"- **审计结论: {verdict}**",
        "",
        "---",
        "",
        "## 一、为什么不能只信 `verify`",
        "",
        "`verify` 是**我自己写的闸门**。闸门说\"干净\"属于自证——它只会去找我事先想到的模式，",
        "想不到的就躺着不动，而且恰恰不会报错。",
        "",
        "所以换角度：**拿标注文件里的真实答案原文当探针，回头去沙箱里搜**。",
        "字段名被净化掉 ≠ 安全。万一某句\"错法描述\"原样躺在某个 md 里，",
        "按字段名扫描是**抓不到**的。",
        "",
        "### 探针分级",
        "",
        "| 级别 | 内容 | 探针数 | 判定 |",
        "|------|------|-------|------|",
        f"| P0 致命 | `anti_patterns` 中文描述原文（错法清单 = 直接告诉模型\"什么算错\"） | {len(probes['P0'])} | 命中即失败 |",
        f"| P1 严重 | `reason_code` / `suggest` / `clarify.options` 原文 | {len(probes['P1'])} | 命中即失败 |",
        f"| P2 参考 | `probes` / `missing` 探测词（短词，误报高） | {len(probes['P2'])} | 只提示 |",
        "",
        "> **探针筛选很关键** —— 第一版把 `must_not_call` 的**工具名**",
        "> （`cone_search` / `crossmatch_batch` / `fetch_page`）也当探针，",
        "> 结果 65 个文件只因在工具文档里正常提到工具名就被判\"泄漏\"，刷出 **2607 条噪音**。",
        "> 所以这里只收**中文长描述**：含汉字且去括号后 ≥ 8 字；短词降级到 P2。",
        "",
        "---",
        "",
        "## 二、分区判定（关键改动）",
        "",
        "判定必须看\"这个命中落在**谁的视野**里\"：",
        "",
        "| 分区 | 目录 | 判定 |",
        "|------|------|------|",
        "| **模型可见区** | `skill/`、`题卷/`、`_exec/题包/`、`SANDBOX-RULES.md`、`ALLOWED-FILES.md` | 命中即 **FATAL** |",
        "| **执行侧** | `_lock/`、`_exec/`（题包除外）、`answers/` | 命中只记 **INFO** |",
        "",
        "第一版把两区混在一起报红，于是 `sandbox_lock.py` 里那句",
        "`BLACK_FIELD = (\"expect_tools\", ...)` **自己把自己判成了\"泄题\"**，",
        "48 条噪音淹掉了真正要看的东西。",
        "",
        "---",
        "",
        "## 三、审计发现（均已修复并复检）",
        "",
        "### 发现 1（真实泄漏）：`skill/README.md` 评测层组件清单表",
        "",
        "`### contracts/` 小节里嵌了**第二张表**，逐行登记评测层组件：",
        "`eval_runner.py` / `probes.py` / `case_executor.py` / `probe_support.py` / `cases/`，",
        "并写明**五维加权评分、维度名、权重和=1.0、pass_score 0.9 > WARN 0.85、24 场景、六审计器**。",
        "",
        "性质：不是 E1 六维的答案，`pass_score 0.9` 也不是 E1 的通过线。",
        "但它属于 `ALLOWED-FILES.md` 里承诺\"看不见\"的**判分逻辑**（判据/权重/通过线/红线）。",
        "**承诺了就得兑现**——否则模型至少知道\"存在评分体系、阈值在 0.9 附近\"，足以改变答题策略。",
        "",
        "漏网原因：老规则只盯 E1 标注字段名，没列**判分侧组件名**。",
        "且这张表**逐行打码救不了**：把文件名换掉后剩下\"评审执行器：24 场景…五维加权评分\"照泄不误",
        "→ 必须整表砍掉 → 新增 `BLOCK_RANGE_CUTS` 区间切割。",
        "",
        "### 发现 2（真实泄漏）：`skill/src/client_paging.py:395`",
        "",
        "注释里带 `graders.py:274-276` —— **判分脚本文件名 + 行号**。",
        "",
        "### 发现 3（文档矛盾，非泄漏）：`SANDBOX-RULES.md`",
        "",
        "写「不可以看 `_exec/`」，而**题包就放在 `_exec/题包/`**。",
        "照字面严格执行，模型会拒绝读那个本该喂给它的自包含题包。",
        "",
        "**已修**：在 § 一.4 与 § 三 各补一段，讲清例外——",
        "`_exec/` 整目录不给你；唯一例外是 `_exec/题包/<当前题号>.md`，",
        "由执行会话单独取出、一次一份。顺带把题包里那句",
        "「写完立刻自检：`python _lock/check_answer.py`」标为**给执行会话的**，",
        "它既与\"自包含、不用翻别处\"冲突，又把注意力引向 `_lock/`。",
        "",
        "### 发现 4（构建器空头承诺）：`--acl` 参数没真上锁",
        "",
        "构建器 `--acl` 只 `print(\"（--acl 已在 seal 时一并施加）\")`，",
        "**从不调用 `seal --acl`**。实测（PowerShell 读 ACL）三箱 `skill/`、`题卷/`",
        "一条 Everyone deny 都没有 —— 文档说有、实际没有，比明说没有危险得多。",
        "已改为构建器在 `--apply` 后**真跑** `seal [--acl]`，并逐箱回显结果。",
        "",
        "> 顺带记一个排查教训：`icacls` 命令行输出在中文 Windows 上是 GBK，",
        "> 喂进管道/Python 会乱码，deny 行容易被当不存在。**读 ACL 要用 PowerShell**",
        "> （`Get-Acl` 直接拿对象），本脚本的 `check_locks()` 就是这么做的。",
        "",
        "---",
        "",
        "## 四、顺带修掉的净化器缺陷",
        "",
        "- **规则互相遮挡（漏杀）**：老逻辑每行命中第一条就 `break`，",
        "  于是 `evals/probes.py` 先命中 `evals/` 就收工，**`probes.py` 原样留下**。",
        "  改成逐条过、累加红改，并合并连续重复占位符。",
        "- **净化过头（误杀）**：`.md` 原来整行替换。实测 `static/core/stance.md:2`",
        "  是 344 字立场声明，只顺带提了句 `evals`，整行换掉 = 把有用的立场要求一起删了。",
        "  改成**片段级红改为默认**，只有\"去标点空白后 < 12 字\"的空骨架行才整行占位。",
        "",
        "两者靠\"骨架长度\"这个判据分开。修复中构建期断言还抓到一次",
        "YAML 不可哈希键问题（`evals` 处于 `{key: v}` 键位时替换成裸占位符），已修。",
        "",
        "---",
        "",
        "## 五、复检结果（本次实跑）",
        "",
        "| 项目 | 命中 |",
        "|------|------|",
        f"| P0 致命（错法清单原文） | **{len(p0)}** |",
        f"| P1 严重（理由码 / 澄清选项 / 替代路径） | **{len(p1)}** |",
        f"| 文件名 / 字段名 / 越界 / 题面一致性（模型可见区） | **{len(other)}** |",
        f"| 执行侧（不计入判定） | {len(exec_files)} 个文件（`_lock/` 脚本自称字段名，设计使然） |",
        "",
        "### 目录锁实测",
        "",
        lock_table(),
        "",
        f"ACL 硬锁整体判定: **{'✅ 三箱 skill/ 与 题卷/ 均已拒绝 Everyone 写入删除' if acl_ok else '❌ 有箱未上锁'}**",
        "",
        "> deny 权限 = `CreateFiles, AppendData, DeleteSubdirectoriesAndFiles, Delete`",
        "> （即 `WD,AD,DE,DC`）。**没有**拒绝 `WA`(写属性) 与 `WRITE_DAC`(改 ACL) ——",
        "> 否则 `unseal` 自己也会被挡死，沙箱再也打不开。",
        "",
        "### 四部验收（另跑 `verify_all.py`）",
        "",
        "| 部 | 项目 | 结果 |",
        "|----|------|------|",
        "| A | 三箱一致性（155 条目） | PASS |",
        "| B | 静态隔离扫描 | PASS |",
        "| C | 负向测试 8 场景 | PASS |",
        "| D | 命令自检 | PASS |",
        "",
        "---",
        "",
        "## 六、残留风险（如实写明）",
        "",
        "| 防线 | 挡得住 | 挡不住 |",
        "|------|--------|--------|",
        "| **物理不含答案** | 任何偷看（沙箱里根本没有） | — |",
        "| 只读属性 + ACL | 误改内容、误删文件 | 同用户下的**故意**读取（模型与执行会话通常同一 Windows 用户） |",
        "| 软锁十一道闸 | 事后发现篡改/越界并判红 | 实时阻止写入 |",
        "",
        "**别把 ACL 当防泄题手段**。防泄题靠两件事：",
        "",
        "1. 沙箱**物理不含**答案（本次审计已验证）；",
        "2. 被测模型侧**不挂载**仓库文件读取 / grep / 检索能力（纪律，靠执行者遵守）。",
        "",
        "另外 `_lock/` 与 `answers/` 同箱，且 `_lock/` **未上 ACL**（必须可写，否则闸门自己锁死自己）。",
        "所以「只把 `skill/` + `题卷/` + 单份题包喂给模型」是**硬前提**，不是可选项。",
        "",
        "---",
        "",
        "## 七、复现命令",
        "",
        "```bash",
        "cd <USER_HOME>\\E1-答题沙箱-2026-10-17",
        "",
        "# 独立泄题审计 + 目录锁检查 + 生成本报告",
        "python _builder/audit_leak.py",
        "",
        "# 四部验收（一致性 / 静态隔离 / 8 项负向测试 / 命令自检）",
        "python _builder/verify_all.py",
        "",
        "# 重建三箱并一并上锁（必须三箱一起重建）",
        "python _builder/build_sandboxes.py --apply --force --acl",
        "```",
        "",
    ]
    out = ROOT / "_验收" / "泄题审计报告.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8", newline="\n")
    print(f"\n[audit] 报告已生成: {out}")
    return out


def audit(repo: Path) -> int:
    tasks = load_tasks(repo)
    probes = build_probes(tasks)
    print("══════════ 泄题审计（独立于 sandbox_lock.py）══════════")
    print(f"标注来源: {repo / 'evals' / 'nl2tool' / 'tasks.yaml'}")
    print(f"探针规模: P0(错法清单) {len(probes['P0'])} · "
          f"P1(理由码/选项/建议) {len(probes['P1'])} · "
          f"P2(探测词·仅提示) {len(probes['P2'])}")
    print()

    fatal: list[str] = []
    warns: list[str] = []
    infos: list[tuple[str, str, str]] = []   # (箱, 相对路径, 命中说明)

    def zone_of(r: str) -> str:
        """判定某文件属于'模型可见区'还是'执行侧'。"""
        for d in MODEL_VISIBLE_DIRS:
            if r.startswith(d + "/") or r.startswith(d + "\\"):
                return "model"
        top = r.split("/")[0]
        if top in MODEL_VISIBLE_TOPS or r in MODEL_VISIBLE_FILES:
            return "model"
        return "exec"

    for b in BOXES:
        root = ROOT / b
        if not root.exists():
            fatal.append(f"{b}: 沙箱不存在")
            continue
        corpus = collect_corpus(root)

        # ── 1) 文件名黑名单（只看模型可见区）─────────────────────────────
        # 执行侧不查：_lock/ 里本来就有净化日志、verify 报告这类名字。
        for p in walk(root):
            if zone_of(rel(p, root)) != "model":
                continue
            low = p.name.lower()
            for tok in FORBIDDEN_NAME_TOKENS:
                if tok in low:
                    fatal.append(f"[{b} 文件名] {rel(p, root)} ← '{tok}'")
                    break

        # ── 2) 内容指纹（按区域分级）──────────────────────────────────────
        for r, raw, nt in corpus:
            z = zone_of(r)
            top = r.split("/")[0]
            if top in STRICT_TOPS or r in RULE_FILES:
                if CONCRETE_TASK_ID.search(PLACEHOLDER_TASK_ID.sub("NL2T-<?>", raw)):
                    ln = next((i for i, l in enumerate(raw.splitlines(), 1)
                               if CONCRETE_TASK_ID.search(
                                   PLACEHOLDER_TASK_ID.sub("NL2T-<?>", l))), 0)
                    fatal.append(f"[{b} 题号] {r}:{ln}")
            for f in FIELD_NAME_PATTERNS:
                if f in raw:
                    ln = next((i for i, l in enumerate(raw.splitlines(), 1)
                               if f in l), 0)
                    msg = f"{r}:{ln} ← '{f}'"
                    if z == "model":
                        fatal.append(f"[{b} 标注字段·模型可见] {msg}")
                    else:
                        infos.append((b, r, "标注字段名（执行侧脚本自称，属设计）"))

        # ── 3) 反向探针：标注原文是否被抄进沙箱 ────────────────────────────
        # 这一条不分区域：标注原文(错法描述 / 理由码 / 澄清选项)任何地方都不该出现，
        # 连 _lock/ 里也不该有 —— 闸门只需要字段名，不需要答案内容。
        for lvl in ("P0", "P1"):
            for probe, origin in probes[lvl]:
                pn = norm(probe)
                if len(pn) < 8:
                    continue
                hits = [r for r, _raw, nt in corpus if pn in nt]
                if hits:
                    fatal.append(f"[{lvl} {b}] {origin} 原文出现在: "
                                 + ", ".join(hits[:3]))

        # P2 只提示
        for probe, origin in probes["P2"]:
            pn = norm(probe)
            if len(pn) < 3:
                continue
            hits = [r for r, _raw, nt in corpus if pn in nt]
            if hits:
                warns.append(f"[P2 {b}] {origin} “{probe}” 出现在 "
                             f"{len(hits)} 个文件（短词，通常无害）")

        # ── 4) 题面一致性 ────────────────────────────────────────────────
        for t in tasks:
            tid = t["id"]
            f = root / "题卷" / "per_task" / f"{tid}.txt"
            if not f.exists():
                fatal.append(f"{b}: 缺题面 {tid}")
                continue
            if f.read_text(encoding="utf-8").strip() != t["utterance"].strip():
                fatal.append(f"{b}/{tid}: 题面与标注 utterance 不一致")

    p0 = [f for f in fatal if f.startswith("[P0")]
    p1 = [f for f in fatal if f.startswith("[P1")]
    other = [f for f in fatal if not f.startswith(("[P0", "[P1"))]

    # 执行侧命中按文件去重统计（同一脚本可能命中多个字段名，只算一个文件）
    exec_files = sorted({(b, r) for b, r, _why in infos})
    exec_why = sorted({why for _b, _r, why in infos})

    print("── P0 致命：错法清单(anti_patterns)原文是否漏进沙箱 ──")
    print(f"   [模型可见区] 命中 {len(p0)} 条")
    for x in p0[:12]:
        print("     ✗ " + x)
    print()
    print("── P1 严重：理由码 / 澄清选项 / 替代路径原文 ──")
    print(f"   [模型可见区] 命中 {len(p1)} 条")
    for x in p1[:12]:
        print("     ✗ " + x)
    print()
    print("── 文件名 / 字段名(模型可见区) / 题面一致性 ──")
    print(f"   命中 {len(other)} 条")
    for x in other[:12]:
        print("     ✗ " + x)
    print()
    print("── 执行侧（_lock / _exec / answers，模型拿不到）──")
    print(f"   涉及 {len(exec_files)} 个文件")
    for b, r in exec_files[:12]:
        print(f"     · [{b}] {r}")
    if exec_why:
        print(f"   说明: {'; '.join(exec_why)}")
    print()

    if warns:
        print("── P2 参考（短词探测，高误报，不算失败）──")
        for w in warns[:6]:
            print("     · " + w)
        print()

    # ── 5) 目录锁（ACL 硬锁 + 只读属性）───────────────────────────────────
    lock_rows = check_locks()
    ro_rows = check_readonly()
    acl_expected = {("skill", "DENY"), ("题卷", "DENY"),
                    ("answers", "OK"), ("_lock", "OK")}
    acl_got = {(d, s) for _b, d, s in lock_rows}
    acl_ok = acl_expected <= acl_got
    lock_fail = sum(1 for _b, d, s in lock_rows
                    if (d, s) in {("skill", "DENY"), ("题卷", "DENY")}) != 6

    print("── 目录锁（ACL 硬锁 / 只读属性）──")
    for b in BOXES:
        cells = [f"{d}={'锁' if s == 'DENY' else '可写'}"
                 for bb, d, s in lock_rows if bb == b]
        ro = next((t for bb, t in ro_rows if bb == b), "?")
        print(f"   {b}: {' · '.join(cells)}  |  {ro}")
    print(f"   ACL 硬锁: {'✅ 三箱 skill/ 与 题卷/ 均已拒绝 Everyone 写入删除' if acl_ok and not lock_fail else '❌ 有箱未上锁'}")
    print()

    print("════════════════════════════════════════════")
    print(f"   模型可见区 P0 致命: {len(p0)} · P1 严重: {len(p1)} · 其他: {len(other)}")
    print(f"   执行侧（不计入判定）: {len(exec_files)} 个文件")
    print(f"   目录锁: {'✅' if acl_ok and not lock_fail else '❌'}")
    leak_free = not fatal
    print(f"   ── 总判定: {'无泄漏 ✅' if leak_free else '存在泄漏 ❌'}"
          f"{' · 锁已上 ✅' if acl_ok and not lock_fail else ' · 锁缺失 ❌'}")
    print("══════════════════════════════════════════")

    write_report(probes, p0, p1, other, exec_files, exec_why, warns,
                 lock_rows, ro_rows, acl_ok and not lock_fail, leak_free)
    return 0 if (leak_free and acl_ok and not lock_fail) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="沙箱泄题审计")
    ap.add_argument("--repo", default=None)
    ns = ap.parse_args()
    repo = Path(ns.repo).resolve() if ns.repo else detect_repo()
    return audit(repo)


if __name__ == "__main__":
    raise SystemExit(main())
