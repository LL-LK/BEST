# -*- coding: utf-8 -*-
"""按 B2a__E5-D01__a2.prompt.txt 的观测信封生成单行 JSON 作答 (只读本 prompt 文件)。"""
import json
import pathlib

text = (
    "ps1 锥形搜索 RA=180.0 Dec=30.0 r=5″（raw_protocol）：state=rows，"
    "error_code=null；行数=total_count=3，pages=1，truncated=false。"
    "三源距离 3.145/3.961/3.982″；i=19.494±0.146、g=18.599±0.010，第三源无测光。"
    "stable_uri=null，无内容信任字段。"
)
print("len:", len(text))
assert len(text) <= 200, len(text)

payload = json.dumps({"answer_text": text}, ensure_ascii=False)
assert "\n" not in payload
out = pathlib.Path(r"G:/tw/twskills/astro-best/temp/indep3/B2a__E5-D01__a2.answer.json")
out.write_text(payload, encoding="utf-8")

raw = out.read_text(encoding="utf-8")
back = json.loads(raw)
print("keys:", list(back))
print("roundtrip_ok:", back["answer_text"] == text)
print("single_line:", "\n" not in raw)
print("text:", back["answer_text"])
