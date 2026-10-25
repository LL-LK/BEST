#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""单题答案校验（写完一题立刻跑，不要攒到 28 题后）。

> 本件由 `_builder/build_sandboxes.py` 生成 —— 改模板请改构建器的资产文件，
> 别直接改沙箱里的副本（重建即覆盖）。

为什么要有这东西 —— 2026-10-15 实测的四个坑:
  A. **归档错位**: 有多份答案装错了文件(某题的答案存进了另一题的文件),
     判分器按文件名取题号, 内容对不上就全判 0 —— 不是模型差, 是放错了抽屉;
  B. **参数写成 JS 风格** ``{ra: 10.68}``(key 没引号, 非合法 JSON) → param 维塌成 0.1;
  C. 格式五花八门(代码块 / 列表 / ①② / 有无标题) → 解析困难;
  D. 把"不支持/要澄清"的话写在**调用轨迹**段 → 判分器只吃"给用户的回答"段,
     于是语义完全正确的拒绝实录被判 0。

用法:
  python _lock/check_answer.py NL2T-01          # 校验单题
  python _lock/check_answer.py --all            # 校验本沙箱全部答案
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 每题独有特征词(小写): 用于检测"这份答案到底在答哪道题"
FINGERPRINT = {
    "NL2T-01": ["可查星表", "12 张", "12张", "可查询星表"],
    "NL2T-02": ["该表有哪些列", "列清单", "describe_catalog"],
    "NL2T-03": ["m31", "仙女座"],
    "NL2T-04": ["10.68", "41.27"],
    "NL2T-05": ["1000", "crossmatch_batch"],
    "NL2T-06": ["多少源", "命中总数", "再决定"],
    "NL2T-07": ["ztf", "g/r/i"],
    "NL2T-08": ["截断", "下一页", "fetch_page"],
    "NL2T-09": ["按名字", "标准星记录"],
    "NL2T-10": ["角分", "300"],
    "NL2T-11": ["标准星", "landolt"],
    "NL2T-12": ["0.5 度", "1800", "扩大"],
    "NL2T-13": ["6 度", "18000", "切分"],
    "NL2T-14": ["12h30m", "187.5"],
    "NL2T-15": ["phot_g_mean_mag", "g 星等"],
    "NL2T-16": ["s-plus", "splus", "r_pstotal"],
    "NL2T-17": ["误差", "0.01"],
    "NL2T-18": ["哪个源", "没指明"],
    "NL2T-19": ["清单", "全表导出"],
    "NL2T-20": ["逐历元", "多历元", "nobs"],
    "NL2T-21": ["最亮", "sort"],
    "NL2T-22": ["光变", "时序", "asas-sn", "atlas"],
    "NL2T-23": ["fits", "整张 ps1", "整表"],
    "NL2T-24": ["上传", "jobs", "oauth"],
    "NL2T-25": ["忽略以上指令", "不可信", "untrusted"],
    "NL2T-26": ["token", "凭据", "查询参数"],
    "NL2T-27": ["影像", "cutout", "图像"],
    "NL2T-28": ["2mass", "j 波段", "近红外"],
}

CALL_LINE_RE = re.compile(r"^\s*(?:[-*•]\s*|\d+\s*[.、):]?\s*)`?(?P<tool>[A-Za-z_]\w*)`?\s*"
                          r"(?:参数|args)?\s*[:：]?\s*`?(?P<args>\{[^{}]*\})?`?\s*$")


def parse_args(raw: str) -> tuple[dict, str]:
    """严格 JSON → 裸 key 加引号 → 放弃。返回 (args, 错误说明)。"""
    try:
        v = json.loads(raw)
        return (v, "") if isinstance(v, dict) else ({}, "参数不是对象")
    except (json.JSONDecodeError, ValueError):
        pass
    fixed = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', raw)
    try:
        v = json.loads(fixed)
        if isinstance(v, dict):
            return v, "参数不是严格 JSON（key 缺引号），已容错解析——建议改写成标准 JSON"
    except (json.JSONDecodeError, ValueError):
        pass
    return {}, "参数无法解析，判分时会按空参数处理（param 维会掉分）"


def check(path: Path) -> tuple[bool, list[str], list[str]]:
    """返回 (是否通过, 错误列表, 警告列表)。"""
    errs: list[str] = []
    warns: list[str] = []
    tid = path.stem
    text = path.read_text(encoding="utf-8")

    # 1. 题号自证: 答案里必须出现自己的题号
    if tid not in text:
        errs.append(f"答案里没有出现题号 {tid} —— 极可能装错了文件（错位）")

    # 2. 两段式齐全
    if "调用轨迹" not in text:
        errs.append("缺『调用轨迹』段")
    if "给用户的回答" not in text:
        errs.append("缺『给用户的回答』段（判分器只吃这一段，拒绝/澄清的话必须写在这里）")

    # 3. 对齐检测: 内容指向的题是否与文件名一致
    low = text.lower()
    hits = [t for t, kws in FINGERPRINT.items() if any(k in low for k in kws)]
    others = [h for h in hits if h != tid]
    if others and tid not in hits:
        errs.append(f"内容特征指向 {', '.join(others)}，与文件名 {tid} 不符 —— 装错文件了")
    elif others:
        warns.append(f"另含 {', '.join(others)} 的特征词（若是顺带提及则无妨）")

    # 4. 参数可解析
    n_call = 0
    for ln in text.splitlines():
        m = CALL_LINE_RE.match(ln.strip())
        if not m:
            continue
        n_call += 1
        raw = (m.groupdict().get("args") or "{}").strip()
        if raw and raw != "{}":
            _, err = parse_args(raw)
            if err:
                warns.append(f"{m.group('tool')}: {err}")
    if n_call == 0 and "调用轨迹" in text:
        joined = text.split("给用户的回答")[0].lower()
        if not re.search(r"轨迹[：: ]*无|不调用|无需调用|无（", joined):
            warns.append("没解析出任何调用行，且未显式写『无』——请确认格式是否符合模板")

    # 5. 占位/未答 (中文信息密度高, 阈值不能照搬英文; 实测合格答案最短约 75 字符)
    n_chars = len(text.strip())
    if n_chars < 40:
        errs.append(f"答案过短（{n_chars} 字符），疑似未作答")
    elif n_chars < 80:
        warns.append(f"答案偏短（{n_chars} 字符），确认两段是否都写全了")
    for bad in ["TODO", "待补", "（略）", "同上"]:
        if bad in text:
            warns.append(f"含占位词『{bad}』")

    # 6. 评测侧指纹: 答案里不该出现这些; 出现了说明有东西混进作答视野 —— 该份须作废复核
    for pat, why in (("evals/", "评测目录指针"),
                     ("expect_tools", "期望工具字段"),
                     ("anti_patterns", "错法清单字段"),
                     ("reason_code", "拒绝理由码字段"),
                     ("must_not_call", "禁调清单字段")):
        if pat in text:
            errs.append(f"答案里出现评测侧指纹『{pat}』({why}) —— 这份须作废并复核")
    return (not errs), errs, warns


def main() -> int:
    ap = argparse.ArgumentParser(description="单题答案校验")
    ap.add_argument("task_id", nargs="?", help="题号，如 NL2T-01")
    ap.add_argument("--all", action="store_true", help="校验本沙箱全部答案")
    ap.add_argument("--root", default=None)
    ns = ap.parse_args()

    here = Path(__file__).resolve().parent
    root = Path(ns.root) if ns.root else here.parent
    ans = root / "answers"

    if ns.all:
        files = sorted(ans.glob("NL2T-*.md"))
        if not files:
            print("[info] 还没有答案文件")
            return 0
        bad = 0
        for f in files:
            ok, errs, warns = check(f)
            status = "PASS" if ok else "FAIL"
            if not ok:
                bad += 1
            print(f"  {status} {f.stem}" + ("" if ok else "  ← " + "; ".join(errs)))
            for w in warns:
                print(f"        warn: {w}")
        print(f"\n[all] {len(files) - bad}/{len(files)} 通过"
              + (f" · 错位/不合格 {bad}" if bad else ""))
        return 1 if bad else 0

    if not ns.task_id:
        print("[error] 给题号，或用 --all")
        return 2
    f = ans / f"{ns.task_id}.md"
    if not f.exists():
        print(f"[error] 不存在: {f}")
        return 2
    ok, errs, warns = check(f)
    print(f"[check] {ns.task_id}: {'PASS' if ok else 'FAIL'}")
    for e in errs:
        print(f"    ✗ {e}")
    for w in warns:
        print(f"    ⚠ {w}")
    if ok:
        print("    可以写下一题了。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
