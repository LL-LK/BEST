import json, io

answer = (
    "ps1 3行 total=ret=3,未截断;"
    "best://ps1/cone?ra=180.0&dec=30.0&sr=5.0;"
    "live_ps1_ra180.0_dec30.0_r5.0as;trust=untrusted。"
    "1)179.999042,29.999727,i19.49;"
    "2)180.001103,29.999454,g18.60;"
    "3)180.000408,29.998952,无光度值"
)

print("char_len =", len(answer))
assert len(answer) <= 200, f"too long: {len(answer)}"

payload = json.dumps({"answer_text": answer}, ensure_ascii=False)
assert "\n" not in payload and "\r" not in payload, "must be single line"
path = "temp/indep3/sham_placeholder__E5-D01__a3.answer.json"
with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(payload)

with io.open(path, "r", encoding="utf-8") as fh:
    raw = fh.read()
back = json.loads(raw)
print("keys =", list(back.keys()))
print("roundtrip_len =", len(back["answer_text"]))
print("identical =", back["answer_text"] == answer)
print("newline_count =", raw.count("\n"), "| cr_count =", raw.count("\r"))
print("RAW:", raw)
