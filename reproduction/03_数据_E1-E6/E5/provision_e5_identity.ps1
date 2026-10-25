param()
$ErrorActionPreference = 'Stop'
$e5Root = '<WORK_ROOT>'
$e5Evidence = '<USER_HOME>\Desktop\论文\e2和e5重构计划\E5_执行_2026-10-12_v4_01'
$e5Repo = '<REPO_ROOT>'
$e5App = '<USER_HOME>\AppData\Local\Programs\DeepSeek Harness'
$e5UserSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$e5Names = @('E5HarnessV4', 'E5Scorer')
$e5Created = @()
$e5AclBefore = @()
$e5Result = [ordered]@{ schema='e5-os-provision-v1'; status='INCOMPLETE'; experiment_units=0; root=$e5Root; created=@(); acl_changes=@(); error=$null }

function Add-E5Rule($acl, $sid, $rights, $kind, $inherit=$true) {
    $flags = if ($inherit) { [Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit' } else { [Security.AccessControl.InheritanceFlags]::None }
    $rule = New-Object Security.AccessControl.FileSystemAccessRule($sid, $rights, $flags, [Security.AccessControl.PropagationFlags]::None, $kind)
    [void]$acl.AddAccessRule($rule)
}
function Set-E5DedicatedAcl($path, $grants) {
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    Add-E5Rule $acl $e5UserSid 'FullControl' 'Allow'
    Add-E5Rule $acl ([Security.Principal.SecurityIdentifier]'S-1-5-32-544') 'FullControl' 'Allow'
    Add-E5Rule $acl ([Security.Principal.SecurityIdentifier]'S-1-5-18') 'FullControl' 'Allow'
    foreach ($grant in $grants) { Add-E5Rule $acl $grant.Sid $grant.Rights 'Allow' $grant.Inherit }
    Set-Acl -LiteralPath $path -AclObject $acl
}
function Add-E5ScopedAcl($path, $sid, $rights, $kind) {
    if (!(Test-Path -LiteralPath $path)) { throw "ACL target missing: $path" }
    $acl = Get-Acl -LiteralPath $path
    $e5AclBefore += [ordered]@{path=$path; sddl=$acl.Sddl}
    # No recursive reset, deletion or owner change: one new named SID ACE only.
    Add-E5Rule $acl $sid $rights $kind ((Get-Item -LiteralPath $path).PSIsContainer)
    Set-Acl -LiteralPath $path -AclObject $acl
    $script:e5AclBefore = $e5AclBefore
    $script:e5Result.acl_changes += [ordered]@{path=$path; sid=$sid.Value; rights=$rights; type=$kind; recursive_reset=$false}
}
try {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator token required' }
    foreach ($name in $e5Names) { if (Get-LocalUser -Name $name -ErrorAction SilentlyContinue) { throw "Refuse reusing pre-existing account: $name" } }
    if (Test-Path -LiteralPath $e5Root) { throw "Refuse reusing root: $e5Root" }
    foreach ($path in @($e5Repo, $e5App)) { if (!(Test-Path -LiteralPath $path)) { throw "Missing path: $path" } }
    [void](New-Item -ItemType Directory -Path $e5Root)
    Set-E5DedicatedAcl $e5Root @()
    foreach ($name in $e5Names) {
        $bytes = New-Object byte[] 30
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        $password = ConvertTo-SecureString ('E5!a9' + [Convert]::ToBase64String($bytes)) -AsPlainText -Force
        $user = New-LocalUser -Name $name -Password $password -AccountExpires (Get-Date).AddDays(7) -Description 'E5 v4 isolated experiment identity; not a model login account' -UserMayNotChangePassword
        $e5Created += $name
        Add-LocalGroupMember -SID ([Security.Principal.SecurityIdentifier]'S-1-5-32-545') -Member $user
        $credential = New-Object Management.Automation.PSCredential("$env:COMPUTERNAME\$name", $password)
        $credential | Export-Clixml -LiteralPath (Join-Path $e5Root "$name.credential.clixml")
        $e5Result.created += [ordered]@{name=$name; sid=$user.SID.Value; admin=$false; expires='7 days'; password_logged=$false; credential_protection='DPAPI under current user; ACL admin/current user only'}
    }
    $harnessSid = (Get-LocalUser -Name 'E5HarnessV4').SID
    $scorerSid = (Get-LocalUser -Name 'E5Scorer').SID
    foreach ($name in @('public','profile','cells','private','evidence')) { [void](New-Item -ItemType Directory -Path (Join-Path $e5Root $name)) }
    Set-E5DedicatedAcl (Join-Path $e5Root 'public') @(@{Sid=$harnessSid;Rights='ReadAndExecute';Inherit=$true}, @{Sid=$scorerSid;Rights='ReadAndExecute';Inherit=$true})
    foreach ($name in @('profile','cells')) { Set-E5DedicatedAcl (Join-Path $e5Root $name) @(@{Sid=$harnessSid;Rights='Modify';Inherit=$true}) }
    Set-E5DedicatedAcl (Join-Path $e5Root 'private') @(@{Sid=$scorerSid;Rights='Modify';Inherit=$true})
    Set-E5DedicatedAcl (Join-Path $e5Root 'evidence') @(@{Sid=$scorerSid;Rights='Modify';Inherit=$true})
    # Allow installed executable/runtime reads without opening the user's home.
    Add-E5ScopedAcl $e5App $harnessSid 'ReadAndExecute' 'Allow'
    # Existing G: source roots grant Authenticated Users read/modify. A new account
    # alone therefore is insufficient; explicitly deny the experimental identity.
    Add-E5ScopedAcl $e5Repo $harnessSid 'FullControl' 'Deny'
    foreach ($path in @('<TOOL_ROOT>\deepseek\.dsh\sessions', '<TOOL_ROOT>\deepseek\.dsh\.credentials.yaml', '<TOOL_ROOT>\deepseek\.science')) {
        if (Test-Path -LiteralPath $path) { Add-E5ScopedAcl $path $harnessSid 'FullControl' 'Deny' }
    }
    Copy-Item -LiteralPath (Join-Path $e5Repo 'evals\ablation\items.yaml') -Destination (Join-Path $e5Root 'private\items.yaml')
    Set-Content -LiteralPath (Join-Path $e5Root 'public\positive-control.txt') -Value 'E5_PUBLIC_POSITIVE_CONTROL' -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $e5Root 'private\negative-control.txt') -Value ([Guid]::NewGuid().ToString()) -Encoding UTF8
    $e5Result.status = 'PROVISIONED_UNVERIFIED'
} catch {
    $e5Result.error = $_.Exception.Message
    # Fail closed: partially prepared identities cannot be used as a PASS gate.
    foreach ($name in $e5Created) { Disable-LocalUser -Name $name -ErrorAction SilentlyContinue }
    $e5Result.status = 'FAILED_INCOMPLETE_ACCOUNTS_DISABLED'
} finally {
    $e5Result.finished_at_utc = [DateTime]::UtcNow.ToString('o')
    ConvertTo-Json -InputObject @($e5AclBefore) -Depth 6 | Set-Content -LiteralPath (Join-Path $e5Evidence 'os-acl-before.json') -Encoding UTF8
    ConvertTo-Json -InputObject $e5Result -Depth 6 | Set-Content -LiteralPath (Join-Path $e5Evidence 'os-provision-result.json') -Encoding UTF8
}
