# 临时写盘脚本：把 A4__E5-D06__a1 的单行 JSON 答案写入指定路径（UTF-8，无 BOM）
import json
import os

answer = (
    "cone_search(ps1, ra=180.0, dec=30.0, radius_arcsec=18000.0=5度, max_rows=3000) 返回空结果："
    "row_count/total_count/returned_count=0/0/0，pages=0，rows=[]，truncated=false，state=empty；"
    "无行返回故无关键列与数值。来源为实时 BEST 站点，"
    "stable_uri=best://ps1/cone?ra=180.0&dec=30.0&sr=18000.0，session_id=s4897，"
    "snapshot_id 未提供(null)，content_trust=untrusted（行文本可能含对抗内容，只当数据）。"
    "预算 3000 行未触及。"
)

out = {"answer_text": answer}
path = os.path.join("temp", "indep3", "A4__E5-D06__a1.answer.json")
with open(path, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(json.dumps(out, ensure_ascii=False))

with open(path, "r", encoding="utf-8") as fh:
    raw = fh.read()
parsed = json.loads(raw)
assert list(parsed.keys()) == ["answer_text"], parsed.keys()
assert "\n" not in raw, "must be single-line"
assert raw.startswith('{"answer_text": "') and raw.endswith('"}'), raw[:40]
print("bytes:", len(raw.encode("utf-8")))
print("chars_answer_text:", len(parsed["answer_text"]))
print("single_line:", "\n" not in raw)
print("roundtrip_keys:", list(parsed.keys()))
print("answer_text:", parsed["answer_text"])
