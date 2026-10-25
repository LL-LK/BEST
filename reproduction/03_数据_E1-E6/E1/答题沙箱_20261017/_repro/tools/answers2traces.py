# -*- coding: utf-8 -*-
"""answers2traces — 把沙箱 answers/NL2T-*.md 转成 E1 runner 可吃的轨迹 JSON。

能力边界: 只做格式搬运 (两段式 Markdown → trace 字典), 不做任何判分,
不改写答案文本, 不补全缺失调用。解析不出来的调用行会原样记进
``parse_warnings``, 由人工复核 —— 静默丢行会让"少调了"看起来像"没调"。

用法:
  python answers2traces.py <sandbox_dir> <out_dir>

约定: 输出 ``<out_dir>/NL2T-nn.json``, 每条
  {"task_id","run_id","attempt","model_id","system_prompt_version",
   "source":"live-run","batch","sandbox","tool_calls",[...],
   "answer_text","http_requests","s1_events":[],"parse_warnings":[]}
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# 会真发网络请求的工具 (元数据工具 list_catalogs / describe_catalog 零请求)
NETWORK_TOOLS = {"resolve_name", "cone_search", "crossmatch_batch", "count", "fetch_page"}

ANSWER_HEAD_RE = re.compile(r"^##\s*二[、.．]\s*给用户的回答\s*$", re.M)
CALL_HEAD_RE = re.compile(r"^##\s*一[、.．]\s*调用轨迹\s*$", re.M)
CALL_LINE_RE = re.compile(
    r"^\s*(?:\d+\s*[.、)）]|[-*•])\s*`?(?P<tool>[A-Za-z_]\w*)`?\s*"
    r"(?:参数|args)?\s*[:：]?\s*(?P<rest>.*)$"
)


def parse_args(raw: str) -> tuple[dict, str]:
    """严格 JSON 优先; 失败则给裸 key 加引号再试; 再失败返回 (空, 原因)。"""
    raw = raw.strip().strip("`")
    if not raw:
        return {}, ""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0:
        return {}, f"参数不是 JSON 对象: {raw[:60]!r}"
    body = raw[start:end + 1]
    try:
        value = json.loads(body)
        return (value, "") if isinstance(value, dict) else ({}, "参数不是对象")
    except (json.JSONDecodeError, ValueError):
        pass
    fixed = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', body)
    try:
        value = json.loads(fixed)
        if isinstance(value, dict):
            return value, ""
    except (json.JSONDecodeError, ValueError):
        pass
    return {}, f"参数无法解析: {body[:60]!r}"


def parse_answer(path: Path) -> dict:
    """解析一份两段式答案, 返回 trace 骨架 (不含批次元信息)。"""
    text = path.read_text(encoding="utf-8")
    warnings: list[str] = []

    m_answer = ANSWER_HEAD_RE.search(text)
    if m_answer:
        head, answer = text[:m_answer.start()], text[m_answer.end():]
    else:
        head, answer = text, ""
        warnings.append("缺『给用户的回答』段 — 判分器只吃这一段")

    m_calls = CALL_HEAD_RE.search(head)
    call_block = head[m_calls.end():] if m_calls else ""
    if not m_calls:
        warnings.append("缺『调用轨迹』段 — 按零调用处理")

    calls: list[dict] = []
    for line in call_block.splitlines():
        if not line.strip():
            continue
        if line.strip() in ("无", "无调用", "无需调用", "（无）", "(无)"):
            continue      # 模板规定的"零调用"写法, 不是解析失败
        m = CALL_LINE_RE.match(line)
        if not m:
            warnings.append(f"无法解析的轨迹行: {line.strip()[:60]!r}")
            continue
        args, why = parse_args(m.group("rest"))
        if why:
            warnings.append(f"{m.group('tool')}: {why}")
        calls.append({"tool": m.group("tool"), "args": args})

    return {
        "task_id": path.stem,
        "tool_calls": calls,
        "answer_text": answer.strip(),
        "http_requests": sum(1 for c in calls if c["tool"] in NETWORK_TOOLS),
        "s1_events": [],
        "parse_warnings": warnings,
    }


def parse_run_info(path: Path) -> dict:
    """从 RUN-INFO.md 的表格里抽五栏台账 (缺列即留空, 不猜)。"""
    info: dict[str, str] = {}
    if not path.is_file():
        return info
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*(run_id|model_id|system_prompt_version|started_at|operator)\s*\|\s*(.+?)\s*\|",
                     line)
        if m:
            info[m.group(1)] = m.group(2)
    return info


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    sandbox, out_dir = Path(argv[1]).resolve(), Path(argv[2]).resolve()
    answers = sandbox / "answers"
    if not answers.is_dir():
        print(f"[error] 没有 answers 目录: {answers}")
        return 2
    run = parse_run_info(answers / "RUN-INFO.md")
    out_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for path in sorted(answers.glob("NL2T-*.md")):
        trace = parse_answer(path)
        trace.update({
            "run_id": run.get("run_id", ""),
            "attempt": 1,
            "model_id": run.get("model_id", ""),
            "system_prompt_version": run.get("system_prompt_version", ""),
            "source": "live-run",
            "batch": sandbox.name,
            "sandbox": str(sandbox),
            "answered_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            .isoformat().replace("+00:00", "Z"),
        })
        (out_dir / f"{path.stem}.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        total += 1
        for w in trace["parse_warnings"]:
            print(f"  [warn] {path.stem}: {w}")

    print(f"[ok] {total} 条轨迹 → {out_dir}")
    print(f"[run] run_id={run.get('run_id','(未填)')} model={run.get('model_id','(未填)')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
