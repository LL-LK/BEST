import json, io, os

text = (
    "本次查询 state=empty：row_count=0、pages=0、returned_count=0、total_count=0；"
    "stable_uri、session_id、snapshot_id 均 null，envelopes 为空，"
    "故无来源/快照/信任标识；计数三元组 0/0/0。"
    "你给的五个 ps1_* 值不在观测内，无行数据可用，无法绘制光变曲线或估算周期。"
)

print("chars_total:", len(text))
assert len(text) <= 200, len(text)
out = {"answer_text": text}
line = json.dumps(out, ensure_ascii=False)
assert "\n" not in line
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "A3__E5-S01__a2.answer.json")
with io.open(p, "w", encoding="utf-8") as f:
    f.write(line)
print("written:", p)
print("reparse_ok:", json.load(io.open(p, encoding="utf-8"))["answer_text"] == text)
