# 临时检视脚本 2：读取 prompt 文件 JSON 的其余顶层字段（只读）
import json
import re

p = r"G:/tw/twskills/astro-best/temp/indep3/B2a__E5-D07__a3.prompt.txt"
raw = open(p, encoding="utf-8").read()
m = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.S)
doc = json.loads(m.group(1))

print("n_rows_observed:", json.dumps(doc.get("n_rows_observed"), ensure_ascii=False))
print("row_keys_type:", type(doc.get("row_keys")).__name__, "len:",
      len(doc.get("row_keys") or []))
print("row_keys:", json.dumps(doc.get("row_keys"), ensure_ascii=False)[:800])
print("notes:", json.dumps(doc.get("notes"), ensure_ascii=False, indent=1)[:4000])
fr = doc.get("first_row")
print("first_row_is_dict:", isinstance(fr, dict))
if isinstance(fr, dict):
    print("first_row_keys:", sorted(fr.keys()))

# 距离分布：有多少行超过 60 角秒
rows = []
for e in doc.get("envelopes") or []:
    rows.extend(((e.get("data") or {}).get("rows")) or [])
d = [float(r["inputobjs_dist_arcsec"]) for r in rows]
print("n_rows:", len(d), "<=60:", sum(1 for x in d if x <= 60.0), ">60:", sum(1 for x in d if x > 60.0))
print("min/max dist:", min(d), max(d))

# 页大小语义：请求 page_size=2，实际返回行数
print("requested page_size:", doc["tool_calls"][1]["args"]["page_size"])
print("requested max_rows:", doc["tool_calls"][0]["args"]["max_rows"])
print("env row counts:", [len(((e.get('data') or {}).get('rows')) or []) for e in doc.get("envelopes") or []])

# 尾部原始文本（fenced json 之外的内容）
tail = raw.split("```")[-1]
print("tail_after_fence_repr:", repr(tail[-1200:]))
