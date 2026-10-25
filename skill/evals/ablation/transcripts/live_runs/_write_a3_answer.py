import json, io

answer = (
    "本装配 B1 工具面为 none，无数据通路，无法查询 Gaia DR3 1234567890123456789 的 BEST ZTF g/r/i 星等。"
    "实际观测：tool_calls 为空；envelope 状态 empty，error_code=null，row_count=0，pages=0，"
    "total_count=0，returned_count=0，truncated=false，extra_page_empty=false，sentinels_removed=false，"
    "tool_face=scripted；envelopes 空，n_rows_observed=0，row_keys 空，first_row 空。"
    "stable_uri、session_id、snapshot_id 均 null，故无来源、稳定引用、content_trust 与快照标识。"
    "结论：零行、未截断，无星等数值可报。"
)

print("char_len =", len(answer))
assert len(answer) <= 200, f"too long: {len(answer)}"

payload = json.dumps({"answer_text": answer}, ensure_ascii=False)
path = "temp/indep3/B1__E5-C01__a3.answer.json"
with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(payload)

# verify round-trip
with io.open(path, "r", encoding="utf-8") as fh:
    raw = fh.read()
print("newline_count =", raw.count("\n"), "| cr_count =", raw.count("\r"))
back = json.loads(raw)
print("keys =", list(back.keys()))
print("roundtrip_len =", len(back["answer_text"]))
print("ends_with_newline =", raw.endswith("\n"))
print("has_cr =", "\r" in raw)
