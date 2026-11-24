"""固定 argv、会话绑定、空输出目录及无网 bwrap 网关。"""
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import subprocess
import sys
import threading
import uuid

raw=sys.stdin.buffer.read(65537)
if len(raw)>65536:raise SystemExit('E5_REQUEST_SIZE_DENIED')
request=json.loads(raw)
fields={'schema','protocol_sha256','cell_id','session_id','call_id','tool','arguments','state'}
if set(request)!=fields or request['schema']!='e5-domain-request-v1':raise SystemExit('E5_REQUEST_SCHEMA_DENIED')
for key in ('cell_id','session_id','call_id'):
    if not isinstance(request[key],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',request[key]):raise SystemExit('E5_ID_DENIED')
if not re.fullmatch(r'[0-9a-f]{64}',request['protocol_sha256']):raise SystemExit('E5_PROTOCOL_HASH_DENIED')
tools={'resolve_name','list_catalogs','describe_catalog','cone_search','crossmatch_batch','count','fetch_page',
       'best_submit','best_get_count','best_get_page','best_metadata','best_resolve','e5_fixture_square'}
if request['tool'] not in tools or not isinstance(request['arguments'],dict) or not isinstance(request['state'],dict):
    raise SystemExit('E5_TOOL_DENIED')
root=Path('<SANDBOX_HOME>/domain-calls')/hashlib.sha256((request['session_id']+'\0'+request['call_id']).encode()).hexdigest()
root.mkdir(parents=True,exist_ok=False)
(root/'input').mkdir();(root/'output').mkdir()
sentinel=socket.socket();sentinel.bind(('127.0.0.1',0));sentinel.listen(4);sentinel.settimeout(3)
port=sentinel.getsockname()[1]
resource.setrlimit(resource.RLIMIT_CPU,(30,30))
resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
resource.setrlimit(resource.RLIMIT_FSIZE,(32*1024*1024,32*1024*1024))
resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))
def serve():
    for _ in range(2):
        try:connection,_=sentinel.accept()
        except OSError:break
        with connection:connection.sendall(b'E5_SENTINEL')
threading.Thread(target=serve,daemon=True).start()
with socket.create_connection(('127.0.0.1',port),timeout=1) as connection:
    positive=connection.recv(32)==b'E5_SENTINEL'
if not positive:raise SystemExit('E5_SENTINEL_POSITIVE_FAILED')
bound={**request,'receipt_id':str(uuid.uuid4()),'parent_netns':os.readlink('/proc/self/ns/net'),'sentinel_port':port}
(root/'input/request.json').write_text(json.dumps(bound,ensure_ascii=False))
argv=['/usr/bin/bwrap','--unshare-all','--die-with-parent','--new-session','--clearenv',
      '--setenv','PATH','/usr/bin','--setenv','HOME','/nonexistent','--setenv','PYTHONNOUSERSITE','1',
      '--setenv','PYTHONDONTWRITEBYTECODE','1','--proc','/proc','--dev','/dev','--ro-bind','/usr','/usr',
      '--symlink','usr/bin','/bin','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64',
      '--ro-bind','/opt/e5/domain','/opt/e5/domain','--ro-bind','/opt/e5/runtime','/opt/e5/runtime',
      '--ro-bind','/opt/e5/data','/opt/e5/data','--ro-bind',str(root/'input'),'/input',
      '--bind',str(root/'output'),'/output','--chdir','/output',
      '/usr/bin/python3','/opt/e5/domain/domain_worker.py']
try:process=subprocess.run(argv,capture_output=True,timeout=40)
finally:sentinel.close()
(root/'stdout.bin').write_bytes(process.stdout);(root/'stderr.bin').write_bytes(process.stderr)
(root/'argv.json').write_text(json.dumps(argv))
if process.returncode!=0 or len(process.stdout)>32*1024*1024 or len(process.stderr)>1024*1024:
    print(json.dumps({'worker_exit_code':process.returncode,'stderr':process.stderr.decode('utf-8',errors='replace')[:4000]}))
    raise SystemExit(1)
worker=json.loads(process.stdout)
if worker['session_id']!=request['session_id'] or worker['call_id']!=request['call_id'] or not worker['boundary']['worker_boundary_pass']:
    raise SystemExit('E5_RECEIPT_BINDING_FAILED')
receipt={'schema':'e5-domain-gateway-receipt-v1','session_id':request['session_id'],'call_id':request['call_id'],
         'cell_id':request['cell_id'],'protocol_sha256':request['protocol_sha256'],'receipt_id':bound['receipt_id'],
         'request_sha256':hashlib.sha256(raw).hexdigest(),'argv_sha256':hashlib.sha256(json.dumps(argv,separators=(',',':')).encode()).hexdigest(),
         'gateway_uid':os.getuid(),'host_sentinel_positive_control':positive,'worker_exit_code':0,'worker':worker}
receipt['gateway_sha256']=hashlib.sha256(Path('/opt/e5/domain/domain_gateway.py').read_bytes()).hexdigest()
receipt['worker_sha256']=hashlib.sha256(Path('/opt/e5/domain/domain_worker.py').read_bytes()).hexdigest()
(root/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False))
print(json.dumps(receipt,ensure_ascii=False))
