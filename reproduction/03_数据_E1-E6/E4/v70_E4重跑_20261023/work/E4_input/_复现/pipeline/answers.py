# 本文件由 temp/e4_judge/parse_r2.py 复制而来，**只改了两行路径常量**。
# -*- coding: utf-8 -*-
"""把 2026-10-22 这批新答卷放进答案面 r2/，并逐题抽成判据能吃的记录。

三份新答卷的**交付形态又不一样**（这次不是同一套脚本产的），所以抽取要按箱分别写：
  sb1  35 题各自 `### RB-xx`；18 条 C 题按 6 组三连标题合答（`### RB-C01 / RB-C02 / RB-C03`），
       该组正文里明写"与 RB-xx 同一答案，逐字同义" → 同一段正文分配给组内 3 题（记录 shared_block）。
  sb2  53 题各自 `### RB-xx　<题面>`（全角空格分隔题号与题面）。
  sb3  没有逐题小节，是**一张表**：`| 题号 | 题面（简） | 判定 | 处理与依据 |`，53 行 → 一行一题。

只做切分 + 搬运，不做 route 判定（route 由 routes.py 的同一套规则定）。
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

BOX_ROOT = Path(__file__).resolve().parents[2]          # = _复现/..  = 沙箱根
ANS = BOX_ROOT / "_answers"
OUT = Path(__file__).resolve().parents[1] / "out"        # = _复现/out
SRC = {}   # 由 discover() 按箱填充：_answers/sbN/r2/ 下唯一那份 .md
# 箱号校验: 每份答卷自己声明的答题对象/箱号必须与目标箱一致, 否则当场停
BOX_SELF = {"sb1": r"sb1", "sb2": r"sb2", "sb3": r"sb3"}
EXEC_WORDS = re.compile(r"(已执行|已查|Done|EXEC|可执行|实测)")


def discover() -> None:
    """答案在哪：_answers/sbN/r2/ 下唯一一份 .md；并校验它自述的箱号与目录一致。"""
    for box in ("sb1", "sb2", "sb3"):
        cand = sorted((ANS / box / "r2").glob("*.md"))
        if len(cand) != 1:
            raise SystemExit(f"[STOP] _answers/{box}/r2/ 里应有且只有 1 份 .md，实有 {len(cand)} 份")
        head = cand[0].read_text(encoding="utf-8")[:1200]
        if not re.search(BOX_SELF[box], head):
            raise SystemExit(f"[STOP] {cand[0].name} 正文没声明 {box}，拒绝判分")
        SRC[box] = cand[0]
        print(f"  [答案] {box} <- _answers/{box}/r2/{cand[0].name}")


def split_md(text: str, item_pat: str, stop_pat: str) -> list[tuple[str, str]]:
    pat, stop = re.compile(item_pat, re.M), re.compile(stop_pat, re.M)
    marks = [(m.end(), m.group(1)) for m in pat.finditer(text)]
    out = []
    for i, (e, qid) in enumerate(marks):
        end = pat.search(text, e).start() if i + 1 < len(marks) else len(text)
        body = text[e:end]
        m = stop.search(body)
        if m:
            body = body[:m.start()]
        out.append((qid, body.strip()))
    return out


def parse_sb1(text: str) -> dict[str, dict]:
    """35 题各自成节; C 题三连标题合答 → 同段正文分配给组内每题。"""
    recs = {}
    # 三连标题: ### RB-C01 / RB-C02 / RB-C03
    for m in re.finditer(r"^### ((?:RB-C\d{2}\s*/\s*)+RB-C\d{2})\s*$", text, re.M):
        ids = re.findall(r"RB-C\d{2}", m.group(1))
        end = text.find("\n### ", m.end())
        nxt = re.search(r"^##+ ", text[m.end():], re.M)
        body_end = m.end() + nxt.start() if nxt else len(text)
        body = text[m.end():body_end].strip()
        for qid in ids:
            recs[qid] = {"answer_text": body, "shared_block": "/".join(ids)}
    # 单题标题: ### RB-01 (--- RB-50), 排除 C 组
    for m in re.finditer(r"^### (RB-\d{2})\s*$", text, re.M):
        qid = m.group(1)
        nxt = re.search(r"^##+ ", text[m.end():], re.M)
        body = text[m.end(): m.end() + nxt.start()] if nxt else text[m.end():]
        recs[qid] = {"answer_text": body.strip(), "shared_block": None}
    return recs


def parse_sb2(text: str) -> dict[str, dict]:
    """53 题各自 `### RB-xx　<题面>` (题号与题面之间是全角空格)。"""
    return {qid: {"answer_text": body, "shared_block": None}
            for qid, body in split_md(text, r"^### (RB-[A-Z0-9]+)[　\s]", r"^#{1,3}\s")}


def parse_sb3(text: str) -> dict[str, dict]:
    """一张表, 一行一题; 组标题给出分类语境, 一并带上。"""
    recs, group = {}, ""
    for line in text.splitlines():
        h = re.match(r"^### (.+)$", line)
        if h:
            group = h.group(1).strip()
            continue
        if not line.startswith("| RB-"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        qid, brief, verdict, basis = cells[0], cells[1], cells[2], "|".join(cells[3:])
        recs[qid] = {"answer_text": f"判定：{verdict}\n题面（简）：{brief}\n处理与依据：{basis}",
                     "shared_block": None, "group": group}
    return recs


PARSERS = {"sb1": parse_sb1, "sb2": parse_sb2, "sb3": parse_sb3}


def main() -> None:
    discover()
    print("== 抽取 ==")
    for box, src in SRC.items():
        text = (ANS / box / "r2" / src.name).read_text(encoding="utf-8")
        recs = PARSERS[box](text)
        out = {}
        for qid, r in recs.items():
            body = r["answer_text"]
            label = ""
            m = re.search(r"(?:判定|结论)\**\s*[：:]\s*(.+)", body)
            if m:
                label = m.group(1).strip().strip("*")[:60]
            out[qid] = {"box": box, "item_id": qid, "answer_text": body, "label": label,
                        "label_src": "正文判定行", "shared_block": r.get("shared_block"),
                        "group": r.get("group"),
                        "executed_claim": bool(EXEC_WORDS.search(label or "")),
                        "source": src.name}
        # 指针式作答: "与 RB-xx 逐字一致 / 同上" —— 模型自己声明内容就是那题的答案,
        # 若不承接, "同上" 会被当成一个独立的三字回答去判, 那是转写假象而不是作答差异。
        ptr = re.compile(r"(?:与|同)\s*(RB-[A-Z0-9]{2,3})\s*[^\n]{0,12}(逐字一致|同上|同答)")
        for qid, rec in list(out.items()):
            m = ptr.search(rec["answer_text"])
            if m and m.group(1) in out and m.group(1) != qid:
                rec["answer_text"] += f"\n\n［承接 {m.group(1)}：］" + out[m.group(1)]["answer_text"]
                rec["inherited_from"] = m.group(1)
        (OUT / f"{box}_r2_raw.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        shared = sorted({v["shared_block"] for v in out.values() if v["shared_block"]})
        print(f"  {box}: {len(out)} 题 | 合答块 {len(shared)} 个 {shared if shared else ''}")


if __name__ == "__main__":
    main()
