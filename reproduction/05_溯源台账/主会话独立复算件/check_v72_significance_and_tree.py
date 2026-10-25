# -*- coding: utf-8 -*-
"""检查 v72 补充材料里是否存在 E5 相关显著性表述，并汇总落盘情况。"""
import re, os, sys, json
sys.stdout.reconfigure(encoding='utf-8')

SUP = r"<WORKSPACE>\10_脱敏复现包\BEST_v72_图2嵌入正文确认_20261023\source\supplementary_material.tex"
MAIN = r"<WORKSPACE>\10_脱敏复现包\BEST_v72_图2嵌入正文确认_20261023\source\main.tex"

for tag, path in (('supplementary', SUP), ('main', MAIN)):
    s = open(path, 'rb').read().decode('utf-8')
    print('=' * 20, tag, '=' * 20)
    hits = []
    for i, line in enumerate(s.split('\n'), 1):
        if re.search(r'(0\.6358|0\.09625|0\.0885|Holm|符号翻转|显著|McNemar|\$p=|p=0\.)', line):
            t = line.strip()
            if len(t) > 12:
                hits.append((i, t[:230]))
    for i, t in hits:
        print(f'{i}: {t}')
    print('命中行数:', len(hits))
    print()

# 投稿包当前落盘情况
ROOT = r"<WORKSPACE>\11_投稿包"
print('=' * 20, '11_投稿包 落盘情况', '=' * 20)
total_files = 0
total_bytes = 0
for dirpath, dirnames, filenames in os.walk(ROOT):
    for fn in filenames:
        total_files += 1
        try:
            total_bytes += os.path.getsize(os.path.join(dirpath, fn))
        except OSError:
            pass
print('文件数:', total_files, '  体积: %.1f MB' % (total_bytes / 1048576))
for dirpath, dirnames, filenames in os.walk(ROOT):
    rel = os.path.relpath(dirpath, ROOT)
    depth = 0 if rel == '.' else rel.count(os.sep) + 1
    if depth <= 3:
        print('  ' * depth + os.path.basename(dirpath) + '/', f'({len(filenames)} 文件)')
