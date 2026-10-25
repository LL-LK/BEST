"""将已完成实验文件整理为可离线校验的交付包；不改实验原件，不调用API。"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import json,hashlib,shutil,zipfile,tarfile,re,base64
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'docs/results/2026-10-11'
NAME='E3与E6-实验资料汇总-20261011'
OUT=BASE/NAME
if OUT.exists() or OUT.with_suffix('.zip').exists(): raise RuntimeError('输出已经存在，停止覆盖')
OUT.mkdir(); mapping={}
def copy(src,dst):
 src=ROOT/src if not isinstance(src,Path) else src
 assert src.is_file() and not src.is_symlink(),src
 dest=OUT/dst; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dest)
 mapping[str(dest.relative_to(OUT))]=str(src.relative_to(ROOT))
def tree(src,dst,exclude=()):
 src=ROOT/src
 for p in sorted(src.rglob('*')):
  if not p.is_file(): continue
  if p.name=='.DS_Store' or p.name in exclude or p.name.endswith('.inspect.ndjson') or '__pycache__' in p.parts: continue
  copy(p,Path(dst)/p.relative_to(src))
B='E6-R3-supplement-20261011-1791689271010679000'
cur=f'docs/results/2026-10-11/e6-r3-supplement/{B}'
for n in ['E3与E6-论文初稿.docx','E3与E6-论文初稿.md','DRAFT-DOCX-VERIFICATION.json']:
 copy(f'{cur}/{n}',Path('01_论文初稿')/n)
copy('temp/e3-formal/FINAL-RESULTS.json','02_E3/01_当前结果/FINAL-RESULTS.json')
for p in (ROOT/'docs/results/2026-10-11/e3-e6-paper').glob('E3-*'):
 if p.is_file(): copy(p,Path('02_E3/01_当前结果')/p.name)
tree('temp/e3-formal/outputs/e3-expert-review-20261010','02_E3/02_教师反馈')
tree('temp/e3-formal/outputs/e3-targeted-verification-20261011','02_E3/03_四条核验')
for n in ['E3-匿名审核简表.xlsx','E3-全量匿名审核表.xlsx']:
 copy(f'temp/e3-formal/outputs/e3-teacher-review-20261008/{n}',Path('02_E3/04_匿名审核材料')/n)
tree('docs/results/2026-10-07/e3-b5ad6d180c9f42ce','02_E3/05_原始实验归档')
history={'E3与E6-论文方法与结果-修订版.docx','E3与E6-论文方法与结果-修订版.md','DOCX-VERIFICATION.json'}
for p in sorted((ROOT/cur).iterdir()):
 if not p.is_file() or p.name=='.DS_Store': continue
 if p.name in history: copy(p,Path('05_历史论文材料/上一修订版')/p.name)
 elif p.name not in ['E3与E6-论文初稿.docx','E3与E6-论文初稿.md','DRAFT-DOCX-VERIFICATION.json','README.md']:
  copy(p,Path('03_E6/01_当前R3补测')/p.name)
tree('docs/results/2026-10-07/E6-20261007-1791350994158084000','03_E6/02_原批次结果与原始归档')
copy(cur+'-原始证据.zip',f'03_E6/03_补测原始证据/{B}-原始证据.zip')
tree('docs/results/2026-10-11/e3-e6-paper','05_历史论文材料/原论文复核包')
for n in ['requirements.lock.txt','environment.json','pip-check.log']:
 copy(f'temp/e3-e6/{n}',Path('04_复核与环境')/n)
copy(f'{cur}/FINAL-TESTS-314.log','04_复核与环境/FINAL-TESTS-314.log')
for d in ['e3-formal','e6-formal']:
 for p in sorted((ROOT/'temp'/d).glob('*.py')):
  if p.name.startswith('test_'): continue
  copy(p,Path('04_复核与环境/辅助程序')/d/p.name)
(OUT/'00_先读说明.md').write_text('''# E3 与 E6 实验资料汇总

这是 2026 年 10 月 11 日的当前交付快照。先读 `01_论文初稿/E3与E6-论文初稿.docx`；可编辑 Word 与同内容 Markdown 已检查排版。它包含两个实验的方法、结果、教师意见及局限，尚不是含引言、相关工作和全文参考文献的完整论文。

## 目录与阅读顺序

| 目录 | 内容及用途 |
|---|---|
| 01_论文初稿 | 当前方法与结果稿、同内容文本、Word 检查记录 |
| 02_E3/01_当前结果 | 教师反馈与四条核验后的当前 FINAL-RESULTS.json，重算主指标、分母及逐回答计数 |
| 02_E3/02_教师反馈 | 教师原表 evidence/teacher-original.xlsx、修复版、逐条反馈、导入检查和反馈报告 |
| 02_E3/03_四条核验 | 三份空白回答和一份反证的助手核验记录、证据及修改说明；不是教师补评分 |
| 02_E3/04_匿名审核材料 | 发给老师的匿名简表及原全量表 |
| 02_E3/05_原始实验归档 | 原批次题集、原结果、评分与报告，original-evidence.tar.gz 保存原始回答及冻结程序 |
| 03_E6/01_当前R3补测 | 充值后独立 R3 的可读 REPORT.md、当前 FINAL-RESULTS.json、逐题一致性、效率、U1–U6、失败与审计 |
| 03_E6/02_原批次结果与原始归档 | R0/R1/原R3 的逐题结果和全部失败，original-evidence.tar.gz 保存原始轨迹与冻结材料 |
| 03_E6/03_补测原始证据 | 补测全部请求、回包、答案、失败、快照及来源轨迹的原始证据 ZIP |
| 04_复核与环境 | 实际依赖版本、Python 环境记录、314 项测试日志及辅助程序；冻结原程序另在原始归档中 |
| 05_历史论文材料 | 以前的复核稿及上一修订版，仅供追溯，旧待办以本次范围说明为准 |

## 当前范围与结果

E3 真实回答共 216 份，含 192 份离线主测和 24 份在线辅测。教师定性反馈及原始勾选保留；完整独立量表评分不足，M6 一致性统计不报告数值，助手核验不能替代专家评分。

E6 保留 R0、R1、原 R3 和充值后独立 R3 补测。新补测 160 次尝试全部结束，133 份有效、27 份失败，21/32 题具有完整五次有效记录。失败不删除，补测不择优替换原答案。有效表示符合采集条件，不表示全文科学正确。

研究者已取消 R2 D+7 跨日复测和 U7 主观评分；当前 E6 采集范围已结束，无待执行 API 调用。仅报告各批次内重复一致性、冻结回包重放、效率与客观 U1–U6，不声称验证跨日稳定性或在线后端跨日漂移。这是结果已知后的范围修订，原始协议及历史说明保留，不据此将原完整协议或既有科学失败改为通过。

## 原始证据如何查看

E3 和原 E6 的 `.tar.gz` 可用解压工具展开；其中目录保持原项目结构，便于追溯。补测 ZIP 同样可解压查看逐题回答及请求；在解压后的批次目录运行 `python3 verify_supplement_archive_e6.py`，即可离线核验快照来源。归档内部仍保留采集时的协议，因此可能包含旧 R2/U7 字段；当前范围以本说明及 `03_E6/01_当前R3补测/PROTOCOL-AMENDMENT-R2-CANCELLATION.json` 为准。

JSON 用于程序重算与追溯，阅读时优先使用 Word、Markdown 和 CSV。多数实验原件保留原绝对路径；路径不必在接收者电脑上存在。SOURCE-MAP.json 提供汇总包路径到原项目路径的映射，文件本体未改写。复制的辅助程序需要项目代码及原目录布局；不是在任意目录直接一键执行的独立软件。当前阅读和文件校验不需要 API。

## 文件校验与配置

解压汇总包后，在根目录运行 `python3 verify_package.py`，会按 MANIFEST.json 校验全部文件的 SHA-256 和大小，不调用网络。旧内部清单保留其原交付路径；本汇总包以根目录清单为准。原始归档已核对哈希、目录及凭据模式；有效密钥当前不可用，因此不能声称完成了按实际密钥进行的精确扫描。`.env`、虚拟环境、缓存及页面截图不在本包中。
''')
index={'as_of':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'current_paper':'01_论文初稿/E3与E6-论文初稿.docx','E3':{'batch':'e3-b5ad6d180c9f42ce','current_results':'02_E3/01_当前结果/FINAL-RESULTS.json','real_answers':216,'main_answers':192,'ancillary_answers':24,'expert_quantitative_agreement_available':False},'E6':{'original_batch':'E6-20261007-1791350994158084000','supplement_batch':B,'current_results':'03_E6/01_当前R3补测/FINAL-RESULTS.json','supplement_attempts':160,'valid':133,'failed':27,'R2_status':'cancelled_before_execution','U7_status':'cancelled','cross_day_stability_verified':False,'pending_API_calls':0,'scientific_pass':False},'raw_records_modified':False}
(OUT/'RESULTS-INDEX.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n')
(OUT/'SOURCE-MAP.json').write_text(json.dumps(mapping,ensure_ascii=False,indent=2)+'\n')
(OUT/'verify_package.py').write_text('''"""Python 标准库离线校验，无网络调用。"""
from pathlib import Path
import hashlib,json,sys
root=Path(__file__).resolve().parent
m=json.loads((root/'MANIFEST.json').read_text())
errors=[]
for name,v in m['files'].items():
 p=root/name
 if not p.is_file() or p.stat().st_size!=v['bytes'] or hashlib.sha256(p.read_bytes()).hexdigest()!=v['sha256']: errors.append(name)
print(json.dumps({'passed':not errors,'checked':len(m['files']),'errors':errors},ensure_ascii=False))
sys.exit(bool(errors))
''')
print('Copied files; auditing originals and nested archives',flush=True)
pattern=re.compile(rb'sk-[A-Za-z0-9_-]{20,}')
fields={'authorization','cookie','set-cookie','x-api-key','api_key','access_token','refresh_token','e3_api_key'}
hits=[]; counted=0; malformed=[]
def check_obj(v):
 if isinstance(v,dict):
  for k,x in v.items():
   if k.lower() in fields and isinstance(x,str) and x and '[REDACTED]' not in x: return True
   if k=='content_base64' and isinstance(x,str):
    try:
     if pattern.search(base64.b64decode(x,validate=True)): return True
    except (ValueError,TypeError): pass
   if check_obj(x): return True
 elif isinstance(v,list): return any(check_obj(x) for x in v)
 return False
def scan(name,data):
 global counted
 counted+=1
 if pattern.search(data): hits.append(name)
 if name.endswith(('.json','.jsonl')):
  try:
   vals=[json.loads(s) for s in data.decode().splitlines() if s.strip()] if name.endswith('.jsonl') else [json.loads(data)]
   if any(check_obj(x) for x in vals): hits.append(name)
  except (ValueError,UnicodeError): malformed.append(name)
def safe_name(name):
 parts=Path(name).parts
 if name.startswith('/') or '..' in parts or '.env' in parts or any(x.startswith('.env.') for x in parts): raise ValueError('禁止归档路径或环境文件：'+name)
archives=[]
for p in sorted(OUT.rglob('*')):
 if not p.is_file(): continue
 name=str(p.relative_to(OUT)); safe_name(name)
 if p.name.endswith('.tar.gz'):
  entries=0
  with tarfile.open(p,'r:gz') as t:
   for item in t:
    safe_name(item.name)
    if item.issym() or item.islnk(): raise ValueError('归档符号链接：'+name)
    if item.isfile():
     scan(name+'!'+item.name,t.extractfile(item).read()); entries+=1
  archives.append({'path':name,'type':'tar.gz','readable_entries':entries,'passed':True})
 elif p.suffix in ['.zip','.docx','.xlsx']:
  with zipfile.ZipFile(p) as z:
   assert z.testzip() is None
   for item in z.infolist():
    safe_name(item.filename)
    if not item.is_dir(): scan(name+'!'+item.filename,z.read(item))
   if p.suffix=='.zip': archives.append({'path':name,'type':'zip','entries':len(z.infolist()),'crc_passed':True})
 else: scan(name,p.read_bytes())
if hits: raise ValueError('凭据模式/字段命中，请检查文件路径：'+json.dumps(sorted(set(hits)),ensure_ascii=False))
if malformed: raise ValueError('JSON 结构检查未完成：'+json.dumps(malformed[:20],ensure_ascii=False))
audit={'at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'archives':archives,'scanned_members_and_files':counted,'env_files_included':False,'credential_pattern_and_field_scan_passed':True,'exact_known_API_key_scan_available':False,'credentials_scan_scope':'模式、结构字段及解码回包；实际密钥精确扫描不可用','zero_network_calls':True,'raw_source_bytes_unchanged':True}
(OUT/'PACKAGE-AUDIT.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
files={str(p.relative_to(OUT)):{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='MANIFEST.json'}
(OUT/'MANIFEST.json').write_text(json.dumps({'generated_at':audit['at'],'files':files},ensure_ascii=False,indent=2)+'\n')
archive=OUT.with_suffix('.zip')
print('Audit passed; building combined ZIP',len(files),'files',flush=True)
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for p in sorted(OUT.rglob('*')):
  if p.is_file(): z.write(p,NAME+'/'+str(p.relative_to(OUT)),compress_type=zipfile.ZIP_STORED if p.name.endswith(('.zip','.tar.gz','.xlsx','.docx')) else zipfile.ZIP_DEFLATED)
with zipfile.ZipFile(archive) as z:
 assert z.testzip() is None
 for name,v in files.items():
  data=z.read(NAME+'/'+name); assert len(data)==v['bytes'] and hashlib.sha256(data).hexdigest()==v['sha256'],name
receipt={'at':audit['at'],'folder':str(OUT),'zip':str(archive),'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'file_count':len(files)+1,'outer_zip_crc_passed':True,'outer_zip_file_hashes_passed':True,'nested_archive_audit_passed':True,'R2':'cancelled','U7':'cancelled'}
(BASE/(NAME+'-交付校验.json')).write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(receipt,ensure_ascii=False),flush=True)
