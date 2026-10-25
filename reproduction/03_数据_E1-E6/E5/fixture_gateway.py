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

raw=sys.stdin.buffer.read(4097)
if len(raw)>4096:raise SystemExit('request too large')
request=json.loads(raw)
if set(request) != {'schema','operation','value','session_id','call_id'} or request['schema'] != 'e5-fixture-request-v1' or request['operation'] != 'square_fixture' or request['value'] != 7:
    raise SystemExit('invalid finite fixture schema')
for name in ['session_id','call_id']:
    if not isinstance(request[name],str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,160}',request[name]):raise SystemExit('invalid binding ID')
root=Path('<SANDBOX_HOME>/fixture-calls')/hashlib.sha256((request['session_id']+'\0'+request['call_id']).encode()).hexdigest()
root.mkdir(parents=True,exist_ok=False)
(root/'input').mkdir()
(root/'output').mkdir()
(root/'outside-canary.txt').write_text(str(uuid.uuid4()))
sentinel=socket.socket()
sentinel.bind(('127.0.0.1',0)); sentinel.listen(4);sentinel.settimeout(4)
port=sentinel.getsockname()[1]
resource.setrlimit(resource.RLIMIT_CPU,(8,8))
resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
resource.setrlimit(resource.RLIMIT_FSIZE,(2*1024*1024,2*1024*1024))
resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
def serve():
    for _ in range(3):
        try:conn,_=sentinel.accept()
        except OSError:break
        with conn:conn.sendall(b'E5_SENTINEL')
thread=threading.Thread(target=serve,daemon=True);thread.start()
with socket.create_connection(('127.0.0.1',port),timeout=1) as conn:
    positive_control=conn.recv(32)==b'E5_SENTINEL'
if not positive_control:raise SystemExit('sentinel positive control failed')
bound={**request,'receipt_id':str(uuid.uuid4()),'parent_netns':os.readlink('/proc/self/ns/net'),'sentinel_port':port}
(root/'input/request.json').write_text(json.dumps(bound))
argv=['/usr/bin/bwrap','--unshare-all','--die-with-parent','--new-session','--clearenv','--setenv','PATH','/usr/bin','--setenv','HOME','/nonexistent','--setenv','PYTHONNOUSERSITE','1','--setenv','PYTHONDONTWRITEBYTECODE','1','--proc','/proc','--dev','/dev','--ro-bind','/usr','/usr','--symlink','usr/bin','/bin','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64','--ro-bind','/opt/e5','/opt/e5','--ro-bind',str(root/'input'),'/input','--bind',str(root/'output'),'/output','--chdir','/output','/usr/bin/python3','/opt/e5/fixture_worker.py']
try:
    process=subprocess.run(argv,capture_output=True,timeout=15)
finally:sentinel.close()
(root/'stdout.bin').write_bytes(process.stdout)
(root/'stderr.bin').write_bytes(process.stderr)
(root/'argv.json').write_text(json.dumps(argv))
if len(process.stdout)>1024*1024 or len(process.stderr)>1024*1024:raise SystemExit('output limit exceeded')
proof=json.loads(process.stdout) if process.returncode==0 else None
result={'schema':'e5-fixture-gateway-receipt-v1','session_id':request['session_id'],'call_id':request['call_id'],'receipt_id':bound['receipt_id'],'request_sha256':hashlib.sha256(raw).hexdigest(),'argv_sha256':hashlib.sha256(json.dumps(argv,separators=(',',':')).encode()).hexdigest(),'worker_sha256':hashlib.sha256(Path('/opt/e5/fixture_worker.py').read_bytes()).hexdigest(),'gateway_uid':os.getuid(),'host_sentinel_positive_control':positive_control,'worker_exit_code':process.returncode,'worker':proof,'stderr':process.stderr.decode('utf-8',errors='replace')}
(root/'receipt.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
raise SystemExit(0 if process.returncode==0 else 1)
