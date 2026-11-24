# -*- coding: utf-8 -*-
"""污染审计: 代理读到了**别题**的问句文本吗?

**为什么查这个**: 提示词是**打包成一个文件**发的 (30 题一个 ``prompts_*.json``),
而代理只被分配 5 题。实测多个代理自述"读了该文件 1–28 行"、"prompt E5-D10 里
拼作 source_id/ra/dec/rpsf/gpsf/ypsf" —— 即它们**读到了别题的文本**。

这**不是答案键泄露** (问句是合法任务文本), 但是**跨题污染**: 真实部署里每个查询
彼此独立, 而这里第 X 题的决策可能被第 Y 题的措辞影响。

**判据**: 对每题, 取其决策里用到的**字符串取值** (工具参数中的字符串, 以及
``describe_catalog`` 的 catalog 名), 检查它是否**只出现在别题的问句里、不出现在本题问句里**。
命中即"本题决策用到了别题才有的词"。
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from evals.ablation.harness.run_batch import load_items  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
PILOT = ROOT / "temp" / "decision_pilot"
TOOLS = {"resolve_name", "list_catalogs", "describe_catalog", "cone_search",
         "crossmatch_batch", "count", "fetch_page"}


def _load(d: pathlib.Path) -> dict[str, dict]:
    """读某装配的逐题决策。"""
    out: dict[str, dict] = {}
    for p in sorted(d.glob("*.json")):
        raw = p.read_text(encoding="utf-8-sig").strip()
        if raw.startswith("```"):
            raw = raw.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            out[p.stem] = json.loads(raw)
        except json.JSONDecodeError:
            out[p.stem] = {}
    return out


def _tokens(dec: dict) -> set[str]:
    """取决策里用到的字符串取值 (工具名除外)。"""
    out: set[str] = set()
    for c in dec.get("tool_calls") or []:
        for v in (c.get("args") or {}).values():
            for item in (v if isinstance(v, list) else [v]):
                if isinstance(item, str) and item not in TOOLS and len(item) >= 3:
                    out.add(item)
    return out


def main() -> int:
    """逐格判"用到了别题才有的词"。"""
    items = {i["id"]: i for i in load_items()}
    a3, b3 = _load(PILOT / "out"), _load(PILOT / "out_b3")
    utt = {i: str(it.get("utterance") or "") for i, it in items.items()}
    hits = 0
    checked = 0
    rows: list[str] = []
    for name, dec in (("A3", a3), ("B3", b3)):
        for iid, d in dec.items():
            if not d or iid not in utt:
                continue
            checked += 1
            mine = utt[iid]
            others = " ".join(v for k, v in utt.items() if k != iid)
            for tok in sorted(_tokens(d)):
                if tok not in mine and tok in others:
                    hits += 1
                    rows.append(f"   ⚠ {name}/{iid}: 取值 {tok!r} 只出现在**别题**问句里")
    for r in rows[:14]:
        print(r)
    if len(rows) > 14:
        print(f"   ... 另有 {len(rows) - 14} 条")
    print(f"\n跨题污染命中: {hits} 次 / 检查 {checked} 格")
    print("\n说明: 命中说明该格决策用到了**别题才有的词**。若集中在校验过的字段名")
    print("      (如 rpsf/gpsf), 则污染是**词表级**的, 不改变路由方向; 但仍应修。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
