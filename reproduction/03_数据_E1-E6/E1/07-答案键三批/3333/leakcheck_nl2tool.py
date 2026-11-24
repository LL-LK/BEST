#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NL2Tool E1 作答泄漏检测 (leak_check)
====================================
判定 28 份作答是否「抄答案」或「泄露评测金标/凭据」。

原理 (与项目 memory 记载一致):
  抽 tasks.yaml 的"秘密"字段 + graders.py 的维度/权重 → 对每份作答做
  "在答案、但题面/白名单(MODEL_CONTEXT)均无"的逐字命中检测。
  - 命中"秘密字段" => 抄答案/泄题嫌疑
  - 命中"凭据形状" => 数据泄露嫌疑
  - 命中"跨题引用" => 串题污染嫌疑

白名单 (模型合法可见, 不算泄漏):
  src/ static/ references/ contracts/ SKILL.md manifest.yaml environment.yaml
  (即 astro-best skill 本体, 非 evals/ 标注)
"""
import os, re, glob, sys

from pathlib import Path

_HERE = Path(__file__).resolve()
ANSWER_DIR = str(_HERE.parent)                                        # 答案与脚本同目录
REPO_ROOT  = str(_HERE.parents[3])                                    # 仓库根（不硬编码本机路径）
TASKS_YAML = os.path.join(REPO_ROOT, "evals", "nl2tool", "tasks.yaml")
GRADERS_PY = os.path.join(REPO_ROOT, "evals", "nl2tool", "graders.py")

# ---------------------------------------------------------------------------
# 1. 抽取金标"秘密"字段 (模型在真实评测里看不到)
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
# 跨题引用 (在某份作答里提到别的题号 => 串题)
CROSS_REF = re.compile(r"NL2T-(\d{2})")

def extract_secret_tokens_from_yaml():
    """从 tasks.yaml 抽取所有确定性秘密 token (reason_code 值 + must_not_call 工具名)。"""
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

def grep_repo(pattern, root=REPO_ROOT, exclude_dirs=None):
    """在仓库(白名单范围内)里搜 pattern, 返回命中的文件集合。"""
    if exclude_dirs is None:
        exclude_dirs = {"evals", ".git", "node_modules", "__pycache__", "temp", ".workbuddy"}
    hits = set()
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in exclude_dirs]
        for f in fn:
            if not f.endswith((".md", ".py", ".yaml", ".json", ".txt")):
                continue
            p = os.path.join(dp, f)
            try:
                with open(p, encoding="utf-8", errors="ignore") as fh:
                    if pattern in fh.read():
                        hits.add(p)
            except Exception:
                pass
    return hits

def main():
    secret = extract_secret_tokens_from_yaml()
    # 把 yaml 抽到的 reason_code 也并入高置信 token
    high = set(HIGH_CONF_TOKENS) | secret

    # 预检: 这些高置信 token 是否出现在"白名单"本体里 (若出现则不是泄题证据)
    whitelist_hits = {t: grep_repo(t) for t in high}

    answer_files = sorted(glob.glob(os.path.join(ANSWER_DIR, "NL2T-*.md")))
    report = []
    overall_leak = False

    for fp in answer_files:
        name = os.path.basename(fp)
        with open(fp, encoding="utf-8") as f:
            text = f.read()
        self_ref = set()
        # 跨题引用 (排除自身题号)
        m = re.match(r"NL2T-(\d{2})", name)
        self_no = m.group(1) if m else None
        for cm in CROSS_REF.finditer(text):
            if cm.group(1) != self_no:
                self_ref.add("NL2T-" + cm.group(1))

        # 高置信 token 命中 (且不在白名单本体出现 => 泄题)
        hit_high = []
        for t in high:
            if t in text:
                in_whitelist = bool(whitelist_hits.get(t))
                hit_high.append((t, in_whitelist))

        # 通用标记
        hit_generic = [g for g in GENERIC_MARKERS if g in text]

        # 凭据形状
        hit_cred = []
        for pat in CRED_SHAPES:
            for cm in re.finditer(pat, text, re.IGNORECASE):
                hit_cred.append(cm.group(0)[:40])

        flags = []
        if hit_high:
            leaked = [t for t, wl in hit_high if not wl]
            if leaked:
                flags.append("抄答案/泄题:" + ",".join(leaked))
                overall_leak = True
        if hit_generic:
            flags.append("指向金标:" + ",".join(hit_generic))
            overall_leak = True
        if hit_cred:
            flags.append("凭据形状:" + "|".join(hit_cred))
            overall_leak = True
        if self_ref:
            flags.append("跨题引用:" + ",".join(sorted(self_ref)))
            overall_leak = True

        report.append((name, flags, hit_high, hit_generic, hit_cred, sorted(self_ref)))

    # 输出
    print("="*78)
    print("NL2Tool E1 作答泄漏检测报告")
    print("="*78)
    print("作答目录:", ANSWER_DIR)
    print("高置信秘密 token 总数:", len(high))
    print("  其中只在 tasks.yaml 出现、白名单本体未见:",
          sum(1 for t in high if not whitelist_hits.get(t)))
    print("-"*78)
    clean = 0
    for name, flags, hit_high, hit_generic, hit_cred, cross in report:
        if flags:
            print(f"[!] {name}")
            for fl in flags:
                print(f"      - {fl}")
        else:
            clean += 1
            print(f"[OK] {name}  无泄漏信号")
    print("-"*78)
    print(f"洁净: {clean}/{len(report)}  有信号: {len(report)-clean}/{len(report)}")
    print("整体结论:", "存在泄漏/抄答案嫌疑" if overall_leak else "未检测到抄答案或数据泄露")
    print("="*78)

    # 附: 高置信 token 是否在白名单本体出现 (解释用)
    print("\n[诊断] 高置信 token 在 skill 白名单本体的出现情况 (若出现则非泄题证据):")
    for t in sorted(high):
        files = whitelist_hits.get(t, set())
        if files:
            short = [os.path.relpath(x, REPO_ROOT) for x in list(files)[:3]]
            print(f"  {t}: 见 {short}")
    print("\n[诊断] 以下高置信 token 仅在 tasks.yaml(金标)出现, 若出现在作答即泄题:")
    only_gold = [t for t in high if not whitelist_hits.get(t)]
    print("  " + ", ".join(sorted(only_gold)))

if __name__ == "__main__":
    main()
