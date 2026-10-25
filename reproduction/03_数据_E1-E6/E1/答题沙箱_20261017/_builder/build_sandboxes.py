#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E1 答题沙箱构建器 v2 —— 一次跑完三个沙箱。

与上一版（2026-10-14 手工搭的沙箱）的区别:
  1. **构建器本身入库可复用** —— 上一版没有构建脚本, 三箱是手搓的, 无法一键重建,
     于是"三箱逐字节一致"这层保证只能靠事后比对, 出偏差也查不出是哪一步歪的;
  2. **净化粒度从"行级"升级为"区块级 + 行级"两级** —— 上一版把 README.md 的仓库
     文件树区块逐行替换成占位符, 结果是 1141 行里 815 行变成占位符(71%),
     文件从 1280 行膨胀到 1409 行且几乎不可读。文件树是**仓库级清单**, 不是
     skill 的工具文档, 正确做法是整段剥离, 而不是逐行打码;
  3. **修掉上一版 preflight 的计数 bug** —— 上一版 `progress` 排除了 RUN-INFO.md,
     `preflight` 却没排除, 于是长期报 29/28;
  4. **修掉上一版台账"未填"守卫被绕过的 bug** —— 旧守卫只认 `（填`, 占位符写成
     `（待填…` 就能静默通过。本版改用显式哨兵 `<!-- UNSET -->`;
  5. **新增硬锁 ACL** —— `skill/`、`题卷/` 拒绝 Everyone 写入与删除(可选, `--acl`)。

隔离口径（**说清能力边界，不吹**）:
  * 沙箱里**物理不含**任何答案(标注/金标准/历史跑批/判分脚本一律不拷贝) —— 这是主防线;
  * ACL 只能挡"误改/误删", **挡不住故意偷看**: 模型进程与执行会话通常是同一
    Windows 用户, 系统无法区分它俩。真正防偷看靠主防线 + 模型侧不挂载仓库读取能力。

用法:
    python _builder/build_sandboxes.py                    # 干跑: 只报计划, 不落盘
    python _builder/build_sandboxes.py --apply            # 构建三个沙箱
    python _builder/build_sandboxes.py --apply --force    # 已存在则先解封重建
    python _builder/build_sandboxes.py --apply --acl      # 额外上 ACL 硬锁
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
# 一、配置
# ══════════════════════════════════════════════════════════════════════════════

BOXES = ("sb1", "sb2", "sb3")
N_TASKS = 28

# 已知仓库根候选（沙箱在工作区之外，往上找不到，故显式登记）
KNOWN_REPO_CANDIDATES = (
    r"<USER_HOME>\OneDrive\桌面\AI-archive-pre-sinking-snapshot-20261010",
    r"<USER_HOME>\astro-best",
)

# 源（= 被测对象本体 + 它本该知道的工具面）。白名单制: 不在清单里的一律不进沙箱。
SRC_FILES = ("SKILL.md", "README.md", "manifest.yaml", "architecture.md")
SRC_DIRS = ("agents", "contracts", "static", "references", "src", "templates", "rag")

# 物理排除: 这些目录/后缀即使出现在白名单子树里也不拷
SKIP_DIR_NAMES = {"__pycache__", ".git", ".ipynb_checkpoints", "node_modules", ".pytest_cache"}
SKIP_SUFFIX = {".pyc", ".pyo", ".so", ".pyd", ".dll", ".exe", ".bin", ".zip", ".tar", ".gz"}

# 明确禁止进沙箱（答案与历史跑批产物）—— 构建器自身的硬断言
FORBIDDEN_TOKENS = (
    "tasks.yaml", "items.yaml", "rubric.yaml",
    "graders.py", "runner.py", "gen_golden.py", "normalizers.py",
    "live-2026-", "candidate-answers", "traces/golden",
)

PURGE_RULES = [
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
    # ── 判分侧（第二轮审计补）────────────────────────────────────────────
    # 上一版只覆盖了 E1 标注字段名，漏了"判分体系"这一类指针。实测在
    # skill/README.md 的评测层清单表里原样躺着：评分量规文件名、五维加权、
    # pass_score 0.9 > WARN 0.85、24 场景、六审计器；src/client_paging.py
    # 注释里还带了一句 `graders.py:274-276`（判分脚本名 + 行号）。
    # 这些都不是 E1 的答案，但属于 ALLOWED-FILES.md 里承诺"看不见"的
    # **判分逻辑**（判据 / 权重 / 通过线 / 红线）—— 承诺了就得兑现。
    (r"eval_runner\.py|graders?\.py|probes\.py|probe_support\.py|case_executor\.py",
     "判分脚本文件名"),
    (r"scoring[-_]?rubric|test-scenarios\.yaml", "评分量规/场景清单文件名"),
    (r"pass_score|WARN\s*0?\.85", "通过线/警戒线数值"),
    (r"评分量规|五维加权|加权评分|通过线|警戒线|红线判定", "评分口径"),
    (r"TemplatesAuditor|契约审计器|契约文本审计|文本审计", "评测审计器指针"),
    # `evals/` 带斜杠的写法老规则已覆盖；这里补"evals 目录 / 被 evals 审计"这类变体
    (r"\bevals\b", "评测层指针（各种写法）"),
]

# 区块级净化: 整段剥离（比逐行打码干净得多）
BLOCK_CUTS = {
    "README.md": [
        (r"^##\s+文件树 SSOT\s*$",
         "> [已剥离] 仓库级文件树清单整段移除 —— 它是仓库导航件，不是 skill 的工具文档，"
         "且内含评测目录与题号指针。"),
    ],
}

# 区间区块切割: [起始表头, 锚点行, 结束小节) 整段剥离
#
# 为什么需要它 —— README.md 的 `### contracts/` 小节里嵌了**第二张表**，
# 逐行登记评测层组件（eval_runner.py / probes.py / cases/ / audit/ ...）。
# 逐行打码救不了这种行：把 `eval_runner.py` 换成占位符，剩下的
# "评审执行器：24 场景真实探针 + 25 用例真实执行 + 六审计器 + 五维加权评分"
# 本身就是判分口径，照泄不误。整表砍掉才是干净解法。
#
# 匹配方式：先找锚点行（含判分脚本名），再向上吞掉紧邻的表格表头，
# 向下一直删到下一个 `###` 小节为止（不含）。
BLOCK_RANGE_CUTS = {
    "README.md": [
        {
            "header": r"^\|\s*文件\s*\|\s*能力边界\s*\|\s*治理规则\s*\|$",
            "anchor": r"^\|\s*`eval_runner\.py`\s*\|",
            "end": r"^###\s+",
            "note": "> [已剥离] 评测层组件清单整段移除 —— 它逐行登记判分脚本与"
                    "评分量规（含维度名、权重和、通过线），属判分逻辑，不应出现在模型可见面。",
        }
    ],
}

# 占位符按后缀选，保证结构化文件净化后仍能解析
PLACEHOLDER = {
    ".md":  "> [已净化] 本行原含评测/题号指针，已按沙箱隔离规则剥离",
    ".txt": "> [已净化] 本行原含评测/题号指针，已按沙箱隔离规则剥离",
    ".py":  "# [已净化] 本行原含评测/题号指针，已按沙箱隔离规则剥离",
    ".yaml": "# [已净化] 本行原含评测/题号指针，已按沙箱隔离规则剥离",
    ".yml": "# [已净化] 本行原含评测/题号指针，已按沙箱隔离规则剥离",
    ".json": "",
    ".cfg": "# [已净化] 本行原含评测/题号指针，已按沙箱隔离规则剥离",
    ".toml": "# [已净化] 本行原含评测/题号指针，已按沙箱隔离规则剥离",
    ".ini": "; [已净化] 本行原含评测/题号指针，已按沙箱隔离规则剥离",
}
DEFAULT_PLACEHOLDER = "# [已净化] 本行原含评测/题号指针，已按沙箱隔离规则剥离"

# 续接题上下文（题卷设计件；仓库 tasks.yaml 里没有 context 字段，故以此为准）
# 2026-10-18: 删掉 NL2T-09 的上下文。原文是「我关注的是 M31（仙女座星系）」，
#   题面却写「按名字查这颗星…的标准星记录」——指代落在一个星系上，而标注要求它
#   等价于一条标准星记录。实测模型点破「M31 不是恒星」后停手，被判 toolset 0.67。
#   改法：指代写进题面（具名恒星 Betelgeuse），上下文一并删掉。
PAPER_CONTEXT = {
    "NL2T-06": "[user] RA=180.0、Dec=30.0、半径 60″ 内有什么？",
    "NL2T-08": "[user] 查 RA=180.0、Dec=30.0、半径 60″ 内的 ps1 源。\n"
               "[tool_result] status.truncated = true, sqlid = s3898, "
               "returned_count = 1000, total_count = 5000",
    "NL2T-10": "[user] 查 RA=10.68、Dec=41.27、半径 60″ 内的 ps1 星。",
    "NL2T-12": "[user] 查 RA=180.0、Dec=30.0、半径 60″ 内的 ps1 星。",
}

SYSTEM_PROMPT_BODY = """你是 astro-best 天体测量助手。可用工具共 7 个，见《可用工具面》；
完整 schema 在沙箱 skill 目录里，需要时才查；一般不必翻。

本次为**离线决策评测**：不需要发起真实网络请求，也不需要 BEST 站点或 MCP 在线 ——
按你实际会发出的调用给出工具名与参数即可。

## 怎么说清楚（三条通用要求）

1. **做不到的事，就说“不支持 / 不提供”**，并给出理由与可走的替代路径。
   只说“拿不到”“给不了”而不点明不支持什么、为什么、还能做什么，读者无法据此决策。
2. **要请用户补充信息时，点明缺的是哪个维度**（天体标识 / 坐标 / 半径 / 星表 /
   波段 / 时间基准 / 语义口径），并给出候选让用户择一。不要只写“请补充信息”。
3. **参数的默认值只是兜底，不等于当前场景的合适值。** 取值前先判断目标的
   类型与尺度（点源 / 扩展源 / 天区范围），再决定单位与数量级。

## 输出格式

一、调用轨迹：按先后顺序列出工具名与参数；不调用就写「无」；
二、给用户的回答：你真正要回复用户的话（澄清、拒绝、替代路径都写在这里）。

不要输出分析过程，不要引用其他题目。"""


# ══════════════════════════════════════════════════════════════════════════════
# 二、工具函数
# ══════════════════════════════════════════════════════════════════════════════

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(p: Path, root: Path) -> str:
    return str(p.relative_to(root)).replace("\\", "/")


relp = rel


def walk(root: Path):
    """遍历沙箱（排除 VCS / 缓存目录）。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in {".git", "__pycache__", ".ipynb_checkpoints"}]
        for name in filenames:
            yield Path(dirpath) / name


def ph_for(suffix: str) -> str:
    return PLACEHOLDER.get(suffix.lower(), DEFAULT_PLACEHOLDER)


# 净化模式: 散文类整行替换; 结构化/代码类改成片段级红改(整行替换会打碎多行标量)
INLINE_SUFFIX = {".yaml", ".yml", ".json", ".py", ".toml", ".ini", ".cfg"}
INLINE_MARK = "[已净化]"
# 这些后缀里 `xxx: v` 是映射键值；直接把键替换成裸 `[已净化]` 会得到
# `weights: {tests: 3, [已净化]: 3}` —— 不可哈希键，YAML/JSON 当场解析失败。
# 处于键位时补引号，值仍然是合法字符串键。（构建期断言实测抓到的。）
KEY_QUOTE_SUFFIX = {".yaml", ".yml", ".json", ".toml", ".ini", ".cfg"}

# _lock 的运行时产物（每次跑都会重写），不进任何哈希比对
LOCK_RUNTIME = {
    "verify_report.md", "preflight_report.md", "progress_report.md",
    "ANSWERS.sha256", "lock.log",
}


def purify_text(text: str, suffix: str) -> tuple[str, list[tuple[int, str, str]]]:
    """两级净化。返回 (净化后文本, [(行号, 命中正则, 原因), ...])。

    为什么结构化文件不能用整行替换 —— 构建期实测: contracts/pipeline-stage.contract.yaml
    里命中的行是一个**多行块标量的续行**, 整行换成注释后 YAML 直接解析失败
    ("expected <block end>, but found <scalar>")。上一版只抽样验了 3 个结构化文件,
    漏掉了这个文件 —— 于是"净化后仍可解析"这件事当时并没真正被保证。
    """
    lines = text.split("\n")
    hits: list[tuple[int, str, str]] = []
    ph = ph_for(suffix)
    inline = suffix.lower() in INLINE_SUFFIX
    out: list[str] = []
    for i, line in enumerate(lines, 1):
        # 同一行要过**全部**规则，不是命中第一条就收工。
        #
        # 实测翻车: src/crossmatch_jobs.py:19 原文是 `evals/probes.py`, 老逻辑
        # 先命中 `evals/` 就 break, 于是 `probes.py` 原样留下 —— 前缀挡住了
        # 后缀, 一条规则把另一条规则"遮"住了。这种遮挡关系在规则变多之后
        # 只会更常见, 所以这里改成逐条过、累加红改。
        bad = None
        cur = line
        line_hits: list[tuple[str, str]] = []
        for pat, why in PURGE_RULES:
            if re.search(pat, cur):
                line_hits.append((pat, why))
                quote_keys = suffix.lower() in KEY_QUOTE_SUFFIX
                cur = re.sub(
                    pat,
                    # 处于 `key: value` 的键位时补引号，避免产出不可哈希键
                    (lambda m, _c=cur: '"%s"' % INLINE_MARK
                     if quote_keys and _c[m.end():m.end() + 2].lstrip().startswith(":")
                     else INLINE_MARK),
                    cur)
        if not line_hits:
            out.append(line)
            continue
        for pat, why in line_hits:
            hits.append((i, pat, why))
        # 片段级红改为默认；只有"改完就剩个空骨架"的行才整行占位。
        #
        # 为什么改掉原来的"散文一律整行替换" —— 实测 static/core/stance.md 第 2 行
        # 是 344 字的立场声明，只在括号里顺带提了一句 "全仓只见于 agents/docs/evals
        # 的散文与判定词表"。整行换掉 = 把一条真实有用的立场要求一起删了，
        # 属于净化过头。片段级红改只吃掉 `evals` 四个字母，正文照留。
        # 同一行被多条规则命中时，把连续重复的占位符合并成一个，免得
        # `[已净化][已净化]` 这种双拼。
        redacted = re.sub(r"(\[已净化\][ \t]*){2,}", INLINE_MARK, cur)
        rest = re.sub(r"[\s\-|`#>*·•（）()【】\[\]，。、；：,.;:\"']+", "",
                      redacted.replace(INLINE_MARK, ""))
        if inline or len(rest) >= 12:
            out.append(redacted)
        else:
            out.append(ph)
    return "\n".join(out), hits


def apply_block_cuts(rel: str, text: str) -> tuple[str, list[str]]:
    """区块级剥离: 命中起始行 -> 到文件末尾整段砍掉。返回 (文本, [说明])。"""
    cuts = BLOCK_CUTS.get(rel)
    if not cuts:
        return text, []
    lines = text.split("\n")
    notes: list[str] = []
    for pat, note in cuts:
        idx = None
        for i, line in enumerate(lines):
            if re.match(pat, line.rstrip()):
                idx = i
                break
        if idx is None:
            notes.append(f"[未命中] 区块规则 /{pat}/ 在 {rel} 里没找到起始行（规则需复核）")
            continue
        lines = lines[:idx] + [note, ""]
        notes.append(f"{rel}: 自第 {idx + 1} 行起整段剥离（{note[:24]}…）")
    return "\n".join(lines), notes


def apply_range_cuts(rel: str, text: str) -> tuple[str, list[str]]:
    """区间区块剥离：把 [表头, 下一个 ###) 之间的一整张表砍掉。"""
    rules = BLOCK_RANGE_CUTS.get(rel)
    if not rules:
        return text, []
    lines = text.split("\n")
    notes: list[str] = []
    for r in rules:
        hdr = re.compile(r["header"])
        anc = re.compile(r["anchor"])
        end = re.compile(r["end"])
        a = next((i for i, l in enumerate(lines) if anc.match(l)), None)
        if a is None:
            notes.append(f"[未命中] 区间规则的锚点 /{r['anchor']}/ 在 {rel} 里没找到（规则需复核）")
            continue
        # 向上吞掉紧邻的表格表头（中间允许空行 / 分隔行）
        h = a
        while h - 1 >= 0 and not hdr.match(lines[h - 1]):
            if lines[h - 1].strip() in ("", "|"):
                h -= 1
                continue
            if re.match(r"^\|[\s:|-]+\|$", lines[h - 1]):
                h -= 1
                continue
            break
        if h - 1 >= 0 and hdr.match(lines[h - 1]):
            h -= 1
        e = next((i for i in range(a + 1, len(lines)) if end.match(lines[i])), len(lines))
        notes.append(f"{rel}: 第 {h + 1}~{e} 行整表剥离（评测层组件清单）")
        lines = lines[:h] + [r["note"], ""] + lines[e:]
    return "\n".join(lines), notes


def collect_sources(repo: Path) -> list[tuple[str, Path]]:
    """按白名单收集 (相对路径, 绝对路径)。"""
    found: list[tuple[str, Path]] = []
    for name in SRC_FILES:
        p = repo / name
        if p.is_file():
            found.append((name, p))
    for d in SRC_DIRS:
        base = repo / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in p.parts):
                continue
            if p.suffix.lower() in SKIP_SUFFIX:
                continue
            found.append((str(p.relative_to(repo)).replace("\\", "/"), p))
    return sorted(set(found))


# ══════════════════════════════════════════════════════════════════════════════
# 三、题卷生成（唯一真源 = tasks.yaml 的 utterance）
# ══════════════════════════════════════════════════════════════════════════════

def load_tasks(tasks_yaml: Path) -> list[dict]:
    import yaml  # 仅构建期需要；锁脚本保持纯标准库
    data = yaml.safe_load(tasks_yaml.read_text(encoding="utf-8"))
    tasks = data["tasks"]
    ids = [t["id"] for t in tasks]
    assert len(tasks) == N_TASKS, f"任务数 {len(tasks)} != {N_TASKS}"
    assert len(set(ids)) == N_TASKS, "题号有重复"
    assert ids == [f"NL2T-{i:02d}" for i in range(1, N_TASKS + 1)], f"题号不连续: {ids}"
    for t in tasks:
        assert t.get("utterance"), f"{t['id']} 缺 utterance"
    return tasks


def build_toolface(repo: Path) -> str:
    """从 references/tools.schema.json 现生成工具面 —— 不再手抄（旧版手抄件已漂移：
    旧 TOOLFACE.md 写 `radius_arcsec` 缺省 180 角秒，而新版 schema 已无此默认值）。"""
    schema = json.loads((repo / "references/tools.schema.json").read_text(encoding="utf-8"))
    tools = schema["tools"]
    schema_hash = sha256_file(repo / "references/tools.schema.json")[:16]

    L = [
        "# 可用工具面（7 个原子工具）",
        "",
        "> 本件是**工具导航表**：只讲“有哪些工具、各要什么参数”。",
        "> 完整定义（含返回信封、错误码、量纲说明）在 `skill/references/tools.schema.json`。",
        "> **哪句话该用哪个工具、传什么值 —— 本件不提示，那是本次要评的东西。**",
        "",
        f"> 生成依据：`references/tools.schema.json` @ `{schema_hash}`",
        "",
        "## 一览",
        "",
        "| 工具 | 一句话职责 |",
        "|------|-----------|",
    ]
    for t in tools:
        desc = (t.get("title") or t.get("description") or "").strip()
        L.append(f"| `{t['name']}` | {desc} |")
    L.append("")

    for t in tools:
        isch = t.get("inputSchema", {}) or {}
        props = isch.get("properties", {}) or {}
        required = isch.get("required", []) or []
        L.append(f"### `{t['name']}`")
        L.append("")
        desc = (t.get("description") or t.get("title") or "").strip()
        if desc:
            L.append(f"- 说明：{desc}")
            L.append("")
        if not props:
            L.append("无参数。")
            L.append("")
        else:
            L.append("| 参数 | 类型 | 必填 | 说明 |")
            L.append("|------|------|------|------|")
            for k, v in props.items():
                typ = v.get("type", "-")
                req = "是" if k in required else "否"
                bits = []
                d = v.get("description")
                if d:
                    bits.append(str(d))
                if "default" in v:
                    bits.append(f"缺省 `{v['default']}`")
                note = "；".join(bits) if bits else "—"
                note = note.replace("\n", " ")
                L.append(f"| `{k}` | {typ} | {req} | {note} |")
            L.append("")
    L.append("> 参数以外的 schema 细节（返回信封、错误码、量纲）见 `skill/references/tools.schema.json`。")
    L.append("")
    return "\n".join(L)


# ══════════════════════════════════════════════════════════════════════════════
# 四、沙箱文本件（规则 / 白名单 / 执行包 / 台账）
# ══════════════════════════════════════════════════════════════════════════════

def sandbox_rules(box: str) -> str:
    # 注意: 本件在三个沙箱里内容相同, 因此**不写彼此的名字**(写出即触发越界闸)
    return f"""# 答题规则（本沙箱 `{box}`）· 四条硬性规矩

> 一句话：**你就是被测对象**。这个沙箱就是实验环境，不需要任何外部接口。

## 一、四条硬规矩（破一条即该批作废）

1. **一次只复制一个题块，一题一个新会话**。整份粘进同一会话 = 串题污染
   （前面某题教会模型某个知识点，后面某题顺势答对 —— 那分是抄的，不是能力）。
2. **不向模型复述答案、不提示路由**。“再想想”“注意单位”“是否要澄清”都算引导。
3. **被测模型侧不得挂载**仓库文件读取 / grep / 检索能力 —— 否则禁看清单形同虚设
   （一个 grep 就能读到标注）。
4. **不读沙箱外任何路径**，**不读 `_exec/`**（那是 28 题一册的索引件，
   一次看全就是串题）；只写 `answers/`。
   > 关于 `_exec/题包/`：**题包是执行会话逐题粘给你的**，你收到的是一份文本，
   > 不是让你去翻目录。所以"不读 `_exec/`"照旧成立 —— 你只拿到当前这一题的包，
   > 拿到手的这份里什么都有，**不需要**再去别处找。

## 二、离线评测口径（别把它当故障）

- 本次**离线判决策**：不需要真连站点、不需要 BEST/MCP 在线、不需要装任何依赖；
- 按“你实际会发出的调用”给出工具名与参数即可；
- 沙箱里**本来就没有**标准答案、标注、历史跑批、判分脚本 —— 找也找不到，不用找。

## 三、可以看 / 不可以看

**可以看（模型可见面）**：
`SKILL.md`、`SANDBOX-RULES.md`、`ALLOWED-FILES.md`、
`skill/`（被测对象本体与工具文档）、`answers/`（唯一可写）、
`题卷/TOOLFACE.md`（工具面）、`题卷/system_prompt.txt`（本次 system prompt）

**不可以看**：`_exec/`、`题卷/per_task/`、`题卷/context/`、沙箱外任何路径、另外两个沙箱；
`_lock/` 里除 `sandbox_lock.py`、`check_answer.py`（供你跑自检）之外的任何文件。

> `_exec/` 整目录不给你 —— 里面是 28 题一册的索引件，一次看全就是串题。
> 唯一例外是 `_exec/题包/<当前题号>.md`，它由执行会话**单独**取出来交给你，
> 一次一份。你不需要、也不应该自己去列这个目录。
>
> `题卷/per_task/` 与 `题卷/context/` 同理：那是 28 条题面加 4 条续接上下文的原件，
> 也已在文件系统层面对你关闭。**当前这一题的题面在题包里，已经给你了，不用去找。**

## 四、输出格式（两段式，照 `answers/_答题模板.md`）

1. **调用轨迹**：按先后顺序列出工具名与参数；不调用就写「无」；
2. **给用户的回答**：你真正要回复用户的话（澄清、拒绝、替代路径都写在这里）。

参数写成**标准 JSON**（`{{"ra": 10.68}}`，带引号），别写 `{{ra: 10.68}}`。
不要输出分析过程，不要引用其他题目。

## 五、自检

```bash
python _lock/sandbox_lock.py preflight     # 应为「可以开始」(硬阻塞 0)
python _lock/sandbox_lock.py progress      # 收尾时应为 28/28
python _lock/sandbox_lock.py verify        # 收尾时应为 PASS
python _lock/check_answer.py NL2T-<题号>   # 单题格式自检
```
"""


def allowed_files(n_files: int, n_lines: int, rel_list: list[str]) -> str:
    grouped: dict[str, list[str]] = {}
    for r in rel_list:
        top = r.split("/")[0] if "/" in r else "(根目录文件)"
        grouped.setdefault(top, []).append(r)
    L = [
        "# 白名单：模型能看到的全部文件",
        "",
        "> 白名单制：不在本清单里的东西，沙箱里**物理上不存在**。",
        f"> 本次构建：复制 **{n_files}** 个文件，行级净化 **{n_lines}** 行。",
        "",
        "## 一、可以看",
        "",
    ]
    for top in sorted(grouped):
        L.append(f"### `{top}`")
        L.append("")
        for r in grouped[top]:
            L.append(f"- `{r}`")
        L.append("")
    L += [
        "### `题卷/`（工具面与 system prompt）",
        "",
        "- `题卷/TOOLFACE.md` —— 7 个原子工具的工具面",
        "- `题卷/system_prompt.txt` —— 本次 system prompt",
        "",
        "> `题卷/per_task/`（28 条题面）与 `题卷/context/`（4 条续接上下文）**已对模型关闭**：",
        "> 一次读全 28 题就是串题。题面从下一节的题包里取。",
        "",
        "### `_exec/题包/`（自包含题包 · 按题投喂）",
        "",
        "- `_exec/题包/<题号>.md` —— system prompt + 工具面 + 上下文 + 题面，四合一",
        "",
        "> **一次只取一份，且目录本身对模型拒绝读取。** 题包由执行会话逐题取出后",
        "> 以文本形式交给模型 —— 模型拿到的是一份内容，不是一条路径。",
        "> `_exec/` 的其余部分（28 题一册的索引件）一律不给 —— 一次看全就是串题。",
        "",
        "### `answers/`（唯一可写）",
        "",
        "- `answers/NL2T-<题号>.md` —— 你的作答",
        "- `answers/_答题模板.md` —— 两段式模板",
        "- `answers/RUN-INFO.md` —— 批次台账",
        "",
        "## 二、看不见（物理不存在）",
        "",
        "| 类别 | 说明 |",
        "|------|------|",
        "| 标注 | 期望工具序列 / 错法清单 / 澄清探测词 / 拒绝理由码 |",
        "| 金标准轨迹 | 按标注合成的满分轨迹 |",
        "| 历史跑批 | 上一批模型的真实回答与判定 |",
        "| 判分逻辑 | 判据、权重、通过线、红线 |",
        "| 仓库其他目录 | 评测目录 / 文档 / 示例 / 运维 / 测试 |",
        "",
        "## 三、净化口径（两级）",
        "",
        "1. **区块级**：仓库级文件树清单整段剥离（它是导航件，不是工具文档）；",
        "2. **行级**：其余命中行整行替换为占位符。被剥离的三类：",
        "   - 题号（答案定位器）",
        "   - 评测目录指针",
        "   - 标注字段名",
        "",
        "> 占位符按文件后缀选取（`.yaml`/`.py` 用 `#`，`.md` 用 `>`），",
        "> 以保证结构化文件净化后**仍能解析** —— 这条已纳入构建期断言。",
        "",
    ]
    return "\n".join(L)


def exec_notice() -> str:
    return """# 跑批执行须知（给**执行会话**，不是给模型的）

> 一句话：**你就是被测对象**。这个沙箱就是实验环境，不需要任何外部接口。

## 一、四条曾经把人拦住的误判（实测踩过，逐条给出结论）

| 误判 | 结论 |
|------|------|
| “当前环境没有可调用的 astro-best 工具接口” | **不是阻塞项**。本评测离线判**决策**：按“你实际会发出的调用”写工具名与参数即可。工具面见 `题卷/TOOLFACE.md` |
| “astro-best MCP 起不来 / Python 缺 requests” | **不用起**。判分不依赖站点、不依赖 MCP、不依赖任何 pip 依赖 |
| “`题卷/system_prompt.txt` 只有注释，没有 prompt” | 已预填一份**最小可用版**；要换就整份替换，并把版本标识填进 `answers/RUN-INFO.md` |
| “`RUN-INFO.md` 没填，所以不能开始” | **不阻断**。`preflight` 只提醒不拦；但填了该批才能与别的批次横比 |

## 二、五步走

```bash
python _lock/sandbox_lock.py preflight     # 1. 应为「可以开始」(硬阻塞 0)
```

2. 读 `题卷/system_prompt.txt` —— 这就是本次 system prompt；
3. 逐题作答：读 `题卷/per_task/<题号>.txt`；若 `题卷/context/<题号>.txt` 存在，
   **先发 context 再发题面**（那是续接题的上文）。**一题一个新会话**；
4. 每题把结果写进 `answers/<题号>.md`（照 `_答题模板.md` 的两段式）；
5. 收尾：

```bash
python _lock/sandbox_lock.py progress      # 应为 28/28
python _lock/sandbox_lock.py verify        # 应为 PASS
```

## 三、破一条即该批作废的四条硬规矩

- **一题一个新会话**；不向模型复述答案、不提示路由；
- **不要读 `_exec/`**（那是 28 题一册的索引件，一次看全就是串题）**，不要读沙箱外任何路径**；
- **只写 `answers/`**，`skill/` 与 `题卷/` 是只读的；
- 沙箱里**本来就没有**标准答案、标注、历史跑批、判分脚本 —— 找也找不到，不用找。

## 四、本沙箱是三份副本之一，必须同一次构建产出

三份副本是同一次实验的三次重复，题面、上下文、工具面**逐字节一致**
（用 `_builder/verify_all.py` 复核）。**只重建一箱就会破坏这层保证** ——
要重建就三箱一起重建（构建器一次跑完三个）。

> 规矩：本件在三个沙箱里内容**完全相同**，因此**不写彼此的名字**（写出即触发越界闸）。
"""


def tasks_md(tasks: list[dict]) -> str:
    L = [
        "# E1 跑批题卷（TASKS.md）",
        "",
        "> **生成件，勿手改** —— 由构建器从标注文件的 utterance 字段单向提取；",
        "> 本件**只含题面**，不含任何答案（期望工具、错法清单、澄清选项、拒绝理由一律不在此）。",
        "",
        "## 一、三条硬规矩（做不到则该批分数作废）",
        "",
        "1. **一次只复制一个题块，一题一个新会话**。整份粘进同一会话 = 串题污染。",
        "2. **不向模型复述答案、不提示路由**。“再想想”“注意单位”“是否要澄清”都算引导。",
        "3. **被测模型侧不得挂载**仓库文件读取 / grep / 检索能力。",
        "",
        "## 二、题面（28 条，一次只取一段）",
        "",
    ]
    for t in tasks:
        tid = t["id"]
        L.append(f"### {tid}")
        L.append("")
        if tid in PAPER_CONTEXT:
            L.append("**① 上下文前缀**（先发这段，再发 ②）：")
            L.append("")
            L.append("```")
            L.append(PAPER_CONTEXT[tid])
            L.append("```")
            L.append("")
            L.append("**② 用户原话**：")
        else:
            L.append("**用户原话**（只复制这一行）：")
        L.append("")
        L.append(f"> {t['utterance']}")
        L.append("")
    return "\n".join(L)


def prompts_jsonl(tasks: list[dict]) -> str:
    out = []
    for t in tasks:
        tid = t["id"]
        rec = {
            "task_id": tid,
            "context": PAPER_CONTEXT.get(tid, ""),
            "utterance": t["utterance"],
            "answer_path": f"answers/{tid}.md",
        }
        out.append(json.dumps(rec, ensure_ascii=False))
    return "\n".join(out) + "\n"


def packet_md(tid: str, utterance: str, context: str, toolface: str, sysprompt: str) -> str:
    ctx_block = context if context else "（无 —— 本题是独立提问，没有上文）"
    return f"""# 题包 {tid} ｜ 自包含，读完直接作答

> 本文件已包含作答所需的**全部**内容：system prompt、可用工具、上下文、题面。
> **不需要**再去读沙箱里的其他文件。`skill/` 只在你确实要查工具细节时才翻。
> 答完写到 `answers/{tid}.md`。

---

## 一、system prompt

```
{sysprompt}
```

## 二、可用工具（7 个）

{toolface}

## 三、上下文（用户此前说过的话）

{ctx_block}

## 四、题面（用户原话）

> {utterance}

---

## 五、你要输出的（写到 `answers/{tid}.md`）

**三条硬性要求**（实跑踩出来的坑，每一条都会让分数失真）：

1. **首行写 `# {tid}`** —— 自证题号。有批次把某题的答案存进了另一题的文件，
   判分按文件名取题号，全判 0；
2. **参数写成标准 JSON** —— `{{"ra": 10.68}}`，别写 `{{ra: 10.68}}`（key 缺引号不是合法 JSON，
   会被当成空参数，param 维掉到 0.1）；
3. **给用户的话全部写在第二节** —— 判分器只读「给用户的回答」段，
   “不支持”“需要先确认”写在调用轨迹段里等于没说。

```markdown
# {tid}

## 一、调用轨迹

1. 工具名  参数: {{"key": "value"}}

（一个工具都不调就写：`无`）

## 二、给用户的回答

（你真正要回复用户的话，正文原文；要澄清或不支持，都写在这里）
```

**不要写分析过程，不要引用其他题目。**

> **（以下两行是给执行会话的，不是给模型的）**
> 收回答后跑：`python _lock/check_answer.py {tid}`

**口径**：本次为离线决策评测 —— 不需要真连站点、不需要 BEST/MCP 在线、不需要装任何依赖。
按“你实际会发出的调用”给出工具名与参数即可。
"""


def run_info_template(box: str) -> str:
    return f"""# 批次台账（RUN-INFO.md）· **唯一可写的元信息文件**

> 开跑前填五栏。不填也能跑，但**该批与别的批次不可横比** —— 事后无法追认。
> `<!-- UNSET -->` 是未填哨兵；填了请把整行连同哨兵一起替换掉，**别只删哨兵**。

## ⚠️ `model_id` 三箱必须**逐字相同**（这条最容易悄无声息地废掉整个实验）

三个沙箱是**同一个模型的三次重复**。只要 `model_id` 有任何字面差异 ——
大小写、多一个空格、多了个括号后缀（如 `WorkBuddy AI (DeepSeek-V3.2)`）——
判分侧分组时就会把它当成**三个不同模型**，三次重复退化成单次，
**方差算不出来，横比直接失效**。这是上一版实测踩出来的（G4）。

> **别手打。填好第一箱之后，从那箱复制粘贴到另外两箱。**
> 手打必然出现大小写/空格漂移，而且你当场看不出来。

| 字段 | 值 |
|------|-----|
| run_id | <!-- UNSET --> 例：2026-10-17-{box}-r1（**三箱必须各不相同**） |
| model_id | <!-- UNSET --> 例：gpt-5.1 / claude-sonnet-4.5 / deepseek-v3.2（**三箱必须逐字相同**） |
| system_prompt_version | <!-- UNSET --> 例：最小版 v2；若整份替换过 prompt 请写明来源 |
| started_at | <!-- UNSET --> 例：2026-10-17T21:00 |
| operator | <!-- UNSET --> 例：user |

## 填写说明

- `run_id` 三箱**各不相同**（沙箱名 + 轮次），要能靠它把三次重复区分开；
- `model_id` 三箱**逐字相同**；写清厂商与版本，别写“大模型”这种没法复核的词；
- `system_prompt_version` 若沿用沙箱预填的那份，写「沙箱预填最小版」即可；
- 收尾时 `verify` 会把本件是否填写纳入提醒（只提醒，不阻断）。

## 自检（收尾前逐条打勾）

- [ ] `model_id` 是从第一箱**复制粘贴**来的，不是手打
- [ ] `run_id` 三箱互不相同
- [ ] 一题一个新会话，未引导、未复述答案
- [ ] 收尾跑过 `python _lock/sandbox_lock.py progress`（28/28）
- [ ] 收尾跑过 `python _lock/sandbox_lock.py verify`（PASS）
- [ ] 三箱跑完后，在沙箱根跑过 `python _builder/compare_boxes.py`（台账三箱一致）

## 纪律

- 一题一个新会话；不向模型复述答案、不提示路由；
- 只写本目录下的 `NL2T-<题号>.md`；`skill/` 与 `题卷/` 只读。
"""


def answer_template() -> str:
    return """# NL2T-<题号>

## 一、调用轨迹

1. 工具名  参数: {"key": "value"}

（一个工具都不调就写：`无`）

## 二、给用户的回答

（你真正要回复用户的话，正文原文；要澄清或不支持，都写在这里）
"""


# ══════════════════════════════════════════════════════════════════════════════
# 五、构建单个沙箱
# ══════════════════════════════════════════════════════════════════════════════

def write(path: Path, text: str, apply: bool, log: list[str]) -> None:
    if apply:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    log.append(f"write {path}")


def build_box(box: str, dest: Path, sources: list[tuple[str, Path]], tasks: list[dict],
              toolface: str, sysprompt_body: str, apply: bool,
              log: list[str]) -> tuple[int, int, list[str]]:
    """返回 (复制文件数, 净化行数, 问题列表)。"""
    root = dest / box
    purge_log: list[str] = []
    problems: list[str] = []

    if apply and root.exists():
        # 若上一轮已上 ACL 硬锁, 先解封再重建
        unseal_box(root)
        shutil.rmtree(root)

    n_files = 0
    n_lines = 0
    rel_list: list[str] = []

    for rel, src in sources:
        try:
            text = src.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(f"[跳过] 非 UTF-8 文本: {rel}")
            continue
        suffix = src.suffix.lower()

        # 第一级: 区块级剥离（整表 / 整段）
        if BLOCK_RANGE_CUTS.get(rel):
            text, notes = apply_range_cuts(rel, text)
            for n in notes:
                purge_log.append(f"# {rel} · {n}")
                if n.startswith("[未命中]"):
                    problems.append(f"{rel}: {n}")
        if BLOCK_CUTS.get(rel):
            text, notes = apply_block_cuts(rel, text)
            for n in notes:
                purge_log.append(f"# {rel} · {n}")
                if n.startswith("[未命中]"):
                    problems.append(f"{rel}: {n}")

        # 第二级: 行级净化
        text, hits = purify_text(text, suffix)

        # 构建期断言: 结构化文件净化后必须仍可解析
        if suffix in (".json", ".yaml", ".yml") and hits:
            ok, err = validate_structured(text, suffix)
            if not ok:
                problems.append(f"[致命] {rel} 净化后无法解析: {err}")

        if hits:
            for ln, pat, why in hits:
                purge_log.append(f"{sha256_bytes(text.encode())[:8]}  {rel}:{ln}  /{pat}/  {why}")
            n_lines += len(hits)

        write(root / "skill" / rel, text, apply, log)
        rel_list.append(rel)
        n_files += 1

    # ── 题卷 ──────────────────────────────────────────────────────────────────
    # papers 既用于落盘也用于算指纹 —— 同源才能比得动（否则"多一个尾换行"会误报篡改）。
    papers: list[tuple[str, str]] = [
        ("TOOLFACE.md", toolface),
        ("system_prompt.txt", sysprompt_body),
    ]
    for t in tasks:
        papers.append((f"per_task/{t['id']}.txt", t["utterance"] + "\n"))
    for tid, ctx in PAPER_CONTEXT.items():
        papers.append((f"context/{tid}.txt", ctx + "\n"))
    for relpath, content in papers:
        write(root / "题卷" / relpath, content, apply, log)

    # ── 执行包（执行会话专用；不得挂给模型）───────────────────────────────────
    write(root / "_exec" / "TASKS.md", tasks_md(tasks), apply, log)
    write(root / "_exec" / "prompts.jsonl", prompts_jsonl(tasks), apply, log)
    write(root / "_exec" / "跑批执行须知.md", exec_notice(), apply, log)
    for t in tasks:
        tid = t["id"]
        write(root / "_exec" / "题包" / f"{tid}.md",
              packet_md(tid, t["utterance"], PAPER_CONTEXT.get(tid, ""),
                        toolface, sysprompt_body), apply, log)

    # ── 答案区（唯一可写）──────────────────────────────────────────────────
    write(root / "answers" / "_答题模板.md", answer_template(), apply, log)
    write(root / "answers" / "RUN-INFO.md", run_info_template(box), apply, log)

    # ── 规则件 ───────────────────────────────────────────────────────────────
    write(root / "SANDBOX-RULES.md", sandbox_rules(box), apply, log)
    write(root / "ALLOWED-FILES.md",
          allowed_files(n_files, n_lines, rel_list), apply, log)

    # ── 锁 ───────────────────────────────────────────────────────────────────
    lock_src, check_src = load_assets()
    write(root / "_lock" / "sandbox_lock.py", lock_src, apply, log)
    write(root / "_lock" / "check_answer.py", check_src, apply, log)
    write(root / "_lock" / "净化日志.txt",
          "# 行级净化日志 · 格式: <sha256前8位>  <路径>:<行号>  /<命中正则>/  <原因>\n"
          + "\n".join(purge_log) + "\n", apply, log)

    # ── 题卷指纹（防篡改; 题面不是答案，存哈希不泄题）──────────────────────────
    fp = [f"{sha256_bytes(content.encode())}  {relpath}" for relpath, content in papers]
    write(root / "_lock" / "PAPERS.sha256",
          "# 题卷指纹: 题面与工具面逐条 sha256; 被改动即判红\n" + "\n".join(sorted(fp)) + "\n",
          apply, log)

    # ── 构建期基线 ───────────────────────────────────────────────────────────
    # MANIFEST 是**封印时**重算的, 挡不住"先篡改再重新封印"这一手。
    # BASELINE 只在构建时生成一次，seal 不动它 —— 于是任何偏离本次构建产物的状态都能被发现。
    base = []
    if apply:
        for p in sorted(walk(root)):
            r = relp(p, root)
            top = r.split("/")[0]
            if top in {"answers"}:
                continue
            if top == "_lock" and (p.name in LOCK_RUNTIME or p.name == "MANIFEST.sha256"):
                continue
            base.append(f"{sha256_bytes(p.read_bytes())}  {r}")
    write(root / "_lock" / "BASELINE.sha256",
          "# 构建期基线: 本次构建产物的逐文件 sha256; seal 不会重算它\n"
          + "\n".join(base) + "\n", apply, log)

    return n_files, n_lines, problems


def validate_structured(text: str, suffix: str) -> tuple[bool, str]:
    if suffix == ".json":
        try:
            json.loads(text)
            return True, ""
        except Exception as e:
            return False, str(e)
    try:
        import yaml
        list(yaml.safe_load_all(text))
        return True, ""
    except Exception as e:
        return False, str(e)


def unseal_box(root: Path) -> None:
    """解除只读与 ACL 硬锁（重建前必须调用）。"""
    if sys.platform.startswith("win"):
        for d in ("skill", "题卷"):
            p = root / d
            if p.exists():
                subprocess.run(["icacls", str(p), "/remove:d", "Everyone", "/T"],
                               capture_output=True)
        for path in sorted(root.rglob("*")):
            subprocess.run(["attrib", "-R", str(path)], capture_output=True)
    else:
        for path in sorted(root.rglob("*")):
            try:
                if path.is_dir():
                    path.chmod(0o755)
                else:
                    path.chmod(0o644)
            except OSError:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# 六、入口
# ══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(description="E1 答题沙箱构建器 v2")
    ap.add_argument("--repo", default=None, help="skill 包仓库根（含 evals/nl2tool/tasks.yaml）")
    ap.add_argument("--dest", default=None, help="沙箱根（缺省=本脚本上级目录）")
    ap.add_argument("--apply", action="store_true", help="真正落盘（缺省干跑）")
    ap.add_argument("--force", action="store_true", help="目标已存在则先解封重建")
    ap.add_argument("--acl", action="store_true", help="额外上 ACL 硬锁（拒绝 Everyone 写入/删除）")
    ns = ap.parse_args()

    here = Path(__file__).resolve().parent
    dest = Path(ns.dest).resolve() if ns.dest else here.parent
    repo = Path(ns.repo).resolve() if ns.repo else detect_repo()

    print(f"[build] 源仓库: {repo}")
    print(f"[build] 沙箱根: {dest}")
    print(f"[build] 模式:   {'落盘' if ns.apply else '干跑'}"
          + (" · ACL 硬锁" if ns.acl else ""))
    print()

    tasks_yaml = repo / "evals" / "nl2tool" / "tasks.yaml"
    if not tasks_yaml.exists():
        print(f"[error] 找不到标注文件: {tasks_yaml}")
        return 2

    tasks = load_tasks(tasks_yaml)
    print(f"[build] 题面: {len(tasks)} 条 "
          f"({tasks[0]['id']} … {tasks[-1]['id']})，含上下文 {len(PAPER_CONTEXT)} 条")

    sources = collect_sources(repo)
    print(f"[build] 白名单文件: {len(sources)} 个")
    print()

    toolface = build_toolface(repo)
    sysprompt_body = build_system_prompt(repo)

    total_files = total_lines = 0
    all_problems: list[str] = []
    for box in BOXES:
        log: list[str] = []
        nf, nl, probs = build_box(box, dest, sources, tasks, toolface,
                                  sysprompt_body, ns.apply, log)
        total_files += nf
        total_lines += nl
        all_problems += [f"{box}: {p}" for p in probs]
        print(f"[build] {box}: 复制 {nf} 文件 · 行级净化 {nl} 行")

    print()
    print(f"[build] 合计: 复制 {total_files} 文件 · 行级净化 {total_lines} 行")

    if all_problems:
        print()
        print(f"[build] 问题 {len(all_problems)} 条：")
        for p in all_problems[:20]:
            print("   " + p)
        return 1

    if ns.apply:
        # 构建完直接上锁，不再"提示用户自己去跑"。
        #
        # 为什么改 —— 上一版这里只是一句 print("（--acl 已在 seal 时一并施加）"),
        # 但构建器**压根不调用 seal**: 它只是把文件写下去就收工。于是 `--acl`
        # 是个空头承诺 —— 打印说"已施加", 实际三箱的 icacls 里一条 deny 都没有。
        # 实测捅破: 拿 PowerShell 读 ACL, skill/ 与 题卷/ 上根本没有 Everyone deny 条目。
        # 这种"文档说有、实际没有"比明说没有危险得多, 所以这里改成真跑。
        print()
        ok_all = True
        for box in BOXES:
            lock = dest / box / "_lock" / "sandbox_lock.py"
            if not lock.exists():
                print(f"[seal] ✗ {box}: 找不到锁脚本 {lock}")
                ok_all = False
                continue
            cmd = [sys.executable, str(lock), "seal", "--root", str(dest / box)]
            if ns.acl:
                cmd.append("--acl")
            r = subprocess.run(cmd, capture_output=True)
            out = r.stdout.decode("utf-8", "ignore").strip().replace("\r", "")
            tail = out.splitlines()[-1] if out else f"退出码 {r.returncode}"
            mark = "✓" if r.returncode == 0 else "✗"
            print(f"[seal] {mark} {box}: {tail}")
            if r.returncode != 0:
                ok_all = False
                err = r.stderr.decode("utf-8", "ignore").strip()
                if err:
                    print("       " + err.splitlines()[-1])
        if not ok_all:
            return 1
        print()
        print("[build] 下一步：验一遍")
        print(f"   python _builder/audit_leak.py      # 独立泄题审计")
        print(f"   python _builder/verify_all.py      # 四部验收")
    return 0


def detect_repo() -> Path:
    """定位 skill 包仓库根：先查已知候选，再从当前目录往上找。"""
    for cand in KNOWN_REPO_CANDIDATES:
        p = Path(cand)
        if (p / "evals" / "nl2tool" / "tasks.yaml").exists():
            return p.resolve()
    for base in (Path.cwd(), *Path.cwd().parents):
        if (base / "evals" / "nl2tool" / "tasks.yaml").exists():
            return base
    return Path.cwd()


def build_system_prompt(repo: Path) -> str:
    schema_hash = sha256_file(repo / "references/tools.schema.json")[:16]
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (f"# 本次跑批 system prompt —— 最小版 v2（{stamp}）· "
            f"tools.schema.json @ {schema_hash}\n"
            "# 可整份替换成你自己的 prompt; 换过之后请把版本标识填进 answers/RUN-INFO.md。\n"
            "# 注意: prompt 里不得出现任何题目的答案提示（该选哪个工具 / 半径换算成多少 / "
            "要不要先问用户）。\n"
            "# v2 相对 v1 只加了“表达规范”与“参数取值纪律”两条**通用**要求 —— 不点名任何题目、\n"
            "# 不给出任何具体数值, 改的是“怎么说清楚”, 不是“该答什么”。\n"
            "\n"
            + SYSTEM_PROMPT_BODY + "\n")


def load_assets() -> tuple[str, str]:
    """读入锁脚本与单题校验脚本（与构建器同目录存放，便于版本化管理）。"""
    here = Path(__file__).resolve().parent
    lock = (here / "sandbox_lock_v2.py").read_text(encoding="utf-8")
    check = (here / "check_answer.py").read_text(encoding="utf-8")
    return lock, check


if __name__ == "__main__":
    raise SystemExit(main())
