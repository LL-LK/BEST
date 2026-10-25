import json

answer = (
    "PS1 锥搜索 sr=60″：174行，total=returned=174，truncated=false；按 ps1_rpsf 升序，"
    "39行有有效 r 星等（18.2007–22.6834），135行缺失（≈-1003.88）。"
    "stable_uri=best://ps1/cone?ra=180.0&dec=30.0&sr=60.0，s4909，"
    "content_trust=untrusted。"
)

print('chars:', len(answer))
assert len(answer) <= 200, len(answer)

out = r'G:/tw/twskills/astro-best/temp/indep3/A4__E5-D02__a3.answer.json'
with open(out, 'w', encoding='utf-8', newline='\n') as f:
    f.write(json.dumps({'answer_text': answer}, ensure_ascii=False))
    f.write('\n')

raw = open(out, encoding='utf-8').read()
print('file lines:', len(raw.rstrip('\n').splitlines()))
print('roundtrip ok:', json.loads(raw)['answer_text'] == answer)
print('bytes:', len(raw.encode('utf-8')))
