# -*- coding: utf-8 -*-
"""把『模型答案』目录里的 NL2T-*.json 规范化成 runner 轨迹。

答案件只有 task_id/route/tool_calls/answer_text/s1_events 五个字段,
缺 source/run_id/attempt/model_id —— runner 靠 source 区分金标准合成轨迹与
真实跑批轨迹 (混合来源会直接阻断), 缺字段会落默认 live-run 但拿不到模型身份。
本件只做补齐与复制, 不改动任何模型产出字段 (轨迹只增不改, 原件留桌面不动)。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REQUIRED = ("task_id", "tool_calls", "answer_text")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="规范化 E1 答案目录为 runner 轨迹")
    parser.add_argument("--answers", required=True, help="答案件目录 (含 NL2T-*.json)")
    parser.add_argument("--out", required=True, help="轨迹输出目录 (会被清空重建)")
    parser.add_argument("--model-id", default="unknown-live-model", help="被测模型代号")
    parser.add_argument("--run-id", default="live-attempt1", help="本轮 run_id")
    parser.add_argument("--source", default="live-run", help="轨迹来源标记")
    args = parser.parse_args(argv)

    answers = Path(args.answers)
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    files = sorted(answers.glob("NL2T-*.json"))
    if not files:
        print(f"[error] 目录内没有 NL2T-*.json: {answers}", file=sys.stderr)
        return 2

    written: list[str] = []
    problems: list[str] = []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in REQUIRED:
            if key not in data:
                problems.append(f"{path.name}: 缺字段 {key}")
        tid = data.get("task_id") or path.stem
        data["task_id"] = tid
        data.setdefault("source", args.source)
        data.setdefault("run_id", args.run_id)
        data.setdefault("attempt", 1)
        data.setdefault("model_id", args.model_id)
        data.setdefault("route", "answer")
        data.setdefault("http_requests", 0)
        data.setdefault("s1_events", [])
        data.setdefault("network", False)
        data.setdefault("system_prompt_version", "batch-2026-10-06")
        data.setdefault("tools_schema_hash", "batch-2026-10-06")
        dest = out / f"{tid}.{args.run_id}.json"
        dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(tid)

    missing = [f"NL2T-{i:02d}" for i in range(1, 27) if f"NL2T-{i:02d}" not in written]
    print(f"[ok] 写入 {len(written)} 条轨迹 -> {out}")
    print(f"[ok] 覆盖 task_id 集合去重后 {len(set(written))} 个; 26 题中缺: {', '.join(missing) or '无'}")
    for p in problems:
        print(f"[warn] {p}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
