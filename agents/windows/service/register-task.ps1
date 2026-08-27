param(
    [Parameter(Mandatory=$true)][string]$PythonExe,
    [Parameter(Mandatory=$true)][string]$AgentScript,
    [string]$TaskName = "CapivaraAgent",
    [string]$DataRoot = "$env:ProgramData\CapivaraAgent",
    [string]$LauncherScript = "$PSScriptRoot\run-agent.ps1"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $LauncherScript -PathType Leaf)) { throw "launcher do Agent não encontrado: $LauncherScript" }
$arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -PythonExe "{1}" -AgentScript "{2}" -DataRoot "{3}"' -f $LauncherScript,$PythonExe,$AgentScript,$DataRoot
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Capivara Agent task registered: $TaskName"
