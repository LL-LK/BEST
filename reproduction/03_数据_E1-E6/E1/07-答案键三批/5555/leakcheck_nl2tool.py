#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NL2Tool E1 作答泄漏检测 (leak_check) —— 5555 答案键
====================================================
用途：为 5555 答案键补上此前缺失的独立泄漏自检（3333 有报告 + 脚本，5555 没有）。

判定三类风险
  1) 抄答案 / 泄题：作答里出现 tasks.yaml 或 graders.py 的内部脚手架字段
  2) 向外泄露：作答指向评测金标或评测设计文档
  3) 凭据外泄 / 跨题污染：凭据形状字面值、以及作答引用了别的题号

与 3333 版的关系（**两处刻意差异，均已论证**）
---------------------------------------------
token 表 / 正则串 / 检查类别与 3333 版**逐项一致**，保证两类风险可横比。
差异只有两点，都是**收紧**方向：

  1) **白名单严格化**。3333 版 `grep_repo()` 走的是「全仓 walk 减去
     {evals,.git,node_modules,__pycache__,temp,.workbuddy}」，于是
     `nl2tool-candidate-answers/**`（含它自己的 leakcheck 脚本、各批判分报告）
     全被算成"白名单本体"。后果是**几乎每个 token 都能在所谓白名单里找到**，
     "命中且不在白名单"这一判据被稀释。本版只认测试对象本体：

        SKILL.md README.md manifest.yaml architecture.md
        contracts/ static/ references/ src/ agents/ templates/ rag/

     即 `ANSWERS.md` 抬头自述的合法可见面。`docs/eval-*` 与 `CHANGELOG.md`
     按项目纪律属**禁止读取**，不计白名单。

  2) **新增扫 `answers.json`**。5555 与 3333/4444 的关键差异是：它的
     toolset / param / convert / redundant 四维是从 `answers.json` 的
     **真实 predicted tool_calls** 判出来的（3333/4444 用硬编码 canonical）。
     该文件若带金标字段会**直接污染分数**，必须纳入检面。

用法
----
    cd <本脚本所在目录> && python leakcheck_nl2tool.py
    # 可选：把同一套严格标准施加到别的答案键，做跨批横比
    python leakcheck_nl2tool.py --also-check ../../3333/E1-answers-2026-10-07

本脚本只读，不写任何被检文件，也不修改仓库。
"""
import os
import re
import sys
import glob

from pathlib import Path

_HERE = Path(__file__).resolve()
ANSWER_DIR = str(_HERE.parent)                       # 答案与脚本同目录
REPO_ROOT = str(_HERE.parents[3])                    # 仓库根（不硬编码本机路径）
TASKS_YAML = os.path.join(REPO_ROOT, "evals", "nl2tool", "tasks.yaml")
GRADERS_PY = os.path.join(REPO_ROOT, "evals", "nl2tool", "graders.py")

# ---------------------------------------------------------------------------
# 1. 白名单 = 被测对象本体（模型合法可见面）
# ---------------------------------------------------------------------------
WHITELIST_DIRS = ["src", "static", "references", "contracts", "agents", "templates", "rag"]
WHITELIST_FILES = ["SKILL.md", "README.md", "manifest.yaml", "architecture.md",
                   "environment.yaml", "pipeline.yaml", "pyproject.toml"]
SCAN_EXT = (".md", ".py", ".yaml", ".json", ".txt")

# ---------------------------------------------------------------------------
# 2. 秘密串表 —— 与 3333 版逐字一致
# ---------------------------------------------------------------------------
HIGH_CONF_TOKENS = [
    # reason_code 枚举 (tasks.yaml reject.reason_code)
    "NO_TIME_SERIES", "NO_FULL_EXPORT", "NO_UPLOAD_JOB", "CREDENTIAL_IN_PARAM",
    "NO_IMAGE_CUTOUT", "CATALOG_NOT_HOSTED",
    # 脚手架键名 (tasks.yaml schema)
    "must_not_call", "should_call_best", "expect_tools", "anti_patterns",
    "expect_tools_after_clarify", "reason_code", "reason_aliases",
    # graders 专用
    "metascore", "graders.py", "graders ",
]
# 通用"指向评测金标"标记
GENERIC_MARKERS = [
    "tasks.yaml", "graders", "golden", "evals/", "标准答案", "参考答案",
    "answer key", "金标", "六维权重", "通过门槛", "逐维及格",
]
# 凭据形状 (出现在作答中 => 泄露嫌疑)
CRED_SHAPES = [
    r"sk-[A-Za-z0-9]{16,}", r"AKIA[0-9A-Z]{16,}", r"Bearer\s+[A-Za-z0-9._-]+",
    r"api[_-]?key\s*[:=]\s*\S+", r"api[_-]?token\s*[:=]\s*\S+",
    r"password\s*[:=]\s*\S+", r"token\s*[:=]\s*[\"']?[A-Za-z0-9]{12,}",
    r"Authorization\s*:\s*", r"NADC_OAUTH_CLIENT_SECRET\s*[:=]\s*\S+",
]
CROSS_REF = re.compile(r"NL2T-(\d{2})")


# ---------------------------------------------------------------------------
# 3. 工具函数
# ---------------------------------------------------------------------------
def extract_secret_tokens_from_yaml():
    """从 tasks.yaml 抽取确定性秘密 token（reason_code 值 + must_not_call 工具名）。"""
    toks = set()
    try:
        with open(TASKS_YAML, encoding="utf-8") as f:
            txt = f.read()
        for m in re.finditer(r"reason_code:\s*([A-Z_]+)", txt):
            toks.add(m.group(1))
        for m in re.finditer(r"must_not_call:\s*\n((?:\s*-\s*\w+\s*\n)+)", txt):
            for t in re.finditer(r"-\s*(\w+)", m.group(1)):
                toks.add(t.group(1))
    except Exception as e:
        print("WARN extract yaml:", e)
    return toks


def build_whitelist_index():
    """把白名单范围内的文件内容拼成一个大字符串，供成员查询。返回 (index, 文件数)。"""
    chunks, n = [], 0
    for d in WHITELIST_DIRS:
        root = os.path.join(REPO_ROOT, d)
        for dp, _dn, fn in os.walk(root):
            for f in fn:
                if f.endswith(SCAN_EXT):
                    try:
                        with open(os.path.join(dp, f), encoding="utf-8", errors="ignore") as fh:
                            chunks.append(fh.read())
                        n += 1
                    except Exception:
                        pass
    for f in WHITELIST_FILES:
        p = os.path.join(REPO_ROOT, f)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8", errors="ignore") as fh:
                    chunks.append(fh.read())
                n += 1
            except Exception:
                pass
    return "\n".join(chunks), n


def scan(text, high, wl_index, self_no):
    """四类检测。self_no=None 表示该文件本就是清单件，不做跨题判定。"""
    cross = []
    if self_no is not None:
        cross = sorted({"NL2T-" + m.group(1)
                        for m in CROSS_REF.finditer(text) if m.group(1) != self_no})

    hit_high = [(t, t in wl_index) for t in high if t in text]
    hit_generic = [g for g in GENERIC_MARKERS if g in text]

    hit_cred = []
    for pat in CRED_SHAPES:
        for cm in re.finditer(pat, text, re.IGNORECASE):
            hit_cred.append(cm.group(0)[:40])

    flags = []
    leaked = [t for t, wl in hit_high if not wl]
    if leaked:
        flags.append(("抄答案/泄题", ",".join(leaked)))
    if hit_generic:
        flags.append(("指向金标", ",".join(hit_generic)))
    if hit_cred:
        flags.append(("凭据形状", "|".join(hit_cred)))
    if cross:
        flags.append(("跨题引用", ",".join(cross)))
    return flags, hit_high, hit_generic, hit_cred, cross


def run(label, directory, high, wl_index, include_json=True):
    print("=" * 78)
    print(f"NL2Tool E1 泄漏检测 —— {label}")
    print("=" * 78)
    print("作答目录:", directory)
    overall_leak = False
    clean = total = 0

    files = sorted(glob.glob(os.path.join(directory, "NL2T-*.md")))
    print(f"[A] per-task 作答 {len(files)} 份")
    for fp in files:
        name = os.path.basename(fp)
        total += 1
        with open(fp, encoding="utf-8") as f:
            text = f.read()
        m = re.match(r"NL2T-(\d{2})", name)
        self_no = m.group(1) if m else None
        flags, hit_high, _hg, _hc, _cr = scan(text, high, wl_index, self_no)
        if flags:
            print(f"  [!] {name}")
            for kind, detail in flags:
                print(f"        - {kind}: {detail}")
            if any(k != "跨题引用" for k, _ in flags):
                overall_leak = True
        else:
            clean += 1
            print(f"  [OK] {name}  无泄漏信号")

    aj = os.path.join(directory, "answers.json")
    if include_json and os.path.exists(aj):
        total += 1
        print("-" * 78)
        print("[B] answers.json（判分直接依赖，必检）")
        with open(aj, encoding="utf-8") as f:
            jtext = f.read()
        flags, _hh, _hg, _hc, _cr = scan(jtext, high, wl_index, None)
        if flags:
            print("  [!] answers.json")
            for kind, detail in flags:
                print(f"        - {kind}: {detail}")
            overall_leak = True
        else:
            clean += 1
            print("  [OK] answers.json  无泄漏信号")

    print("-" * 78)
    print(f"洁净: {clean}/{total}  有信号: {total - clean}/{total}")
    print("金标类泄漏（抄答案/指向金标/凭据）:",
          "检出 —— 需处置" if overall_leak else "**0 检出**")
    print("=" * 78)
    print()
    return overall_leak


def diagnose(high, wl_index):
    print("[诊断] 高置信 token 在「被测对象本体」白名单中的出现情况"
          "（出现即该串已公开，不足以单独作为泄题证据）:")
    for t in sorted(high):
        if t in wl_index:
            print(f"  {t}: 在白名单内（公开字符串）")
    print()
    print("[诊断] 以下 token 在白名单本体**不存在**，一旦出现在作答即构成泄题证据:")
    only_gold = sorted(t for t in high if t not in wl_index)
    print("  " + (", ".join(only_gold) if only_gold else "（无）"))
    print()


def main():
    argv = sys.argv[1:]
    extra = None
    if "--also-check" in argv:
        i = argv.index("--also-check")
        if i + 1 < len(argv):
            extra = argv[i + 1]

    secret = extract_secret_tokens_from_yaml()
    high = set(HIGH_CONF_TOKENS) | secret
    wl_index, wl_n = build_whitelist_index()

    print("=" * 78)
    print("NL2Tool E1 作答泄漏检测报告 —— 5555 答案键（补充件）")
    print("=" * 78)
    print("仓库根  :", REPO_ROOT)
    print("金标    :", os.path.relpath(TASKS_YAML, REPO_ROOT))
    print("判分器  :", os.path.relpath(GRADERS_PY, REPO_ROOT))
    print("白名单  :", ", ".join(WHITELIST_DIRS + WHITELIST_FILES), f"（{wl_n} 个文件）")
    print("高置信秘密 token 总数:", len(high))
    print()

    diagnose(high, wl_index)

    bad = run("5555 / E1-nl2tool-answers-2026-10-07", ANSWER_DIR, high, wl_index)
    if extra:
        abs_extra = os.path.abspath(extra)
        if os.path.isdir(abs_extra):
            run(os.path.basename(os.path.dirname(abs_extra)) + " 横比",
                abs_extra, high, wl_index, include_json=False)

    print("整体结论:",
          "存在金标泄漏/抄答案嫌疑" if bad else "未检测到抄答案、指向金标或凭据外泄")


if __name__ == "__main__":
    main()
