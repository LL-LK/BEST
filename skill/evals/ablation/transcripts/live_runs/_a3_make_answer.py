# -*- coding: utf-8 -*-
"""从本 prompt 文件里抽出「实际观测到的查询结果」JSON, 逐项核对后生成单行答案 JSON。

只读 prompt 文件, 只写 .answer.json; 不改动任何其它文件。
"""
import json
import re
from pathlib import Path

BASE = Path(r"G:/tw/twskills/astro-best/temp/indep3")
SRC = BASE / "sham_placeholder__E5-D03__a3.prompt.txt"
DST = BASE / "sham_placeholder__E5-D03__a3.answer.json"

raw = SRC.read_text(encoding="utf-8")

# 观测块位于 ```json ... ``` 之间 (文件中唯一一个该标记的围栏)
m = re.search(r"```json\s*\n(.*?)\n```", raw, re.S)
assert m, "未找到 json 围栏"
obs = json.loads(m.group(1))

env = obs["envelope_reported"]
assert env["state"] == "rows", env["state"]
rows = obs["envelopes"][0]["data"]["rows"]
status = obs["envelopes"][0]["status"]
prov = obs["envelopes"][0]["provenance"]

# 计数三元组自洽性核对
assert env["row_count"] == env["total_count"] == env["returned_count"] == 174, env
assert env["row_count"] == len(rows) == obs["n_rows_observed"], (len(rows), obs["n_rows_observed"])
assert status["truncated"] is False and env["truncated"] is False

# 关键列统计
mags = [r["magnitudes"] for r in rows]
bands = sorted({b for mm in mags for b in mm})
with_mag = sum(1 for mm in mags if mm)
dists = [float(r["inputobjs_dist_arcsec"]) for r in rows]
nearest = min(rows, key=lambda r: float(r["inputobjs_dist_arcsec"]))
brightest = min(
    ((r["magnitudes"][b], b, r["ra"], r["dec"]) for r in rows for b in r["magnitudes"]),
    key=lambda t: t[0],
)
catalogs = sorted({r["catalog"] for r in rows})
flags = sorted({r["quality_flag"] for r in rows})

facts = {
    "state": env["state"],
    "row_count": env["row_count"],
    "total_count": env["total_count"],
    "returned_count": env["returned_count"],
    "pages": env["pages"],
    "extra_page_empty": env["extra_page_empty"],
    "truncated": env["truncated"],
    "error_code": env["error_code"],
    "stable_uri": env["stable_uri"],
    "session_id": env["session_id"],
    "snapshot_id": env["snapshot_id"],
    "content_trust": status["content_trust"],
    "tool_face": env["tool_face"],
    "catalogs": catalogs,
    "quality_flags": flags,
    "bands": bands,
    "rows_with_any_magnitude": with_mag,
    "n_rows_len": len(rows),
    "dist_min": min(dists),
    "dist_max": max(dists),
    "nearest": {
        "ra": nearest["ra"],
        "dec": nearest["dec"],
        "dist": nearest["inputobjs_dist_arcsec"],
        "mag": nearest["magnitudes"],
    },
    "brightest": {"mag": brightest[0], "band": brightest[1], "ra": brightest[2], "dec": brightest[3]},
    "data_hash": prov["data_hash"],
    "lineage": prov["lineage"],
    "http_requests": obs["envelopes"][0]["cost"]["http_requests"],
    "elapsed_s": obs["envelopes"][0]["cost"]["elapsed_s"],
    "tool": obs["tool_calls"][0]["tool"],
    "args": obs["tool_calls"][0]["args"],
}
print(json.dumps(facts, ensure_ascii=False, indent=1))

# 组装回答正文 (全部数值来自上面的观测, 无外部数值)
# 优先级: 信封必写项 > 观测要点; 超 200 字时按优先级从尾部丢弃
env = facts
segments = [
    ("state", "state={}".format(env["state"])),
    ("error_code", "err={}".format("null" if env["error_code"] is None else env["error_code"])),
    ("counts", "计数{row}/{total}/{ret}".format(
        row=env["row_count"], total=env["total_count"], ret=env["returned_count"]
    )),
    ("pages", "pages={},extra_page_empty={}".format(env["pages"], str(env["extra_page_empty"]).lower())),
    ("truncated", "truncated={}".format(str(env["truncated"]).lower())),
    ("trust", "content_trust={}".format(env["content_trust"])),
    ("uri", "stable_uri={}".format(env["stable_uri"])),
    # 快照标识保留到 release 段 (live-2026-10-04), 尾部查询参数与 stable_uri 重复
    ("snapshot", "快照{}".format(env["snapshot_id"].split("/")[0])),
    ("session", "会话{}".format(env["session_id"])),
    ("tool_face", "tool_face={}".format(env["tool_face"])),
]
findings = [
    ("cone", "PS1锥形RA180/Dec30/300角秒"),
    ("nearest", "近源{}角秒i={}".format(round(facts["dist_min"], 2), round(facts["nearest"]["mag"]["i"], 2))),
    ("brightest", "最亮{}={}".format(facts["brightest"]["band"], round(facts["brightest"]["mag"], 2))),
    ("withmag", "{}/{}行有星等".format(facts["rows_with_any_magnitude"], facts["row_count"])),
    ("bands", "{}波段".format("/".join(facts["bands"]))),
    ("qflag", "quality_flag={}".format("/".join(facts["quality_flags"]))),
]
# 行数在计数三元组里已出现; 波段名是最次要的一项, 先丢
OPTIONAL_FINDINGS = {"bands", "qflag"}

REQUIRED = {"trust", "uri", "snapshot", "counts", "truncated", "state"}
optional_env = [s for s in segments if s[0] not in REQUIRED]
required_env = [s for s in segments if s[0] in REQUIRED]


def compose(opt_env, find):
    parts = [v for _, v in required_env] + [v for _, v in opt_env] + [v for _, v in find]
    return ";".join(parts)


# 先塞满: 必写 + 全部可选 + 全部要点; 超长时先丢可选信封项 (会话/页码/err),
# 再丢最次要的要点 (波段名), 保证观测要点不被整段砍掉
opt_env, find = list(optional_env), list(findings)
answer = compose(opt_env, find)
while len(answer) > 200 and opt_env:
    opt_env.pop()
    answer = compose(opt_env, find)
while len(answer) > 200 and find:
    find.pop()
    answer = compose(opt_env, find)
print("ENV_OPT", [k for k, _ in opt_env])
print("FIND", [k for k, _ in find])
print("LEN", len(answer))
for seg in answer.split(";"):
    print(len(seg), seg)

# 自洽核对: 回答里的关键事实与观测一致
for token in ("state=rows", "174", "untrusted", "best://ps1/cone", "truncated=false"):
    assert token in answer, token
assert len(answer) <= 200, len(answer)

DST.write_text(json.dumps({"answer_text": answer}, ensure_ascii=False), encoding="utf-8")
print(DST.read_text(encoding="utf-8"))
