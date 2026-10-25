# -*- coding: utf-8 -*-
"""校验 A3 作答文件: 单行 JSON、键名、字符数。"""
import json
import pathlib

p = pathlib.Path(r"<SKILLS_ROOT>\astro-best\temp\indep3\A3__E5-D07__a3.answer.json")
raw = p.read_text(encoding="utf-8")
obj = json.loads(raw)
text = obj["answer_text"]
print("keys", list(obj.keys()))
print("char_len", len(text))
print("non_ascii", sum(1 for c in text if ord(c) >= 128))
print("ascii", sum(1 for c in text if ord(c) < 128))
print("physical_lines", len(raw.rstrip("\n").split("\n")))
print("bytes", p.stat().st_size)
for k in ("stable_uri", "content_trust", "live-2026-10-04", "s4926", "truncated=false", "pages=0"):
    print(k, k in text)
print("---")
print(text)
