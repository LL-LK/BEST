"""仅调用固定领域函数；先验隔离证据失败时不执行生产 SUT。"""
import hashlib
import json
import os
from pathlib import Path
import socket
import sys

request=json.loads(Path('/input/request.json').read_text())
interfaces=[line.split(':')[0].strip() for line in Path('/proc/net/dev').read_text().splitlines()[2:]]
routes=Path('/proc/net/route').read_text().splitlines()[1:]
checks={'input_readable':True,'repo_hidden':not Path('/mnt/g/tw/twskills/astro-best').exists(),
        'gold_hidden':not Path('/mnt/d/E5-v4-20261012-02/private').exists(),
        'other_sessions_hidden':not Path('<SANDBOX_HOME>/domain-calls').exists(),
        'network_namespace_isolated':os.readlink('/proc/self/ns/net')!=request['parent_netns'],
        'no_default_route':not any(line.split()[1]=='00000000' for line in routes),
        'no_external_interface':set(interfaces).issubset({'lo'}),
        'credentials_absent':not any('TOKEN' in k.upper() or 'CREDENTIAL' in k.upper() or 'API_KEY' in k.upper() for k in os.environ),
        'input_readonly':False,'runtime_readonly':False,'snapshots_readonly':False,
        'output_writable':False,'sentinel_blocked':False}
for key,file in [('input_readonly','/input/request.json'),('runtime_readonly','/opt/e5/runtime/src/ai_tools.py'),('snapshots_readonly','/opt/e5/data/bundle.json')]:
    try:
        with open(file,'ab') as stream:stream.write(b'tamper')
    except OSError:checks[key]=True
try:
    Path('/output/positive-write.txt').write_text('allowed')
    checks['output_writable']=True
except OSError:pass
try:
    with socket.create_connection(('127.0.0.1',request['sentinel_port']),timeout=.4) as sock:sock.recv(32)
except OSError:checks['sentinel_blocked']=True
proof={'uid':os.getuid(),'netns':os.readlink('/proc/self/ns/net'),'checks':checks,
       'worker_boundary_pass':all(checks.values()),'mountinfo':Path('/proc/self/mountinfo').read_text()}
Path('/output/boundary-proof.json').write_text(json.dumps(proof,indent=2))
if not proof['worker_boundary_pass']:raise SystemExit('E5_WORKER_BOUNDARY_FAILED')
sys.path[:0]=['/opt/e5/domain','/opt/e5/runtime','/opt/e5/runtime/vendor']
from frozen_backend import invoke
import requests
bundle=json.loads(Path('/opt/e5/data/bundle.json').read_text())
state=request['state']
error=None
try:
    result,state,log=invoke(bundle,state,request['session_id'],request['tool'],request['arguments'])
except (ValueError,TypeError,PermissionError,KeyError,requests.RequestException) as exc:
    result=None;log=[];error={'type':type(exc).__name__,'message':str(exc)[:2000]}
value={'schema':'e5-domain-worker-result-v1','session_id':request['session_id'],'call_id':request['call_id'],
       'cell_id':request['cell_id'],'protocol_sha256':request['protocol_sha256'],'receipt_id':request['receipt_id'],
       'tool':request['tool'],'arguments':request['arguments'],'result':result,'tool_error':error,
       'state':state,'transport_log':log,'boundary':proof,
       'public_bundle_sha256':hashlib.sha256(Path('/opt/e5/data/bundle.json').read_bytes()).hexdigest()}
value['sut_toolbox_sha256']=hashlib.sha256(Path('/opt/e5/runtime/src/ai_tools.py').read_bytes()).hexdigest()
value['frozen_backend_sha256']=hashlib.sha256(Path('/opt/e5/domain/frozen_backend.py').read_bytes()).hexdigest()
Path('/output/result.json').write_text(json.dumps(value,ensure_ascii=False))
print(json.dumps(value,ensure_ascii=False))
