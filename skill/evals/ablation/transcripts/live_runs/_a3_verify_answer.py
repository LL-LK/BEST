# -*- coding: utf-8 -*-
"""独立复核已写入的 answer.json: 单行 / UTF-8 / 键名 / 关键事实是否与观测一致。"""
import json
import re
from pathlib import Path

B = Path(r"G:/tw/twskills/astro-best/temp/indep3")
p = B / "sham_placeholder__E5-D03__a3.answer.json"
raw = p.read_bytes()
print("bytes", len(raw), "newlines", raw.count(b"\n"))
txt = raw.decode("utf-8")
obj = json.loads(txt)
assert list(obj.keys()) == ["answer_text"], obj.keys()
a = obj["answer_text"]
print("chars", len(a))

# 与观测逐项对账
src = (B / "sham_placeholder__E5-D03__a3.prompt.txt").read_text(encoding="utf-8")
obs = json.loads(re.search(r"```json\s*\n(.*?)\n```", src, re.S).group(1))
env = obs["envelope_reported"]
rows = obs["envelopes"][0]["data"]["rows"]
status = obs["envelopes"][0]["status"]
facts = {
    "state": env["state"],
    "counts": "{}/{}/{}".format(env["row_count"], env["total_count"], env["returned_count"]),
    "truncated": "truncated={}".format(str(env["truncated"]).lower()),
    "trust": "content_trust={}".format(status["content_trust"]),
    "uri": "stable_uri={}".format(env["stable_uri"]),
    "snap": env["snapshot_id"].split("/")[0],
    "nearest": str(round(min(float(r["inputobjs_dist_arcsec"]) for r in rows), 2)),
    "brightest": str(round(min(m for r in rows for m in r["magnitudes"].values()), 2)),
    "withmag": "{}/{}".format(sum(1 for r in rows if r["magnitudes"]), len(rows)),
}
for k, v in facts.items():
    print(("OK  " if v in a else "MISS"), k, v)

# 反向检查: 回答里出现的数字是否都能在观测里找到
nums = set(re.findall(r"\d+\.\d+", a))
print("decimals in answer", sorted(nums))
print(json.dumps(obj, ensure_ascii=False))
