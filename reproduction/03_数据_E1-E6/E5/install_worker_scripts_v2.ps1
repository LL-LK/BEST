$ErrorActionPreference='Stop'
$e5Root='<WORK_ROOT>'
$e5Result=[ordered]@{schema='e5-worker-code-install-v2';identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name;exit_code=$null;error=$null;host_drives_required=$false}
try {
  $payload=@{}
  foreach($name in @('fixture_worker.py','fixture_gateway.py')) {$payload[$name]=[Convert]::ToBase64String([IO.File]::ReadAllBytes("$e5Root\public\$name"))}
  $code="import sys,json,base64; from pathlib import Path; data=json.load(sys.stdin); root=Path('/opt/e5'); root.mkdir(exist_ok=True); [(root/name).write_bytes(base64.b64decode(data[name])) for name in ['fixture_worker.py','fixture_gateway.py']]; Path('/etc/wsl.conf').write_text('[user]\ndefault=e5\n[boot]\nsystemd=false\n[interop]\nenabled=false\nappendWindowsPath=false\n[automount]\nenabled=false\n'); Path('/etc/fstab').write_text(''); print('fixture scripts installed without Windows filesystem mounts')"
  $info=New-Object Diagnostics.ProcessStartInfo
  $info.FileName='C:\Windows\System32\wsl.exe'
  $info.Arguments='--distribution E5Worker --user root --cd / --exec /usr/bin/python3 -c "'+$code+'"'
  $info.UseShellExecute=$false;$info.CreateNoWindow=$true
  $info.RedirectStandardInput=$true;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
  $info.StandardOutputEncoding=[Text.Encoding]::UTF8;$info.StandardErrorEncoding=[Text.Encoding]::UTF8
  $process=New-Object Diagnostics.Process;$process.StartInfo=$info
  [void]$process.Start();$stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync()
  $process.StandardInput.Write((ConvertTo-Json -InputObject $payload -Compress));$process.StandardInput.Close()
  if(!$process.WaitForExit(45000)){$process.Kill();throw 'worker setup timeout'}
  $e5Result.exit_code=$process.ExitCode;$e5Result.stdout=$stdout.Result;$e5Result.stderr=$stderr.Result
} catch {$e5Result.error=$_.Exception.Message}
[IO.File]::WriteAllText("$e5Root\cells\worker-code-install-v2.result.json",(ConvertTo-Json -InputObject $e5Result -Depth 5),[Text.UTF8Encoding]::new($false))
