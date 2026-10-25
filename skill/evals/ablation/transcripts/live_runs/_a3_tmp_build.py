# -*- coding: utf-8 -*-
"""临时构造脚本: 生成 A3 独立作答的单行 JSON (仅依据 prompt 内观测信封)。"""
import json
import pathlib

text = (
    "ps1 锥形搜索(RA=180.0,Dec=0.0,60″)及 page=2(每页2行)均空:"
    "总/返回/行数=0/0/0,truncated=false,pages=0,无关键列数值。"
    "stable_uri=best://ps1/cone?ra=180.0&dec=0.0&sr=60.0,"
    "快照 live-2026-10-04/live_ps1_ra180.0_dec30.0_r120.0as,"
    "会话 s4926,content_trust=untrusted,http_requests=0。"
)

if len(text) > 200:
    text = (
        "ps1 锥形搜索(RA=180.0,Dec=0.0,60″)与 page=2(每页2行)均空:"
        "总/返回/行数=0/0/0,truncated=false,pages=0,无关键列数值。"
        "stable_uri=best://ps1/cone?ra=180.0&dec=0.0&sr=60.0,"
        "快照 live-2026-10-04/live_ps1_ra180.0_dec30.0_r120.0as,"
        "会话 s4926,content_trust=untrusted,http_requests=0。"
    )

out = pathlib.Path(r"<SKILLS_ROOT>\astro-best\temp\indep3\A3__E5-D07__a3.answer.json")
payload = json.dumps({"answer_text": text}, ensure_ascii=False, separators=(",", ":"))
out.write_text(payload + "\n", encoding="utf-8")

print("char_len", len(text))
print("non_ascii", sum(1 for c in text if ord(c) >= 128))
print("bytes", out.stat().st_size)
back = json.loads(out.read_text(encoding="utf-8"))
print("roundtrip_ok", back["answer_text"] == text)
print("keys", list(back.keys()))
