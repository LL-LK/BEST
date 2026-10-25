"""保留原题，串行补采真实公开响应；原始字节与文本派生件分开留证。"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

REPO = Path(r'<REPO_ROOT>')
OUT = Path(__file__).parent / 'public-recapture-01'
sys.path.insert(0, str(REPO))
from ops.live_fetch import RecordingSession, dump_snapshot, cone, proximity, _run_cone, _run_proximity
from src.client import BestClient

CASES = [
    ('D01_D10_D11_D12', cone('ps1', 180.0, 30.0, 5.0)),
    ('D02', cone('ps1', 180.0, 30.0, 60.0, sort='ps1_rpsf', order='asc')),
    ('D03', cone('ps1', 180.0, 30.0, 300.0)),
    ('D04_unfiltered', cone('ps1', 180.0, 30.0, 60.0)),
    ('D05_count_first', cone('ps1', 180.0, 30.0, 1800.0, max_records=1)),
    ('D06', cone('ps1', 180.0, 30.0, 18000.0, max_records=3000)),
    ('D07', cone('ps1', 180.0, 0.0, 60.0, max_records=1000, page_size=2)),
    ('D09', proximity('ps1', [(180.0,-30.0),(180.5,-30.5),(181.0,-31.0),(185.0,-35.0),(182.0,-32.0)], radius=5.0, nearest_only=True)),
]

class WireSession(RecordingSession):
    """请求限速、禁止 POST 重试，保存响应 content 字节；不保存 cookie。"""
    def __init__(self, path):
        super().__init__()
        self.trust_env = False
        self.path = path
        self.wire = []
        self.last_at = 0.0
    def request(self, method, url, **kwargs):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname != 'nadc.china-vo.org':
            raise ValueError('unexpected acquisition endpoint')
        if len(self.wire) >= 130:
            raise RuntimeError('acquisition request cap reached; partial material retained')
        time.sleep(max(0.0, 1.5-(time.monotonic()-self.last_at)))
        self.last_at = time.monotonic()
        started = datetime.now(timezone.utc).isoformat()
        resp = super().request(method, url, **kwargs)
        number = len(self.wire)+1
        name = f'wire/response-{number:03d}.bin'
        target = self.path/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(resp.content)
        form = kwargs.get('data')
        if isinstance(form, dict):
            form = {k: ('[REDACTED]' if 'csrf' in k.lower() or 'token' in k.lower() else v) for k,v in form.items()}
        self.wire.append({'method':method, 'url':resp.url, 'status':resp.status_code,
                          'request_form':form, 'started_at_utc':started,
                          'response_file':name, 'content_type':resp.headers.get('Content-Type'),
                          'content_encoding':resp.headers.get('Content-Encoding'),
                          'response_encoding':resp.encoding,
                          'bytes':len(resp.content), 'sha256':hashlib.sha256(resp.content).hexdigest()})
        return resp

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({'cases':CASES, 'out':str(OUT), 'logical_e5_units':0}, ensure_ascii=False, indent=2))
        return
    OUT.mkdir(exist_ok=False)
    results = []
    for case_id, task in CASES:
        folder = OUT / case_id
        folder.mkdir()
        session = WireSession(folder)
        client = BestClient(rate_limit=1.5, max_retries=0, timeout=45)
        old_session = client.session
        session.adapters = old_session.adapters.copy()
        old_session.close()
        client.session = session
        meta = {'page_size':task.get('page_size',1000), 'returned_count':0}
        error = None
        try:
            meta.update(_run_cone(client,task) if task['kind']=='cone' else _run_proximity(client,task))
        except Exception as exc:
            error = {'type':type(exc).__name__, 'message':str(exc)[:1000]}
        finally:
            client.close()
        if session.bodies:
            dump_snapshot(folder, task, session, meta)
        else:
            (folder/'capture_log.json').write_text(json.dumps({'task':task,'observed':meta,'request_log':session.log},indent=2),encoding='utf-8')
        # Client meta is observational evidence, never an independent gold oracle.
        receipt = {'schema':'e5-public-acquisition-v1','case_id':case_id,'task':task,
                   'logical_e5_units':0,'wire_responses':session.wire,'observed':meta,'error':error,
                   'byte_fidelity':'wire/*.bin stores requests Response.content; legacy CSV/HTML files are decoded UTF-8 derivatives',
                   'items_sha256':hashlib.sha256((REPO/'evals/ablation/items.yaml').read_bytes()).hexdigest()}
        (folder/'acquisition.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        results.append({'case_id':case_id,'observed':meta,'error':error,'responses':len(session.wire)})
        (OUT/'progress.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(results[-1],ensure_ascii=False),flush=True)
    (OUT/'COMPLETE.json').write_text(json.dumps({'logical_e5_units':0,'results':results},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__ == '__main__':
    main()
