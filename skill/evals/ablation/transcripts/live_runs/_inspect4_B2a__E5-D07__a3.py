# 临时检视脚本 4：按 GBK 解码指令段，并统计信任字段出现位置（只读）
import json
import re

p = r"G:/tw/twskills/astro-best/temp/indep3/B2a__E5-D07__a3.prompt.txt"
raw_bytes = open(p, "rb").read()
try:
    raw = raw_bytes.decode("utf-8")
    print("decoded as utf-8 ok")
except UnicodeDecodeError as exc:
    print("utf-8 failed:", exc)
    raw = raw_bytes.decode("gbk", errors="replace")
    print("decoded as gbk")

fence = "`" * 3
tail = raw.split(fence)[-1]
print("TAIL_START")
print(tail)
print("TAIL_END")

m = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.S)
doc = json.loads(m.group(1))

for key in ("content_trust", "snapshot_id", "sentinels_removed", "extra_page_empty",
            "stable_uri", "session_id", "data_hash", "lineage", "trust"):
    print(f"{key}: count={raw.count(key)}")

def walk(node, path="$"):
    if isinstance(node, dict):
        for k, v in node.items():
            yield path + "." + k, v
            yield from walk(v, path + "." + k)
    elif isinstance(node, list):
        for i, v in enumerate(node[:3]):
            yield from walk(v, f"{path}[{i}]")

keys = sorted({k.split(".")[-1] for k, _ in walk(doc)})
print("all_field_names_in_json:", keys)
print("has content_trust in json:", "content_trust" in keys)
print("has source in json:", "source" in keys)
