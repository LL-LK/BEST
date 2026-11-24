$ErrorActionPreference='Stop'
$e5Root='<WORK_ROOT>'
$e5Result=[ordered]@{schema='e5-worker-code-install-v1';identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name;exit_code=$null;error=$null}
try {
  $code="from pathlib import Path; import shutil; root=Path('/opt/e5'); root.mkdir(exist_ok=True); [shutil.copyfile('/mnt/d/E5-v4-20261012-02/public/'+name,root/name) for name in ['fixture_worker.py','fixture_gateway.py']]; print('fixture scripts installed; no model tasks')"
  $info=New-Object Diagnostics.ProcessStartInfo
  $info.FileName='C:\Windows\System32\wsl.exe'
  $info.Arguments='--distribution E5Worker --user root --exec /usr/bin/python3 -c "'+$code+'"'
  $info.UseShellExecute=$false;$info.CreateNoWindow=$true
  $info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
  $info.StandardOutputEncoding=[Text.Encoding]::UTF8;$info.StandardErrorEncoding=[Text.Encoding]::UTF8
  $process=New-Object Diagnostics.Process;$process.StartInfo=$info
  [void]$process.Start();$stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync()
  if(!$process.WaitForExit(45000)){$process.Kill();throw 'worker setup timeout'}
  $e5Result.exit_code=$process.ExitCode;$e5Result.stdout=$stdout.Result;$e5Result.stderr=$stderr.Result
} catch {$e5Result.error=$_.Exception.Message}
[IO.File]::WriteAllText("$e5Root\cells\worker-code-install.result.json",(ConvertTo-Json -InputObject $e5Result -Depth 5),[Text.UTF8Encoding]::new($false))
