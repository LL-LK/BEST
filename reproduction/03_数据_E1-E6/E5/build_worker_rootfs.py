"""Create a minimal WSL worker image from public installed Linux binaries only."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

output = Path('/mnt/d/E5-v4-20261012-02/public/e5-worker-rootfs.tar')
if output.exists():
    raise SystemExit('refuse overwriting worker rootfs')
root = Path(tempfile.mkdtemp(prefix='e5-worker-rootfs-'))
for directory in ('usr/bin', 'usr/lib', 'usr/lib64', 'etc', 'tmp', 'root', 'home/e5', 'dev', 'proc', 'sys', 'run', 'var', 'mnt', 'opt/e5'):
    (root / directory).mkdir(parents=True, exist_ok=True)
for link, target in [('bin','usr/bin'), ('lib','usr/lib'), ('lib64','usr/lib64')]:
    (root / link).symlink_to(target, target_is_directory=True)
os.chmod(root / 'tmp', 0o1777)
os.chown(root / 'home/e5', 1000, 1000)
sources = set()
for binary in ('/usr/bin/python3', '/usr/bin/bwrap', '/usr/bin/readlink', '/usr/bin/id', '/usr/bin/env', '/usr/bin/sh'):
    source = Path(binary)
    real = source.resolve()
    sources.add(real)
    proc = subprocess.run(['/usr/bin/ldd', str(real)], capture_output=True, text=True, check=True)
    for path in re.findall(r'(/\S+)', proc.stdout):
        library = Path(path)
        if library.is_file():
            sources.add(library)
    dest = root / source.relative_to('/')
    if source != real:
        dest.symlink_to(str(real))
for source in sources:
    dest = root / source.relative_to('/')
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source.resolve(), dest)
stdlib = Path('/usr/lib/python' + '.'.join(map(str, sys.version_info[:2])))
shutil.copytree(stdlib, root / stdlib.relative_to('/'), symlinks=False)
(root / 'usr/bin/wslpath').symlink_to('/init')
(root / 'etc/passwd').write_text('root:x:0:0:root:/root:/usr/bin/sh\ne5:x:1000:1000:E5 worker:<SANDBOX_HOME>:/usr/bin/sh\n')
(root / 'etc/group').write_text('root:x:0:\ne5:x:1000:\n')
(root / 'etc/wsl.conf').write_text('[user]\ndefault=e5\n[boot]\nsystemd=false\n[interop]\nenabled=false\nappendWindowsPath=false\n')
(root / 'etc/os-release').write_text('ID=e5-minimal\nNAME="E5 minimal isolated worker"\n')
manifest = {'schema':'e5-minimal-worker-image-v1', 'python':sys.version.split()[0], 'copied_binaries':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(sources)}, 'home_copied':False,'credentials_copied':False,'repo_copied':False}
(root / 'opt/e5/image-manifest.json').write_text(json.dumps(manifest,indent=2))
with tarfile.open(output, 'x') as archive:
    for child in sorted(root.iterdir()):
        archive.add(child,arcname=child.name)
manifest['tar_sha256']=hashlib.sha256(output.read_bytes()).hexdigest()
manifest['tar_bytes']=output.stat().st_size
with (output.parent / 'e5-worker-rootfs.manifest.json').open('x') as stream:
    json.dump(manifest,stream,indent=2)
print(json.dumps(manifest,indent=2))
