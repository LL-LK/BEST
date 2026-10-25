# -*- coding: utf-8 -*-
r"""
投稿包隐私扫描器 v3（可复跑，识别性 / 非识别性分级）。

用法：
    python scan_privacy.py <目标目录> [更多目录...] [--csv 输出csv] [--md 输出md] [--json 输出json]

分级口径
--------
【需人工确认】= 具备识别性、可能泄露作者本人或其机器的信息。验收要求此类命中为 0。
【非识别性】= 不具备识别性，保留并在报告中说明理由：
    - 系统路径（Windows System32 等，脚本功能性所需）
    - 容器内路径（WSL / Linux worker 内的 /home/<user>）
    - 测试夹具里的示例内网地址（SSRF 教材示例等）
    - RFC 2606 保留的示例域名邮箱
    - 官方站点公开的学术联系邮箱（沿用既有"第三方公开邮箱 = 学术引用"口径）
    - 假密钥负例夹具、Windows 内置 SID、作者化名 LL-LK、工具会话 UUID、站点域名 / DOI
    - 扫描器脚本与扫描输出自身（它们按定义包含被检模式）
"""
import os, re, sys, csv, json, argparse

# ---------- 识别性规则（命中即需人工确认） ----------
IDENTIFYING = [
    ('用户目录绝对路径', re.compile(r'(?:/Users/[A-Za-z0-9_.\-]{1,40}/)|(?:[A-Za-z]:\\Users\\[A-Za-z0-9_.\-]{1,40}\\)|(?:/home/[A-Za-z0-9_.\-]{1,40}/)')),
    # 泛化：任何「盘符 + 路径中含中日韩字符」的 Windows 绝对路径（工作区路径的典型特征），
    # 不写死具体盘符或目录名，避免清理器把检测规则本身改掉。
    ('工作区绝对路径', re.compile(r'[A-Za-z]:\\(?:[^\s"\'<>|,;)\]]*[\u4e00-\u9fff][^\s"\'<>|,;)\]]*)')),
    ('真实密钥', re.compile(r'(?i)\b(?:sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{12,}|xox[baprs]-[A-Za-z0-9-]{10,}|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})')),
    ('疑似凭据字面量', re.compile(r'(?i)\b(?:api[_-]?key|secret|password|passwd|access[_-]?token|bearer)\b\s*[=:]\s*["\']?(?![A-Za-z0-9_]*\s*[(\[])(?!(?:extract|get|read|load|parse|config|env|yaml|json|none|null|true|false|convertto|securestring)\b)[A-Za-z0-9_\-]{24,}')),
    ('非保留域邮箱', re.compile(r'\b[A-Za-z0-9._%+\-]+@(?!example\.(?:com|net|org|edu|gov|mil|int)|[A-Za-z0-9\-]+\.(?:example|invalid|test|local)\b)[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b')),
    ('私钥块', re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----')),
]

# ---------- 非识别性规则（保留并说明） ----------
NON_IDENTIFYING = [
    ('系统路径', re.compile(r'(?i)[A-Za-z]:\\(?:Windows\\System32|Program Files|Windows|ProgramData)[^\s"\'<>|,;)\]}]*')),
    ('容器内路径', re.compile(r'/home/[A-Za-z0-9_.\-]{1,40}:/usr/bin/\w+')),
    ('测试夹具内网地址', re.compile(r'(?i)https?://(?:10\.0\.0\.1|10\.9\.9\.9|169\.254\.169\.254)(?:/|:)')),
    ('RFC2606示例域名邮箱', re.compile(r'\b[A-Za-z0-9._%+\-]+@(?:example\.(?:com|net|org|edu|gov|mil|int)|[A-Za-z0-9\-]+\.(?:example|invalid|test|local))\b')),
    ('脱敏占位邮箱', re.compile(r'\b(?:user@example\.com|student@example\.edu\.cn)\b')),
    ('公开git远程地址', re.compile(r'git@(?:ssh\.)?github\.com')),
    ('假密钥负例夹具', re.compile(r'sk-123456789012345678901')),
    ('Windows内置SID', re.compile(r'S-1-\d+(?:-\d+)+')),
    ('作者化名', re.compile(r'\bLL-LK\b')),
    ('工具会话UUID', re.compile(r'session-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')),
    ('官方站点公开联系邮箱', re.compile(r'(?i)\b(?:yuanhb@bnu\.edu\.cn|support@china-vo\.org|xiaokai@ucas\.ac\.cn|huangyang@ucas\.ac\.cn|fandongwei@nao\.cas\.cn|ivezic@astro\.washington\.edu)\b')),
    ('站点域名', re.compile(r'nadc\.china-vo\.org', re.I)),
    ('临时路径占位', re.compile(r'(?i)(?:%APPDATA%|%LOCALAPPDATA%|%TEMP%|/private/var/folders/|C:\\Windows\\Temp)')),
    ('主机名占位值', re.compile(r'(?i)hostname\s*=\s*"HOST')),
]

TEXT_EXT = {'.md', '.txt', '.csv', '.json', '.yaml', '.yml', '.py', '.tex', '.log', '.ini', '.cfg',
            '.toml', '.sh', '.bat', '.ps1', '.html', '.xml', '.rst', '.jsonl', '.tsv', '.drawio'}
BIN_EXT = {'.xlsx', '.docx', '.pdf', '.zip', '.png', '.jpg', '.jpeg', '.svg', '.gz'}
# 扫描器自身产物 + 同目录的验收运行日志：按定义包含被检模式或随运行变化，不计入
SELF_FILES = {'scan_privacy.py', '隐私扫描报告.md', '隐私扫描明细.csv', '隐私扫描结果.json',
              '隐私扫描_stdout.txt', '验收_stdout.txt', '验收结果报告.md',
              '既有23条规则核对表.csv', '脱敏规则核对报告.md'}


def scan(roots):
    ident, non = [], []
    stats = {'files': 0, 'bytes': 0, 'text_files': 0, 'binary_files': 0, 'skipped_self': 0}
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ('.git', '__pycache__', '.pytest_cache')]
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                rel = os.path.relpath(fp, root)
                ext = os.path.splitext(fn)[1].lower()
                try:
                    size = os.path.getsize(fp)
                except OSError:
                    continue
                stats['files'] += 1
                stats['bytes'] += size
                if fn in SELF_FILES or os.sep + 'scripts' + os.sep in fp:
                    stats['skipped_self'] += 1
                    continue
                if ext in TEXT_EXT:
                    stats['text_files'] += 1
                    try:
                        txt = open(fp, 'rb').read().decode('utf-8', errors='replace')
                    except OSError:
                        continue
                    lines = txt.split('\n')
                    for kind, pat in IDENTIFYING:
                        for i, line in enumerate(lines, 1):
                            for m in pat.finditer(line):
                                frag = m.group(0)[:180]
                                # 不脱敏清单优先：假密钥夹具、公开学术邮箱、站点域名等
                                if any(npat.search(frag) for _, npat in NON_IDENTIFYING):
                                    continue
                                ident.append([rel, i, kind, frag, '需人工确认'])
                    for kind, pat in NON_IDENTIFYING:
                        for i, line in enumerate(lines, 1):
                            for m in pat.finditer(line):
                                non.append([rel, i, kind, m.group(0)[:180], '非识别性·保留并说明'])
                elif ext in BIN_EXT:
                    stats['binary_files'] += 1
                    try:
                        blob = open(fp, 'rb').read()
                    except OSError:
                        continue
                    txt = blob.decode('utf-8', errors='replace')
                    for kind, pat in IDENTIFYING:
                        if kind in ('真实密钥', '疑似凭据字面量', '私钥块'):
                            for m in pat.finditer(txt):
                                ident.append([rel, 0, kind + '(二进制内)', m.group(0)[:180], '需人工确认'])
    return ident, non, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('root', nargs='+')
    ap.add_argument('--csv')
    ap.add_argument('--md')
    ap.add_argument('--json')
    a = ap.parse_args()

    ident, non, stats = scan(a.root)
    from collections import Counter
    ki = Counter(r[2] for r in ident)
    kn = Counter(r[2] for r in non)
    print('扫描目录:', ' , '.join(a.root))
    print('文件数 %d（文本 %d / 二进制 %d），体积 %.1f MB；跳过扫描器自身产物 %d 个'
          % (stats['files'], stats['text_files'], stats['binary_files'],
             stats['bytes'] / 1048576, stats['skipped_self']))
    print()
    print('【需人工确认 · 识别性】共 %d 条' % len(ident))
    for k, v in ki.most_common():
        print('   %-22s %d' % (k, v))
    if not ident:
        print('   零命中')
    print()
    print('【非识别性 · 保留并说明】共 %d 条' % len(non))
    for k, v in kn.most_common():
        print('   %-22s %d' % (k, v))

    if a.csv:
        os.makedirs(os.path.dirname(a.csv) or '.', exist_ok=True)
        with open(a.csv, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f)
            w.writerow(['分级', '文件相对路径', '行号', '命中类别', '原文片段', '处理动作'])
            for r in ident:
                w.writerow(['需人工确认', r[0], r[1], r[2], r[3], r[4]])
            for r in non:
                w.writerow(['非识别性', r[0], r[1], r[2], r[3], r[4]])
        print('\n写出 CSV:', a.csv)
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump({'roots': a.root, 'stats': stats,
                       'identifying': ident, 'non_identifying': non}, f, ensure_ascii=False, indent=2)
        print('写出 JSON:', a.json)
    if a.md:
        L = ['# 隐私扫描报告（v3 · 识别性分级）', '',
             '- 扫描目录：' + '、'.join('`%s`' % r for r in a.root),
             '- 文件数 %d（文本 %d / 二进制 %d），体积 %.1f MB；跳过扫描器自身产物 %d 个'
             % (stats['files'], stats['text_files'], stats['binary_files'],
                stats['bytes'] / 1048576, stats['skipped_self']), '',
             '## 一、需人工确认（识别性）', '',
             '**共 %d 条**' % len(ident), '']
        if ki:
            L += ['| 类别 | 命中数 |', '|---|---|']
            for k, v in ki.most_common():
                L.append('| %s | %d |' % (k, v))
            L += ['', '| 文件 | 行号 | 类别 | 片段 |', '|---|---|---|---|']
            for r in ident[:2000]:
                L.append('| %s | %s | %s | `%s` |'
                         % (r[0], r[1], r[2], str(r[3]).replace('|', '\\|').replace('`', "'")))
        else:
            L.append('**零命中** —— 无具备识别性的隐私泄露')
        L += ['', '## 二、非识别性（保留并说明）', '',
              '**共 %d 条**' % len(non), '',
              '| 类别 | 命中数 | 保留理由 |', '|---|---|---|']
        REASON = {
            '系统路径': 'Windows 系统目录，脚本功能性所需，替换会破坏脚本',
            '容器内路径': 'WSL / Linux worker 容器内路径，非宿主机标识',
            '测试夹具内网地址': 'SSRF 防护教材示例与测试夹具值，非真实内网设施',
            'RFC2606示例域名邮箱': 'RFC 2606 保留示例域名，非真实邮箱',
            '假密钥负例夹具': '防护用例负例夹具，形状必须像密钥（既有口径）',
            'Windows内置SID': '操作系统公开常量（既有口径）',
            '作者化名': '作者化名，本身已匿名（既有口径）',
            '工具会话UUID': '非个人标识，且被包内清单交叉引用（既有口径）',
            '官方站点公开联系邮箱': '官方站点公开的学术联系信息，属学术引用（既有口径）',
            '站点域名': '公开学术信息（既有口径）',
            '临时路径占位': '环境变量占位形式，非具体路径',
            '主机名占位值': 'Junit XML 中的占位值',
        }
        for k, v in kn.most_common():
            L.append('| %s | %d | %s |' % (k, v, REASON.get(k, '无识别性')))
        with open(a.md, 'w', encoding='utf-8') as f:
            f.write('\n'.join(L) + '\n')
        print('写出 MD:', a.md)


if __name__ == '__main__':
    main()
