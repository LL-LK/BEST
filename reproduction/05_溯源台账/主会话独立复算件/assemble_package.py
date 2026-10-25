# -*- coding: utf-8 -*-
"""
组装 BEST-Skill 投稿包（<WORKSPACE>\\11_投稿包\\）。
原则：只复制与新增，绝不移动或删除 <WORKSPACE> 的 01–10 原始目录内容。
大体积原始归档（*.tar.gz、原始证据 zip）不复制，改为在 08_清单与SHA256 里写 MANIFEST 指针。
"""
import os, shutil, hashlib, json, sys, zipfile, datetime
sys.stdout.reconfigure(encoding='utf-8')

ROOT = r"<WORKSPACE>"
PKG = os.path.join(ROOT, "11_投稿包")
V72 = os.path.join(ROOT, r"10_脱敏复现包\BEST_v72_图2嵌入正文确认_20261023")
V55 = os.path.join(ROOT, r"10_脱敏复现包\BEST_v55_实验更新_20261020\BEST_v55")
DESENS = os.path.join(ROOT, "10_脱敏复现包")

# 不复制的大文件后缀（改用 MANIFEST 指针）
SKIP_SUFFIX = (".tar.gz",)
SKIP_NAMES = ("original-evidence.tar.gz",
              "E6-R3-supplement-20261011-1791689271010679000-原始证据.zip",
              "六个实验最小复现包_脱敏版_20261013.zip")

manifest_log = []
copied = {"files": 0, "bytes": 0}
skipped = []


def ensure(d):
    os.makedirs(d, exist_ok=True)


def copy_tree(src, dst, skip_pred=None):
    """复制目录树；返回 (文件数, 字节数, 跳过的文件列表)"""
    n, b, sk = 0, 0, []
    if not os.path.isdir(src):
        return 0, 0, [("缺失源目录", src)]
    for dirpath, dirnames, filenames in os.walk(src):
        rel = os.path.relpath(dirpath, src)
        target_dir = dst if rel == "." else os.path.join(dst, rel)
        ensure(target_dir)
        for fn in filenames:
            sp = os.path.join(dirpath, fn)
            tp = os.path.join(target_dir, fn)
            if fn.endswith(SKIP_SUFFIX) or fn in SKIP_NAMES or (skip_pred and skip_pred(sp, fn)):
                sk.append((os.path.relpath(sp, ROOT), os.path.getsize(sp) if os.path.exists(sp) else 0))
                continue
            if os.path.exists(tp):
                continue
            shutil.copy2(sp, tp)
            n += 1
            b += os.path.getsize(sp)
    return n, b, sk


def copy_file(sp, tp):
    if not os.path.exists(sp):
        return False, 0
    ensure(os.path.dirname(tp))
    if os.path.exists(tp):
        return False, os.path.getsize(tp)
    shutil.copy2(sp, tp)
    return True, os.path.getsize(sp)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest().upper()


def stage(name, src, dst_rel, note="", skip_pred=None):
    dst = os.path.join(PKG, dst_rel)
    n, b, sk = copy_tree(src, dst, skip_pred)
    copied['files'] += n
    copied['bytes'] += b
    for s in skipped:
        pass
    manifest_log.append({
        'stage': name, 'source': os.path.relpath(src, ROOT), 'dest': dst_rel,
        'files': n, 'bytes': b, 'note': note,
        'not_copied_large': [{'path': p, 'bytes': sz} for p, sz in sk],
    })
    print(f'[{name}] {n} 文件 / {b/1048576:.1f} MB -> {dst_rel}')
    return sk


def stage_file(name, sp, dst_rel, note=""):
    tp = os.path.join(PKG, dst_rel)
    ok, size = copy_file(sp, tp)
    if ok:
        copied['files'] += 1
        copied['bytes'] += size
    manifest_log.append({'stage': name, 'source': os.path.relpath(sp, ROOT),
                         'dest': dst_rel, 'files': 1 if ok else 0, 'bytes': size,
                         'note': note, 'not_copied_large': []})
    print(f'[{name}] {"1 文件" if ok else "已存在"} / {size/1048576:.2f} MB -> {dst_rel}')
    return ok


print('=' * 60)
print('组装 BEST-Skill 投稿包 ->', PKG)
print('=' * 60)

# ---------------- 01_稿件 ----------------
print('\n--- 01_稿件 ---')
stage('稿件正文', os.path.join(V72, 'source'), '01_稿件',
      'v72 基线：main.tex + supplementary_material.tex + 编译类 + figures/（原样保留目录层级）')

# ---------------- 02_图表 ----------------
print('\n--- 02_图表 ---')
stage('图表源工程', os.path.join(V55, '图表源码'), '02_图表',
      '图表生成器与 source_data.json（含 E1 三箱 0.9429/0.9607/0.9554 的图源数据）')
stage_file('图表README', os.path.join(V55, '图表源码', 'README.md'), '02_图表\\README.md')

# ---------------- 03_数据_E1-E6 ----------------
print('\n--- 03_数据_E1-E6 ---')
E = os.path.join(ROOT, r'04_实验数据')

stage('E1 实验产物', os.path.join(E, r'E1_自然语言到工具调用\实验产物'), '03_数据_E1-E6\\E1\\原始三链与判分器',
      'E1 原始三链（3333/4444/5555）证据，含 0.9089/0.9089/0.9446 旧链评分与维度分数报告')
stage('E1 重新判分证据', os.path.join(V55, 'evidence'), '03_数据_E1-E6\\E1\\v55_重新判分_20261020',
      '★论文口径证据：E1_summary.json / E1_sb1-sb3 / E1_combined / E1_tasks.yaml / 判分报告-三箱-2026-10-20.md / 泄漏检查-三箱-2026-10-20.md。注意：同目录另有 E4/E5/E6/formal-scores 等其他实验证据，本包只取 E1_* 与判分报告-三箱、泄漏检查-三箱',
      skip_pred=lambda sp, fn: (fn.startswith('E4_') or fn.startswith('E5_') or
                                fn in ('formal-analysis.json', 'formal-scores.json',
                                       'drive_analysis.json', 'drive_report.md', 'drive_scores.csv',
                                       'input_sha256.json', 'POSTRUN-INTEGRITY.json',
                                       'PREREGISTRATION.md', 'scoring.receipt.json',
                                       'SUSPEND-TIMING-DEVIATIONS.json', 'ACTUAL-BUDGET-AUDIT.json')))

stage('E2 冻结确认性实验', os.path.join(E, r'E2_结果一致性\实验产物'), '03_数据_E1-E6\\E2',
      'E2 v2 冻结快照确认性重跑：accepted_run(results.json 21/21、63/63)、gold、scenarios、snapshots、operations、code、preregistration')

stage('E3 实验产物', os.path.join(E, r'E3_科学忠实性\实验产物'), '03_数据_E1-E6\\E3',
      'E3 全部实验产物：01_当前结果（指标汇总/主测分母/main-recomputed）、02_教师反馈、03_四条核验、04_匿名审核材料、05_原始实验归档')

stage('E4 实验产物', os.path.join(E, r'E4_鲁棒性与安全性\实验产物'), '03_数据_E1-E6\\E4',
      'E4 全部实验产物：用例集与判据表、判定器与执行器、注入器夹具、r1 权威结果与逐条判定表')

stage('E5 正式结果与成果', os.path.join(E, r'E5_消融'), '03_数据_E1-E6\\E5',
      'E5 确认性消融：正式结果_2026-10-12（scores.json 2016 格）、论文成果、复现脚本、执行过程。执行过程_v4_01 的过程日志体积大，按复现必检原则保留全部',
      skip_pred=lambda sp, fn: False)

stage('E6 实验产物', os.path.join(E, r'E6_可复现性\实验产物'), '03_数据_E1-E6\\E6',
      'E6 全部实验产物：01_当前R3补测（论文所报告批次）、02_原批次结果与原始归档（含 69 次 HTTP 402 的 R3-audit.json）、辅助程序。两处大体积原始证据归档不复制，见 08_清单与SHA256 的指针')

# ---------------- 04_复现源码 ----------------
print('\n--- 04_复现源码 ---')
stage('被测对象源码仓', os.path.join(E, r'00_共享底座\astro-best_skill源码仓'), '04_复现源码\\astro-best_skill源码仓',
      '被测对象本体（2901 文件）。整仓保留相对依赖，未拆分')
for b, fn in [('E1', 'E1_最小复现包.zip'), ('E2', 'E2_最小复现包.zip'), ('E3', 'E3_最小复现包.zip'),
               ('E4', 'E4_最小复现包.zip'), ('E5', 'E5_最小复现包.zip'), ('E6', 'E6_最小复现包.zip')]:
    stage_file('最小复现包_' + b, os.path.join(DESENS, fn), os.path.join('04_复现源码', '最小复现包', fn),
               '脱敏版最小复现包（' + b + '）')
stage_file('替换规则表', os.path.join(DESENS, 'REPLACEMENT-RULES.md'), '04_复现源码\\REPLACEMENT-RULES.md')
stage_file('脱敏日志', os.path.join(DESENS, 'DESENSITIZATION-LOG.md'), '04_复现源码\\DESENSITIZATION-LOG.md')

# ---------------- 05_溯源台账 ----------------
print('\n--- 05_溯源台账 ---')
stage('主会话独立复核件', os.path.join(PKG, r'_work\_复核'), '05_溯源台账\主会话独立复算件',
      'MCode 主会话 2026-10-24 的四个独立复算脚本与三份口径核对 md')

# ---------------- 07_脱敏与README ----------------
print('\n--- 07_脱敏与README ---')
stage_file('替换规则表', os.path.join(DESENS, 'REPLACEMENT-RULES.md'), '07_脱敏与README\\REPLACEMENT-RULES.md')
stage_file('脱敏日志', os.path.join(DESENS, 'DESENSITIZATION-LOG.md'), '07_脱敏与README\\DESENSITIZATION-LOG.md')
stage_file('脱敏总览', os.path.join(DESENS, 'README-总览.md'), '07_脱敏与README\\README-脱敏总览.md')

# ---------------- 08_清单与SHA256 ----------------
print('\n--- 08_清单与SHA256 ---')
ensure(os.path.join(PKG, '08_清单与SHA256', 'scripts'))

# 记录未复制的大文件指针
big = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    rel = os.path.relpath(dirpath, ROOT)
    if rel.startswith('11_投稿包'):
        dirnames[:] = []
        continue
    if rel.split(os.sep)[0] not in ('04_实验数据', '10_脱敏复现包', '00_目录说明'):
        continue
    for fn in filenames:
        if fn.endswith(SKIP_SUFFIX) or fn in SKIP_NAMES:
            p = os.path.join(dirpath, fn)
            big.append({'path': os.path.relpath(p, ROOT), 'bytes': os.path.getsize(p),
                        'sha256': sha256(p)})

with open(os.path.join(PKG, '08_清单与SHA256', '组装日志.json'), 'w', encoding='utf-8') as f:
    json.dump({'assembled_at': datetime.datetime.now().isoformat(timespec='seconds'),
               'package_root': PKG,
               'stages': manifest_log,
               'totals': {'files': copied['files'], 'bytes': copied['bytes']},
               'not_copied_large_files': big}, f, ensure_ascii=False, indent=2)

print('\n' + '=' * 60)
print('组装完成：%d 文件 / %.1f MB' % (copied['files'], copied['bytes'] / 1048576))
print('未复制的大文件指针 %d 条（已写入 08_清单与SHA256\\组装日志.json）' % len(big))
print('=' * 60)
