# 生成答案文件：严格依据观测到的 envelope_reported 与行数据（写入目标答案文件）
import json

answer = (
    "已按 ps1 两阶段协议执行 cone_search(ra=180.0, dec=0.0, radius=60″, max_rows=100) "
    "与 fetch_page(page=2, page_size=2)。计数三元组：row_count=770、pages=0、"
    "returned_count=0；信封未标截断（truncated=false、error_code=null、state=rows）。"
    "实际两枚信封共 770 行：首封 0 行，次封 770 行，无续页。"
    "stable_uri 为空串，session_id=s4926，snapshot_id=null，content_trust 字段未出现，"
    "tool_face=raw_protocol。行内 ra/dec 落在 179.962–180.037、29.967–30.033，"
    "input_dec 全为 30.0（非请求的 0.0）；dist 3.145–119.995″，其中 174 行 ≤60″、596 行 >60″。"
    "关键列：ra、dec、magnitudes(g/r/i/z/y)、quality_flag、ps1_*flags/psf。"
)

out = {"answer_text": answer}
dst = r"G:/tw/twskills/astro-best/temp/indep3/B2a__E5-D07__a3.answer.json"
with open(dst, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(json.dumps(out, ensure_ascii=False))

# 自检
with open(dst, encoding="utf-8") as fh:
    text = fh.read()
print("bytes:", len(text.encode("utf-8")))
print("lines:", text.count("\n") + 1)
print("is_single_line:", "\n" not in text)
parsed = json.loads(text)
print("keys:", list(parsed.keys()))
body = parsed["answer_text"]
print("answer_chars:", len(body))
cjk = sum(1 for ch in body if "\u4e00" <= ch <= "\u9fff")
print("cjk_chars:", cjk)
print("within_200_cjk:", cjk <= 200)
print("ASCII_HEAD:", text[:60])
print("ASCII_TAIL:", text[-60:])
