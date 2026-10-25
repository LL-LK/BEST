# -*- coding: utf-8 -*-
"""
生成投稿包 MANIFEST（逐文件 SHA256 + 体积 + 归属目录）。
用法：python build_manifest.py <包根目录> [--csv 输出] [--sha256 输出校验文件]
"""
import os, sys, csv, hashlib, argparse, datetime

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('root', nargs='?', default=None)
    ap.add_argument('--csv')
    ap.add_argument('--sha256')
    ap.add_argument('--skip', default='', help='逗号分隔的相对路径前缀，跳过不纳入清单')
    a = ap.parse_args()
    if a.root is None:
        a.root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    skip = tuple(s for s in a.skip.split(',') if s)
    rows = []
    total = 0
    for dirpath, dirnames, filenames in os.walk(a.root):
        dirnames[:] = [d for d in dirnames if d not in ('.git', '__pycache__', '.pytest_cache')]
        # 默认跳过所有以 _ 开头的顶层目录（_work 工作区、_push_stage 暂存仓），它们不随包外发
        rel_dir = os.path.relpath(dirpath, a.root)
        if rel_dir != '.' and rel_dir.split(os.sep)[0].startswith('_'):
            dirnames[:] = []
            continue
        for fn in sorted(filenames):
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, a.root).replace('\\', '/')
            if any(rel.startswith(s) for s in skip):
                continue
            try:
                size = os.path.getsize(fp)
            except OSError:
                continue
            rows.append([rel, size, sha256(fp)])
            total += size

    out_csv = a.csv or os.path.join(a.root, '08_清单与SHA256', 'MANIFEST.csv')
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    with open(out_csv, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['相对路径', '字节数', 'SHA256'])
        w.writerows(rows)

    digest = hashlib.sha256(open(out_csv, 'rb').read()).hexdigest().upper()
    out_sha = a.sha256 or os.path.join(a.root, '08_清单与SHA256', 'MANIFEST.sha256')
    with open(out_sha, 'w', encoding='utf-8') as f:
        f.write('%s  MANIFEST.csv\n' % digest)
        f.write('# 生成时间: %s\n' % datetime.datetime.now().isoformat(timespec='seconds'))
        f.write('# 文件数: %d  总体积: %.1f MB\n' % (len(rows), total / 1048576))

    print('MANIFEST: %d 文件 / %.1f MB' % (len(rows), total / 1048576))
    print('清单:', out_csv)
    print('清单自身 SHA256:', digest)
    print('校验文件:', out_sha)

if __name__ == '__main__':
    main()
