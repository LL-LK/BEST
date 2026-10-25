# 临时检视脚本 3：读取 fenced json 之后的指令文本，并检查信任相关字段（只读）
p = r"G:/tw/twskills/astro-best/temp/indep3/B2a__E5-D07__a3.prompt.txt"
raw = open(p, encoding="utf-8").read()
fence = "`" * 3
tail = raw.split(fence)[-1]
print("TAIL_START")
print(tail)
print("TAIL_END")
for key in ("content_trust", "snapshot_id", "sentinels_removed", "extra_page_empty",
            "stable_uri", "session_id", "data_hash", "lineage", "source", "trust"):
    print(f"{key}: count={raw.count(key)}")
