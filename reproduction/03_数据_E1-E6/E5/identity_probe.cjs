const fs = require('node:fs');
const crypto = require('node:crypto');
const os = require('node:os');
const cp = require('node:child_process');
const root = 'D:/E5-v4-20261012-02';
const targets = {
  public: root + '/public/positive-control.txt',
  gold: root + '/private/items.yaml',
  private_canary: root + '/private/negative-control.txt',
  repo_gold: 'G:/tw/twskills/astro-best/evals/ablation/items.yaml',
  scorer_code: 'G:/tw/twskills/astro-best/evals/ablation/metrics/composite.py',
  historical_trace: 'G:/tw/twskills/astro-best/evals/ablation/captures/all-systems-rebuild.json',
  user_credentials: 'G:/cc switch/deepseek/.dsh/.credentials.yaml',
  sibling_canary: root + '/evidence/sibling-canary.txt',
  parent_canary: root + '/parent-canary.txt',
};
const result = {schema:'e5-harness-binary-os-identity-probe-v1', created_at_utc:new Date().toISOString(), username:os.userInfo().username, pid:process.pid, executable:process.execPath, logical_e5_units:0, checks:{}};
result.whoami = cp.execFileSync('C:/Windows/System32/whoami.exe',['/user','/fo','csv'],{encoding:'utf8',windowsHide:true});
for(const [name,path] of Object.entries(targets)) {
  try { const bytes=fs.readFileSync(path); result.checks[name]={path,readable:true,sha256:name==='public'?crypto.createHash('sha256').update(bytes).digest('hex'):null}; }
  catch(error) { result.checks[name]={path,readable:false,code:error.code}; }
}
result.os_boundary_pass = result.username==='E5HarnessV4' && result.checks.public.readable && Object.entries(result.checks).filter(([n])=>n!=='public').every(([,c])=>!c.readable && ['EACCES','EPERM'].includes(c.code));
fs.writeFileSync(root+'/cells/identity-proof.json',JSON.stringify(result,null,2),{flag:'wx'});
process.exitCode=result.os_boundary_pass?0:1;
