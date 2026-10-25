import json, io

answer = (
    "B1 工具面 none，无数据通路，无法查询该源 BEST ZTF g/r/i 星等。"
    "观测：tool_calls 空；envelope=empty，error_code=null，行数/页数/服务端总数/返回数=0，"
    "truncated=false；stable_uri=session_id=snapshot_id=null，"
    "无来源、稳定引用、content_trust、快照标识。零行未截断。"
)

print("char_len =", len(answer))
assert len(answer) <= 200, f"too long: {len(answer)}"

path = "temp/indep3/B1__E5-C01__a3.answer.json"
payload = json.dumps({"answer_text": answer}, ensure_ascii=False)
with io.open(path, "w", encoding="utf-8", newline="") as fh:
    fh.write(payload)

# 回读校验
with io.open(path, "rb") as fh:
    raw_bytes = fh.read()
raw = raw_bytes.decode("utf-8")
print("bytes =", len(raw_bytes))
print("bom =", raw_bytes[:3] == b"\xef\xbb\xbf")
print("newline_count =", raw.count("\n"), "| cr_count =", raw.count("\r"))
back = json.loads(raw)
print("keys =", list(back.keys()))
print("roundtrip_len =", len(back["answer_text"]))
print("identical =", back["answer_text"] == answer)
print("answer =", back["answer_text"])
