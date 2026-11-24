import json
import os
import pathlib
import socket
import sys

request=json.loads(pathlib.Path('/input/request.json').read_text())
if request['operation'] != 'square_fixture' or request['value'] != 7:
    raise SystemExit('unsupported fixture operation')
interfaces=[line.split(':')[0].strip() for line in pathlib.Path('/proc/net/dev').read_text().splitlines()[2:]]
routes=pathlib.Path('/proc/net/route').read_text().splitlines()[1:]
proof={
    'public_input_readable':True,
    'outside_sibling_hidden':not pathlib.Path('/input/../outside-canary.txt').exists(),
    'repo_answer_key_hidden':not pathlib.Path('/mnt/g/tw/twskills/astro-best/evals/ablation/items.yaml').exists(),
    'private_mount_hidden':not pathlib.Path('/mnt/d/E5-v4-20261012-02/private/items.yaml').exists(),
    'network_namespace_isolated':os.readlink('/proc/self/ns/net') != request['parent_netns'],
    'network_no_default_route':not any(line.split()[1]=='00000000' for line in routes),
    'network_no_external_interface':set(interfaces).issubset({'lo'}),
    'input_write_denied':False,
    'output_write_allowed':False,
    'controlled_host_sentinel_blocked':False,
}
try:pathlib.Path('/input/request.json').write_text('tamper')
except OSError:proof['input_write_denied']=True
try:
    pathlib.Path('/output/positive-write.txt').write_text('allowed')
    proof['output_write_allowed']=True
except OSError:pass
try:
    with socket.create_connection(('127.0.0.1',request['sentinel_port']),timeout=.7) as sock:
        sock.recv(32)
except OSError:proof['controlled_host_sentinel_blocked']=True
result={'schema':'e5-fixture-worker-v1','value':49,'uid':os.getuid(),'call_id':request['call_id'],'session_id':request['session_id'],'receipt_id':request['receipt_id'],'netns':os.readlink('/proc/self/ns/net'),'interfaces':interfaces,'checks':proof,'worker_boundary_pass':all(proof.values()),'mountinfo':pathlib.Path('/proc/self/mountinfo').read_text()}
pathlib.Path('/output/worker-proof.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
raise SystemExit(0 if result['worker_boundary_pass'] else 1)
