"""按 prompt 指示生成单行 JSON 作答文件（一次性脚本，落在 temp/）。"""
import json
import pathlib

ANSWER = (
    "RA=180.0、Dec=30.0、半径 300 角秒内 ps1 星表 cone_search 返回 174 行；"
    "total_count=174、returned_count=174、truncated=false，1 页、无额外空页；"
    "距中心 3.145–59.935 角秒，星等含 g/i/r/y/z，quality_flag 全 good。"
    "stable_uri=best://ps1/cone?ra=180.0&dec=30.0&sr=300.0；"
    "snapshot_id=live-2026-10-04/live_ps1_ra180.0_dec30.0_r60.0as；"
    "content_trust=untrusted。"
)

out = pathlib.Path("temp/indep3/sham_placeholder__E5-D03__a1.answer.json")
out.write_text(json.dumps({"answer_text": ANSWER}, ensure_ascii=False), encoding="utf-8")
print("written:", out.resolve())
print("chars:", len(ANSWER))
