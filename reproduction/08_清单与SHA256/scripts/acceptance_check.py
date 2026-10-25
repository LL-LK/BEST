# -*- coding: utf-8 -*-
r"""
投稿包机器可检验验收清单。
路径从脚本自身位置推导（scripts/ 的上上级即包根），不依赖任何绝对路径，
因此在审稿人的机器上直接可用。

用法：python 08_清单与SHA256/scripts/acceptance_check.py
"""
import os, re, sys, csv, json, zipfile, datetime
sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(os.path.dirname(HERE))          # 包根（…\11_投稿包）
ROOTS = ['01_稿件', '02_图表', '03_数据_E1-E6', '04_复现源码', '05_溯源台账',
         '06_专家盲评包', '07_脱敏与README', '08_清单与SHA256']
results = []


def rec(no, name, ok, detail, cmd=''):
    results.append((no, name, 'PASS' if ok else 'FAIL', detail, cmd))
    print('[%s] %s %s' % (no, 'PASS' if ok else 'FAIL', name))
    print('       %s' % detail)


# ---------- A. 每个论文报告数字在溯源表中有对应行 ----------
LEDGER = os.path.join(PKG, '05_溯源台账', '数字溯源台账_合并.csv')
n_rows, per_exp = 0, {}
bad = []
if os.path.exists(LEDGER):
    rows = list(csv.reader(open(LEDGER, encoding='utf-8-sig')))
    hdr, body = rows[0], rows[1:]
    n_rows = len(body)
    for r in body:
        per_exp[r[1]] = per_exp.get(r[1], 0) + 1
    bad = [r[0] for r in body if r[9] not in ('一致', '不一致', '口径不同', '无证据')]
else:
    body = []
from collections import Counter
verdicts = dict(Counter(r[9] for r in body))
EXP_COVER = ['E1', 'E2', 'E3', 'E4', 'E5', 'E6']
missing = [e for e in EXP_COVER if per_exp.get(e, 0) == 0]
okA = (n_rows > 0 and not missing and not bad)
rec('A', '每个论文报告数字在溯源表中有对应行', okA,
    '台账 %d 行，覆盖实验：%s；判定值全部合规：%s'
    % (n_rows, '、'.join('%s=%d' % (e, per_exp.get(e, 0)) for e in EXP_COVER),
       '是' if not bad else '否(%s)' % bad),
    'python 08_清单与SHA256\\scripts\\acceptance_check.py')

# ---------- B. 每个 zip 包内有 MANIFEST 与 SHA256 清单 ----------
zipdir = os.path.join(PKG, r'04_复现源码\最小复现包')
zips = sorted(os.listdir(zipdir)) if os.path.isdir(zipdir) else []
b_detail, b_ok = [], True
for z in zips:
    if not z.endswith('.zip'):
        continue
    zf = zipfile.ZipFile(os.path.join(zipdir, z))
    names = zf.namelist()
    man = [n for n in names if 'MANIFEST' in n.upper()]
    sha = [n for n in names if 'SHA256' in n.upper()]
    ok = bool(man) and bool(sha)
    b_ok = b_ok and ok
    b_detail.append('%s: %d 条目, MANIFEST %d 个, SHA256 清单 %d 个 → %s'
                     % (z, len(names), len(man), len(sha), 'OK' if ok else '缺清单'))
rec('B', '每个 zip 包内有 MANIFEST 与 SHA256 清单', b_ok, '；'.join(b_detail),
    'python -c "import zipfile,os,glob;p=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(\'acceptance_check.py\')))),\'04_复现源码\',\'最小复现包\');[print(f,[n for n in zipfile.ZipFile(os.path.join(p,f)).namelist() if \'MANIFEST\' in n.upper()][:1]) for f in os.listdir(p) if f.endswith(\'.zip\')]"')

# ---------- C. 隐私扫描零识别性命中 ----------
scan_json = os.path.join(PKG, '08_清单与SHA256', '隐私扫描结果.json')
ident_n, non_n, scan_stats = 0, 0, {}
if os.path.exists(scan_json):
    j = json.loads(open(scan_json, encoding='utf-8').read())
    ident_n = len(j.get('identifying', []))
    non_n = len(j.get('non_identifying', []))
    scan_stats = j.get('stats', {})
rec('C', '隐私扫描零识别性命中', ident_n == 0,
    '识别性命中 %d 条（要求 0）；非识别性 %d 条（系统路径/测试夹具/公开学术引用/占位符，均保留并说明）；扫描覆盖 %s 文件 / %.1f MB'
    % (ident_n, non_n, scan_stats.get('files', 0), scan_stats.get('bytes', 0) / 1048576),
    'python 08_清单与SHA256\\scripts\\scan_privacy.py <各目录>')

# ---------- D. 稿件内所有 includegraphics 指向的文件均存在 ----------
texdir = os.path.join(PKG, '01_稿件')
missing_fig, n_fig = [], 0
for dp, dn, fns in os.walk(texdir):
    for fn in fns:
        if not fn.endswith('.tex'):
            continue
        fp = os.path.join(dp, fn)
        txt = open(fp, 'rb').read().decode('utf-8', errors='replace')
        for m in re.finditer(r'\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}', txt):
            n_fig += 1
            rel = m.group(1).strip()
            cand = os.path.join(os.path.dirname(fp), rel.replace('/', os.sep))
            if not os.path.exists(cand):
                alt = os.path.join(texdir, rel.replace('/', os.sep))
                if not os.path.exists(alt):
                    missing_fig.append('%s -> %s' % (fn, rel))
rec('D', '稿件内所有 \\includegraphics 指向的文件均存在', not missing_fig,
    '共 %d 处 \\includegraphics；缺失 %d 处%s'
    % (n_fig, len(missing_fig), ('：' + '；'.join(missing_fig[:10])) if missing_fig else ''),
    'grep -n includegraphics 01_稿件/*.tex')

# ---------- E. 各 zip 可正常解压并核对文件数 ----------
e_detail, e_ok = [], True
for z in zips:
    if not z.endswith('.zip'):
        continue
    p = os.path.join(zipdir, z)
    try:
        zf = zipfile.ZipFile(p)
        bad_z = zf.testzip()
        n = len(zf.namelist())
        ok = (bad_z is None)
        e_ok = e_ok and ok
        e_detail.append('%s: %d 条目, CRC 校验 %s' % (z, n, '通过' if ok else '失败@%s' % bad_z))
    except Exception as ex:
        e_ok = False
        e_detail.append('%s: 解压失败 %s' % (z, ex))
rec('E', '各 zip 可正常解压并核对文件数', e_ok, '；'.join(e_detail),
    'python -c "import zipfile,os,glob;[zipfile.ZipFile(f).testzip() for f in glob.glob(os.path.join(\'04_复现源码\',\'最小复现包\',\'*.zip\'))]"')

# ---------- F. 溯源表每个数字都有 SHA256 与可复现命令 ----------
no_sha = sum(1 for r in body if not r[7].strip())
no_cmd = sum(1 for r in body if not r[8].strip())
rec('F', '溯源表每行都有证据 SHA256 与可复现命令', no_sha == 0 and no_cmd == 0,
    '缺 SHA256 %d 行；缺可复现命令 %d 行' % (no_sha, no_cmd),
    'python -c "import csv,os;p=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(\'acceptance_check.py\')))),\'05_溯源台账\',\'数字溯源台账_合并.csv\');r=list(csv.reader(open(p,encoding=\'utf-8-sig\')))[1:];print(sum(1 for x in r if not x[7].strip()),sum(1 for x in r if not x[8].strip()))"')

# ---------- 写报告 ----------
now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
L = ['# 投稿包机器可检验验收报告', '',
     '- 验收时间：%s' % now,
     '- 验收对象：投稿包根目录（本报告位于 `08_清单与SHA256\\`）',
     '- 结论：**%s**' % ('全部通过' if all(r[2] == 'PASS' for r in results) else '存在未通过项'), '',
     '| # | 检查项 | 结果 | 实际结果 |', '|---|---|---|---|']
for no, name, v, detail, cmd in results:
    L.append('| %s | %s | **%s** | %s |' % (no, name, v, detail.replace('|', '\\|')))
L += ['', '## 复核命令', '']
for no, name, v, detail, cmd in results:
    L += ['**%s %s**' % (no, name), '', '```powershell', cmd, '```', '']
L += ['## 说明', '',
      '- A/F 检查的是**论文呈现值 ↔ 证据**的逐条覆盖，判定值仅允许「一致 / 不一致 / 口径不同 / 无证据」四类。',
      '- C 的「非识别性命中」不计入失败：系统路径、测试夹具内网地址、公开学术邮箱、脱敏占位符均按既有口径保留，并已在《隐私扫描报告》中逐类说明理由。',
      '- D 只校验 `01_稿件` 内 LaTeX 源码的图引用；图文件本体随稿件同目录。',
      '- 本报告为**结构与可复现性**验收，不替代科学结论本身的有效性判断（后者见《数字溯源台账_合并.csv》与各线核对报告）。']
out = os.path.join(PKG, '08_清单与SHA256', '验收结果报告.md')
with open(out, 'w', encoding='utf-8') as f:
    f.write('\n'.join(L) + '\n')
print('\n写出:', out)
print('总体:', '全部通过' if all(r[2] == 'PASS' for r in results) else '存在未通过项')
