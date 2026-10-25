"""按用户明确上传授权准备E3/E6最终结果包；不执行Git或API操作。"""
# 标准库：保留原字节的归档、指纹与可移植报告。
import base64
import hashlib
import json
import os
import re
import shutil
import tarfile
from pathlib import Path
# 现有安全配置仅用于密钥扫描，不回显配置内容。
from common_e6 import ROOT, HERE, SECRETS, config, read


def digest(path):
    """返回原始文件字节指纹。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def secret_scan(raw):
    """检查原文和JSON中编码的原始响应，不打印敏感匹配片段。"""
    if any(s and s.encode() in raw for s in SECRETS):
        raise RuntimeError('待上传产物含真实密钥')
    for encoded in re.findall(rb'"content_base64"\s*:\s*"([A-Za-z0-9+/=]+)"', raw):
        decoded = base64.b64decode(encoded)
        if any(s and s.encode() in decoded for s in SECRETS):
            raise RuntimeError('待上传原始响应字节含真实密钥')


def safe_files(directory):
    """排除环境、锁、缓存以及保留本地的专家盲评材料。"""
    excluded = {'operator', 'expert-blind', '__pycache__', '.pytest_cache', 'venv'}
    for p in sorted(directory.rglob('*')):
        if (p.is_file() and not p.is_symlink() and not excluded.intersection(p.relative_to(directory).parts)
                and p.name != '.run.lock' and not p.name.startswith('.env')
                and '.pending-' not in p.name):
            yield p


def archive(paths, destination):
    """归档原始字节并记录每个成员指纹，原件不变。"""
    records = []
    with tarfile.open(destination, 'w:gz', compresslevel=6) as out:
        for path in sorted(set(paths)):
            raw = path.read_bytes()
            secret_scan(raw)
            name = path.relative_to(ROOT).as_posix()
            out.add(path, arcname=name, recursive=False)
            records.append({'path': name, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    if destination.stat().st_size >= 95 * 1024 * 1024:
        raise RuntimeError('结果归档超过仓库单文件预算')
    with tarfile.open(destination, 'r:gz') as incoming:
        members = incoming.getmembers()
        if len(members) != len(records):
            raise RuntimeError('归档成员数不一致')
        for member, record in zip(members, records):
            if member.name != record['path'] or hashlib.sha256(incoming.extractfile(member).read()).hexdigest() != record['sha256']:
                raise RuntimeError('归档复读字节指纹不一致')
    return records


def prepare():
    """仅在E6真实完成和最终审计交付后生成可提交材料。"""
    config()
    e3 = ROOT/'temp/e3-formal/batches/e3-b5ad6d180c9f42ce'
    e6 = HERE/'batches'/read(HERE/'current.json')['batch']
    delivery = read(e6/'FINAL-DELIVERY.json')
    report = Path(delivery['scoring_report'])
    summary = read(report/'summary.json')
    if not delivery['collection_complete'] or not summary['collection_complete_required_lanes']:
        raise RuntimeError('采集未完成，不能准备最终上传')
    for name, fingerprint in delivery['artifacts_sha256'].items():
        if digest(Path(name)) != fingerprint:
            raise RuntimeError('最终交付产物已改变')
    staging = HERE/'repository-results-staging'
    staging.mkdir(exist_ok=False)
    directories = {'E3': staging/e3.name, 'E6': staging/e6.name}
    for target in directories.values():
        target.mkdir()
    mappings = {}
    copied = []
    for lane, sources in [('E3', [p for p in e3.iterdir() if p.is_file() and p.suffix in ('.md', '.json')]),
                          ('E6', list(report.iterdir())+[HERE/'FINAL-REPORT.md', e6/'FINAL-DELIVERY.json',
                                    e6/'run_manifest.json', e6/'R2-CONDITIONS.json', HERE/'ASSISTANT-REVIEW.md'])]:
        for source in sources:
            if source.name == 'REPORT.md' and lane == 'E3':
                continue
            destination = directories[lane]/source.name
            if destination.exists():
                raise RuntimeError('结果文件名冲突')
            secret_scan(source.read_bytes())
            shutil.copyfile(source, destination)
            mappings[str(source.resolve())] = destination
            copied.append({'source': str(source.relative_to(ROOT)), 'destination': str(destination.relative_to(staging)),
                           'original_sha256': digest(source)})
    for source in map(Path, delivery['audits']):
        destination = directories['E6']/(source.parent.parent.name+'.json')
        secret_scan(source.read_bytes())
        shutil.copyfile(source, destination)
        mappings[str(source.resolve())] = destination
        copied.append({'source': str(source.relative_to(ROOT)), 'destination': str(destination.relative_to(staging)),
                       'original_sha256': digest(source)})
    e6_files = []
    for p in safe_files(e6):
        relative = p.relative_to(e6)
        if relative.parts[0] in {'reports', 'delivery-audits', 'coverage-audits', 'wire-semantics-audits'}:
            if not (p.is_relative_to(report) or p in map(Path, delivery['audits'])):
                continue
        e6_files.append(p)
    pilot = read(e6/'pilot-source.json')
    pilot_id = pilot.get('batch') or pilot.get('pilot_batch')
    if not pilot_id:
        raise RuntimeError('必须确认快照pilot来源后归档')
    e6_files.extend(safe_files(HERE/'batches'/pilot_id))
    e6_files.extend(HERE.glob('*.py'))
    e6_files.extend(safe_files(HERE/'scoring-protocols'))
    e6_files.extend([HERE/'PROTOCOL.md', HERE/'ASSISTANT-REVIEW.md', HERE/'FINAL-REPORT.md',
                     HERE/'formal-tests-64-model-balance-failures.log'])
    e3_files = list(safe_files(e3))+list((ROOT/'temp/e3-formal').glob('*.py'))
    e3_files.extend([ROOT/'temp/e3-formal/tests.log', ROOT/'temp/e3-formal/final-report-validation.log',
                     ROOT/'temp/e3-formal/README.md', ROOT/'temp/e3-e6/requirements.lock.txt'])
    e6_files.append(ROOT/'temp/e3-e6/requirements.lock.txt')
    members = {}
    for lane, paths in [('E3', e3_files), ('E6', e6_files)]:
        members[lane] = archive(paths, directories[lane]/'original-evidence.tar.gz')
        for record in members[lane]:
            mappings.setdefault(str(ROOT/record['path']), directories[lane]/'original-evidence.tar.gz')
    # 报告副本改为仓内相对链接；JSON和压缩包原始字节与路径不改。
    for destination in staging.rglob('*.md'):
        text = destination.read_text()
        for original, target in sorted(mappings.items(), key=lambda item: -len(item[0])):
            relative = Path(os.path.relpath(target, destination.parent)).as_posix()
            text = text.replace('<'+original+'>', relative).replace(original, relative)
        destination.write_text(text)
    manifest = {'repository': 'https://github.com/LL-LK/AI', 'authorization': '用户要求运行结束后上传E3和E6结果',
                'copied_reports': copied, 'original_archive_members': members,
                'files': {str(p.relative_to(staging)): digest(p) for p in sorted(staging.rglob('*')) if p.is_file()},
                'credentials_excluded': True, 'expert_blind_package_and_private_mapping_excluded': True,
                'E6_protocol_gate': 'FAIL', 'E6_composite': None, 'E3_expert_review': 'pending'}
    (staging/'README.md').write_text('# E3 与 E6 实验结果\n\n用户授权在本轮E6实际运行结束后上传。\n\n'
        f'- [E3最终报告]({e3.name}/FINAL-REPORT.md)：216份真实回答，助手主评完成，独立专家复核待完成。\n'
        f'- [E6最终报告]({e6.name}/FINAL-REPORT.md)：R0/R1/R3计划采集完成，原协议门禁FAIL，综合分缺失；R2留待2026-10-14人工执行。\n\n'
        '各目录包含机器结果、统计及审计。original-evidence.tar.gz保留本轮原件、失败、评分和冻结材料；'
        'publication-manifest.json记录逐成员原始SHA256和公开副本指纹。报告副本链接已转换为仓内链接，JSON中的本机绝对路径作为原始溯源信息保留。\n\n'
        'E3结论与评分来源以FINAL-REPORT.md和FINAL-RESULTS.json为准；automated-report.json保留冻结报告器原输出中的旧模型标签，不能据它声称当前助手主评模型已核验。\n\n'
        '压缩包不含密钥、环境配置、虚拟环境、缓存、专家盲评材料或私有映射。专家盲评包仍在本地，独立专家不应先阅读此结果目录或助手评分。'
        '归档未纳入E3其他预算/模型历史诊断批次，E6保留本轮pilot快照来源以支持复核。\n')
    manifest['files']['README.md'] = digest(staging/'README.md')
    (staging/'publication-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'staging': str(staging), 'files': len(list(staging.rglob('*'))),
                      'archives': {k: len(v) for k, v in members.items()}}, ensure_ascii=False))


if __name__ == '__main__':
    prepare()
