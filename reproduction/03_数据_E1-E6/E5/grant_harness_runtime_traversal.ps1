$ErrorActionPreference='Stop'
$e5Output='<WORK_ROOT>\evidence\runtime-traversal-acl.json'
$e5Sid=(Get-LocalUser -Name 'E5HarnessV4').SID
$e5Record=[ordered]@{schema='e5-runtime-directory-traversal-v1';changes=@();error=$null}
try {
  if(Test-Path -LiteralPath $e5Output){throw 'refuse overwriting receipt'}
  foreach($path in @('<USER_HOME>','<USER_HOME>\AppData','<USER_HOME>\AppData\Local','<USER_HOME>\AppData\Local\Programs')) {
    $acl=Get-Acl -LiteralPath $path
    $before=$acl.Sddl
    # Self only: metadata/traverse, no directory listing or file-content access.
    $rule=New-Object Security.AccessControl.FileSystemAccessRule($e5Sid,[Security.AccessControl.FileSystemRights]'Traverse,ReadAttributes,ReadExtendedAttributes,Synchronize',[Security.AccessControl.InheritanceFlags]::None,[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow)
    [void]$acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $path -AclObject $acl
    $e5Record.changes += @{path=$path;before_sddl=$before;after_sddl=(Get-Acl -LiteralPath $path).Sddl;content_read_granted=$false;inheritable=$false}
  }
} catch {$e5Record.error=$_.Exception.Message}
[IO.File]::WriteAllText($e5Output,(ConvertTo-Json -InputObject $e5Record -Depth 6),[Text.UTF8Encoding]::new($false))
