param([switch]$Uninstall)
$ErrorActionPreference='Stop'
if(-not ([Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Execute como Administrador'}
$root=Join-Path $env:ProgramData 'CapivaraDSM\Agent';$task='Capivara DSM Agent'
if($Uninstall){Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue;Remove-Item $root -Recurse -Force -ErrorAction SilentlyContinue;Write-Host 'CAPIVARA_AGENT_REMOVED';exit 0}
if(-not(Test-Path $root)){throw 'Agent não instalado'}
$runtime=Join-Path $root 'runtime\agent.py';if(-not(Test-Path $runtime)){throw 'Runtime incompleto; reinstale pela Dashboard'}
$python=(Get-Command python.exe -ErrorAction Stop).Source
$action=New-ScheduledTaskAction -Execute $python -Argument ('"{0}"' -f $runtime) -WorkingDirectory (Split-Path $runtime)
$trigger=New-ScheduledTaskTrigger -AtStartup
$settings=New-ScheduledTaskSettingsSet -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings -User 'SYSTEM' -RunLevel Highest -Force|Out-Null
Start-ScheduledTask -TaskName $task;Write-Host 'CAPIVARA_AGENT_REPAIRED'
