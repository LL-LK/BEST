param([string]$e5PromptFile='install-science.prompt.txt', [string]$e5Tag='install-science-v2')
$ErrorActionPreference='Stop'
$e5Root='<WORK_ROOT>'
$e5Out=Join-Path $e5Root "cells\$e5Tag"
$e5Result=[ordered]@{schema='e5-harness-process-v1';identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name;logical_e5_units=0;exit_code=$null;error=$null}
try {
    if(Test-Path -LiteralPath "$e5Out.result.json"){throw 'refuse overwriting run receipt'}
    $env:ELECTRON_RUN_AS_NODE='1'
    $env:DSH_HOME="$e5Root\profile"
    $env:DSH_TOOLS_MODE='native'
    $env:DSH_PERMISSION_MODE='danger-full-access'
    $info=New-Object Diagnostics.ProcessStartInfo
    $info.FileName='<USER_HOME>\AppData\Local\Programs\DeepSeek Harness\DeepSeek Harness.exe'
    $info.Arguments='--expose-internals "<USER_HOME>\AppData\Local\Programs\DeepSeek Harness\resources\app.asar\dsh\node_modules\@deepseek-ai\dsh-desktop-host\lib\cli.js" --profile e5-live-science --from-default-profile web --patch "<WORK_ROOT>\public\harness-management-bootstrap.patch.yml" --json -'
    $info.WorkingDirectory="$e5Root\cells"
    $info.UseShellExecute=$false
    $info.CreateNoWindow=$true
    $info.RedirectStandardInput=$true
    $info.RedirectStandardOutput=$true
    $info.RedirectStandardError=$true
    $info.StandardOutputEncoding=[Text.Encoding]::UTF8
    $info.StandardErrorEncoding=[Text.Encoding]::UTF8
    $process=New-Object Diagnostics.Process
    $process.StartInfo=$info
    [void]$process.Start()
    $e5Result.pid=$process.Id
    $stdout=$process.StandardOutput.ReadToEndAsync()
    $stderr=$process.StandardError.ReadToEndAsync()
    $process.StandardInput.Write([IO.File]::ReadAllText((Join-Path $e5Root "public\$e5PromptFile")))
    $process.StandardInput.Close()
    if(!$process.WaitForExit(600000)){ $process.Kill(); throw 'Harness management timeout (600s)' }
    $e5Result.exit_code=$process.ExitCode
    [IO.File]::WriteAllText("$e5Out.stderr.txt",$stderr.Result,[Text.UTF8Encoding]::new($false))
    $visible=New-Object Collections.Generic.List[string]
    foreach($line in ($stdout.Result -split "`n")) {
        if(!$line.Trim()){continue}
        try {$event=ConvertFrom-Json -InputObject $line -ErrorAction Stop} catch {throw 'Unexpected non-JSON Harness stdout; cannot publish event trace'}
        if($event.type -eq 'thinking'){continue}
        $visible.Add($line.TrimEnd("`r"))
    }
    [IO.File]::WriteAllLines("$e5Out.projected.jsonl",$visible,[Text.UTF8Encoding]::new($false))
} catch { $e5Result.error=$_.Exception.Message }
$e5Result.ended_at_utc=[DateTime]::UtcNow.ToString('o')
[IO.File]::WriteAllText("$e5Out.result.json",(ConvertTo-Json -InputObject $e5Result -Depth 5),[Text.UTF8Encoding]::new($false))
