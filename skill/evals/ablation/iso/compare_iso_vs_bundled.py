# -*- coding: utf-8 -*-
"""隔离批 vs 打包批: 把"污染"从一个粗糙的 token 计数, 收敛到**路由级**的因果对照。

**为什么要重做**: 上一轮报"跨题污染 14/60", 判据是"该取值只出现在别题问句里"。
隔离批 (结构上**不可能**读到别题) 仍然产出 `rpsf`/`gpsf`/`dec` ——
说明那些 token 是**波段→列名的约定推断**, 不是抄来的。**该判据是假阳性。**

**改用因果对照**: 同一格, 打包投递 vs 逐格投递, 路由是否改变。
隔离批是**对照组** —— 只有它才能区分"抄来的"与"自己推出来的"。

并单列**词表漂移**: `columns` / `sort` 的参数取值在两批之间是否不同
(打包批更可能收敛到站点专有拼法, 因为它读得到别题的拼法)。
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

ROOT = pathlib.Path(__file__).resolve().parents[3]
OLD = ROOT / "temp" / "decision_pilot" / "out"          # 打包投递
NEW = ROOT / "temp" / "decision_iso_out" / "A3"         # 逐格投递


def _load(d: pathlib.Path) -> dict[str, dict]:
    """读逐题决策。"""
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


def _cols(dec: dict) -> str:
    """取该决策里 columns/sort 的取值拼成串 (看词表漂移)。"""
    bits: list[str] = []
    for c in dec.get("tool_calls") or []:
        a = c.get("args") or {}
        for k in ("columns", "sort"):
            if k in a:
                v = a[k]
                bits.append(f"{k}={'+'.join(v) if isinstance(v, list) else v}")
    return " ".join(bits) or "(无)"


def main() -> int:
    """打印路由级因果对照与词表漂移。"""
    old, new = _load(OLD), _load(NEW)
    both = sorted(set(old) & set(new))
    print(f"两批都有: {len(both)} 格 (打包 {len(old)} / 隔离 {len(new)})")
    print(f"\n{'题号':10s} {'打包批':9s} {'隔离批':9s} 判定")
    flips = 0
    for i in both:
        a, b = old[i].get("route"), new[i].get("route")
        mark = "一致" if a == b else "**翻转为**"
        flips += int(a != b)
        print(f"  {i:10s} {str(a):9s} {str(b):9s} {mark}")
    print(f"\n路由翻转: {flips}/{len(both)}")
    print("\n词表漂移 (columns / sort 的取值):")
    drift = 0
    for i in both:
        ca, cb = _cols(old[i]), _cols(new[i])
        if ca != cb:
            drift += 1
            print(f"  {i:10s} 打包={ca}")
            print(f"  {'':10s} 隔离={cb}")
    print(f"  词表不同的格数: {drift}/{len(both)}")
    print("\n结论口径:")
    print("  * 路由翻转 = **真污染**(打包投递让本题用了别题的上下文);")
    print("  * 仅词表不同 = **词表漂移**, 不影响路由, 属风格差异;")
    print("  * 隔离批仍产出的 token = **推断**, 不是抄 —— 上一轮的 token 判据是假阳性。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
