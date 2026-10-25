$ErrorActionPreference='Stop'
$e5Root='<WORK_ROOT>'
$e5Result=[ordered]@{schema='e5-wsl-identity-import-v1';identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name;distro='E5Worker';exit_code=$null;error=$null}
try {
    $info=New-Object Diagnostics.ProcessStartInfo
    $info.FileName='C:\Windows\System32\wsl.exe'
    $info.Arguments='--import E5Worker "<WORK_ROOT>\profile\wsl" "<WORK_ROOT>\public\e5-worker-rootfs.tar" --version 2'
    $info.UseShellExecute=$false
    $info.CreateNoWindow=$true
    $info.RedirectStandardOutput=$true
    $info.RedirectStandardError=$true
    $info.StandardOutputEncoding=[Text.Encoding]::Unicode
    $info.StandardErrorEncoding=[Text.Encoding]::Unicode
    $process=New-Object Diagnostics.Process
    $process.StartInfo=$info
    [void]$process.Start()
    $stdout=$process.StandardOutput.ReadToEndAsync()
    $stderr=$process.StandardError.ReadToEndAsync()
    if(!$process.WaitForExit(120000)){ $process.Kill(); throw 'WSL import timed out' }
    $e5Result.exit_code=$process.ExitCode
    $e5Result.stdout=$stdout.Result
    $e5Result.stderr=$stderr.Result
} catch { $e5Result.error=$_.Exception.Message }
[IO.File]::WriteAllText("$e5Root\cells\wsl-import.result.json",(ConvertTo-Json -InputObject $e5Result -Depth 5),[Text.UTF8Encoding]::new($false))
