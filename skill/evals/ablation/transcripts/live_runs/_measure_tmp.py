"""临时: 量测候选答案字数, 供选取 ≤200 字的表述 (temp/ 下, 非入库)。"""
import io
import json

CANDIDATES = [
    'cone_search RA=180.0 Dec=30.0 r=5" ps1: total=3, returned=3, truncated=false, stable_uri 空, snapshot_id=null, 无 content_trust。3 源 179.999,29.9997 i=19.494; 180.001,29.9995 g=18.599; 180.000,29.9990 无测光',
    'cone_search RA=180.0 Dec=30.0 r=5" ps1: total=3, returned=3, truncated=false, stable_uri 空, snapshot_id=null, 无 content_trust。3 源 179.999,29.9997 i=19.494; 180.001,29.9995 g=18.599; 180.000,29.999 无测光',
    'cone_search RA=180.0 Dec=30.0 r=5" ps1: total=3, returned=3, truncated=false, stable_uri 空, snapshot_id=null, 无 content_trust。3 源: 179.999,29.9997 i=19.494; 180.001,29.9995 g=18.599; 180.000,29.999 无测光',
    'cone_search RA=180.0 Dec=30.0 r=5" ps1: total=3, returned=3, truncated=false, stable_uri 空, snapshot_id=null, 无 content_trust。3 源 179.99904,29.99973 i=19.494; 180.00110,29.99945 g=18.599; 180.00041,29.99895 无测光',
]

for idx, text in enumerate(CANDIDATES):
    print(idx, len(text))

with io.open('temp/indep3/cand.json', 'w', encoding='utf-8') as handle:
    json.dump([{'i': i, 'len': len(t), 'text': t} for i, t in enumerate(CANDIDATES)], handle, ensure_ascii=False, indent=1)
