$ErrorActionPreference='Stop'
$e5Root='<WORK_ROOT>'
$env:DSH_HOME="$e5Root\profile"
$env:DSH_TOOLS_MODE='native'
$env:DSH_PERMISSION_MODE='danger-full-access'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
Set-Location -LiteralPath "$e5Root\cells"
Get-Content -LiteralPath "$e5Root\public\install-science.prompt.txt" -Raw | & '<USER_HOME>\AppData\Local\Programs\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd' --profile e5-live-science --from-default-profile web --patch "$e5Root\public\harness-management-bootstrap.patch.yml" --json - 1> "$e5Root\cells\install-science.projected.jsonl" 2> "$e5Root\cells\install-science.stderr.txt"
$e5Rc=$LASTEXITCODE
Set-Content -LiteralPath "$e5Root\cells\install-science.exit-code.txt" -Value $e5Rc
exit $e5Rc
