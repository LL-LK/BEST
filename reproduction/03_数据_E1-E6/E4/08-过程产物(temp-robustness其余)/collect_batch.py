# -*- coding: utf-8 -*-
"""跑批采集物落盘器: 把一批评分前的原始处置写进答案面 answers/<run_id>/<题号>.json。

为什么单开一件: 采集物是**模型答出来的东西**, 必须落在答题面之外; 而逐题会话里
模型不写文件(写了就会翻到别人的答案), 由跑批的人转录。转录的机械部分交给脚本,
人只负责 payload 本身, 少一次手抄就少一处错。

用法: python temp/robustness/collect_batch.py <payload.json> [run_id]
payload 是 list[dict], 每条至少含 item_id / request / answer_text / route。
"""
from __future__ import annotations

# 标准库: JSON / 参数 / 路径
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
ANSWERS = ROOT / "temp" / "robustness" / "answers"

# 采集字段的默认值: 缺省一律按"没有"记, 不按"通过"记 (铁律 5 禁 fail-open)
DEFAULTS = {
    "tool_calls": [],
    "http_requests": 0,
    "corrected": False,
    "declared": False,
    "correct_value": None,
    "declared_issues": [],
}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法: python temp/robustness/collect_batch.py <payload.json> [run_id]")
        return 2
    payload = json.loads(pathlib.Path(argv[1]).read_text(encoding="utf-8"))
    run_id = argv[2] if len(argv) > 2 else "r1"
    out_dir = ANSWERS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    merged: dict[str, dict] = {}
    for rec in payload:
        item_id = rec["item_id"]
        row = dict(DEFAULTS)
        row.update(rec)
        row["run_id"] = run_id
        (out_dir / f"{item_id}.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
        merged[item_id] = row
    if (out_dir / "_all.json").is_file():
        merged = {**json.loads((out_dir / "_all.json").read_text(encoding="utf-8")), **merged}
    (out_dir / "_all.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    print(f"[OK] 答案面 {out_dir} 现有 {len(merged)} 条 (本批 {len(payload)} 条)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
