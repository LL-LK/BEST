$ErrorActionPreference='Stop'
$env:ELECTRON_RUN_AS_NODE='1'
& '<USER_HOME>\AppData\Local\Programs\DeepSeek Harness\DeepSeek Harness.exe' --expose-internals '<WORK_ROOT>\public\identity_probe.cjs'
$e5Rc=$LASTEXITCODE
Set-Content -LiteralPath '<WORK_ROOT>\cells\identity-proof.exit-code.txt' -Value $e5Rc
exit $e5Rc
