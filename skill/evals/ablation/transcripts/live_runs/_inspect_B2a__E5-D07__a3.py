# 临时检视脚本：解析 prompt 文件中的观测结果，只读，不改写任何文件
import json
import re
import sys

p = r"G:/tw/twskills/astro-best/temp/indep3/B2a__E5-D07__a3.prompt.txt"
raw = open(p, encoding="utf-8").read()
print("file_chars:", len(raw))
print("has_fence:", "```json" in raw)
print("occurrences of 'envelope_reported':", raw.count("envelope_reported"))
print("occurrences of 'tool_face':", raw.count("tool_face"))
print("occurrences of 'stable_uri':", raw.count("stable_uri"))

m = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.S)
print("fence_json_found:", bool(m))
if not m:
    sys.exit("no fenced json")

doc = json.loads(m.group(1))
print("top_keys:", list(doc.keys()))
print("route:", doc.get("route"))
print("tool_calls:", json.dumps(doc.get("tool_calls"), ensure_ascii=False))
er = doc.get("envelope_reported")
print("envelope_reported:", json.dumps(er, ensure_ascii=False, sort_keys=True))

envs = doc.get("envelopes") or []
print("n_envelopes:", len(envs))
for i, e in enumerate(envs):
    d = e.get("data") or {}
    rows = d.get("rows") or []
    print(f"env[{i}] keys={sorted(e.keys())} data_keys={sorted(d.keys())} n_rows={len(rows)}")
    print(f"   status={json.dumps(e.get('status'), ensure_ascii=False, sort_keys=True)}")
    print(f"   cost={json.dumps(e.get('cost'), ensure_ascii=False, sort_keys=True)}")
    print(f"   provenance={json.dumps(e.get('provenance'), ensure_ascii=False, sort_keys=True)}")
    print(f"   data.total_count={d.get('total_count')} data.returned_count={d.get('returned_count')}")

allrows = []
for e in envs:
    allrows.extend(((e.get("data") or {}).get("rows")) or [])
print("total_rows_all_envelopes:", len(allrows))

if allrows:
    decs = [r.get("dec") for r in allrows]
    ras = [r.get("ra") for r in allrows]
    inp_dec = sorted({str(r.get("inputobjs_input_dec")) for r in allrows})
    inp_ra = sorted({str(r.get("inputobjs_input_ra")) for r in allrows})
    inp_line = sorted({str(r.get("inputobjs_input_line")) for r in allrows})
    print("ra_range:", min(ras), max(ras))
    print("dec_range:", min(decs), max(decs))
    print("distinct input_dec:", inp_dec)
    print("distinct input_ra:", inp_ra)
    print("distinct input_line:", inp_line)
    print("row_keys:", sorted(allrows[0].keys()))
    print("catalogs:", sorted({str(r.get("catalog")) for r in allrows}))
    print("first_row:", json.dumps(allrows[0], ensure_ascii=False, sort_keys=True)[:600])
    print("row0_fields_present_in_all:",
          sorted(set.intersection(*[set(r.keys()) for r in allrows])))
    print("inputobjs_dist_arcsec_range:",
          min(float(r["inputobjs_dist_arcsec"]) for r in allrows),
          max(float(r["inputobjs_dist_arcsec"]) for r in allrows))
