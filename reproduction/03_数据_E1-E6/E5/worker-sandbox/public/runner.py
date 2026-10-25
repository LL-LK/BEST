import json, os, pathlib, socket, sys
prompt = pathlib.Path('/input/task.txt')
host, port, parent_netns = sys.argv[1], int(sys.argv[2]), sys.argv[3]
net_dev = pathlib.Path('/proc/net/dev').read_text()
interfaces = [line.split(':', 1)[0].strip() for line in net_dev.splitlines()[2:] if ':' in line]
routes = pathlib.Path('/proc/net/route').read_text().splitlines()[1:]
has_default_route = any(line.split()[1] == '00000000' for line in routes if len(line.split()) > 1)
proof = {
    'public_input_readable': prompt.is_file() and 'E5 public input' in prompt.read_text(),
    'outside_sibling_visible': pathlib.Path('/input/../outside-canary.txt').exists(),
    'repo_answer_key_visible': pathlib.Path('/mnt/g/tw/twskills/astro-best/evals/ablation/items.yaml').exists(),
    'traversal_answer_key_visible': pathlib.Path('/input/../../mnt/g/tw/twskills/astro-best/evals/ablation/items.yaml').exists(),
    'input_write_denied': False, 'output_write_allowed': False, 'network_egress_denied': False,
    'uid': os.getuid(), 'mountinfo': pathlib.Path('/proc/self/mountinfo').read_text(),
    'network_namespace': os.readlink('/proc/self/ns/net'),
    'parent_network_namespace': parent_netns,
    'network_interfaces': interfaces,
    'has_default_route': has_default_route,
    'net_dev': net_dev,
}
try:
    prompt.write_text('tamper')
except OSError:
    proof['input_write_denied'] = True
try:
    pathlib.Path('/output/proof.json').write_text('{}')
    proof['output_write_allowed'] = True
except OSError:
    pass
sock = socket.socket(); sock.settimeout(0.5)
try:
    sock.connect(('198.51.100.1', 80))
except OSError as exc:
    proof['network_egress_denied'] = True
    proof['network_error'] = type(exc).__name__ + ': ' + str(exc)
finally:
    sock.close()
try:
    with socket.create_connection((host, port), timeout=0.7) as controlled:
        proof['controlled_host_sentinel_reached'] = controlled.recv(64).decode('ascii', 'replace') == 'E5_SENTINEL'
except OSError as exc:
    proof['controlled_host_sentinel_reached'] = False
    proof['controlled_host_sentinel_error'] = type(exc).__name__ + ': ' + str(exc)
pathlib.Path('/output/proof.json').write_text(json.dumps(proof, indent=2))
print(json.dumps({k: v for k, v in proof.items() if k not in ('mountinfo', 'net_dev')}, indent=2))
