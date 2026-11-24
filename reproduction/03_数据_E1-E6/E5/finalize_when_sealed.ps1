$ErrorActionPreference='Stop'
$e5Root='<WORK_ROOT>'
$e5Evidence=Join-Path $e5Root 'evidence'
$e5Status=[ordered]@{schema='e5-one-shot-local-finalizer-v1';started_at_utc=[DateTime]::UtcNow.ToString('o');status='waiting_complete_seal';logical_e5_units=0;error=$null}
try {
 $e5Deadline=[DateTime]::UtcNow.AddHours(12)
 while(!(Test-Path -LiteralPath (Join-Path $e5Evidence 'collector-COMPLETE-v51.json'))){
  if(Test-Path -LiteralPath (Join-Path $e5Evidence 'confirmatory-INCOMPLETE-v5.json')){throw 'matrix incomplete; scoring forbidden'}
  if([DateTime]::UtcNow -gt $e5Deadline){throw 'finalizer wait timeout; no fabricated completion'}
  Start-Sleep -Seconds 5
 }
 $e5Freeze=Get-Content -LiteralPath (Join-Path $e5Root 'private\confirmatory-v51\freeze.json') -Raw | ConvertFrom-Json
 foreach($e5Property in $e5Freeze.private_files.PSObject.Properties){
  if($e5Property.Name -in @('collector.py','RunJournal.py')){continue}
  $e5File=Join-Path $e5Root ('private\confirmatory-v51\'+$e5Property.Name)
  if(([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([IO.File]::ReadAllBytes($e5File)))).Replace('-','').ToLower() -ne $e5Property.Value){throw "frozen private asset drift: $($e5Property.Name)"}
 }
 $e5ScorerCredential=Import-Clixml -LiteralPath (Join-Path $e5Root 'E5Scorer.credential.clixml')
 $e5Scorer=Start-Process -FilePath 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File "<WORK_ROOT>\public\score_complete_v51.ps1"' -WorkingDirectory (Join-Path $e5Root 'public') -Credential $e5ScorerCredential -LoadUserProfile -WindowStyle Hidden -PassThru
 $e5Status.scorer_wrapper_pid=$e5Scorer.Id
 $e5Scorer.WaitForExit()
 $e5ScorerExit=[IO.File]::ReadAllText((Join-Path $e5Evidence 'scorer-v51.exit.txt')).Trim()
 if($e5ScorerExit -ne '0'){throw "independent scorer failed: $e5ScorerExit"}
 & 'G:\python.data\python.exe' '<USER_HOME>\Desktop\论文\e2和e5重构计划\E5_执行_2026-10-12_v4_01\render_final_report.py' 1> (Join-Path $e5Evidence 'report-v51.stdout.txt') 2> (Join-Path $e5Evidence 'report-v51.stderr.txt')
 if($LASTEXITCODE -ne 0){throw "report generation failed: $LASTEXITCODE"}
 $e5Status.status='complete';$e5Status.logical_e5_units=2016;$e5Status.human_review='pending post-run'
} catch { $e5Status.status='incomplete_or_failed';$e5Status.error=$_.Exception.Message }
$e5Status.ended_at_utc=[DateTime]::UtcNow.ToString('o')
[IO.File]::WriteAllText((Join-Path $e5Evidence 'FINALIZER-RESULT-v51.json'),(ConvertTo-Json $e5Status -Depth 6),[Text.UTF8Encoding]::new($false))
