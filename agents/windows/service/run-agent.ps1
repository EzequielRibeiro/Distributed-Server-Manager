param(
    [Parameter(Mandatory=$true)][string]$PythonExe,
    [Parameter(Mandatory=$true)][string]$AgentScript,
    [string]$DataRoot = "$env:ProgramData\CapivaraAgent"
)
$ErrorActionPreference = 'Stop'
$logDir = Join-Path $DataRoot 'logs'
$logPath = Join-Path $logDir 'agent.log'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$env:PYTHONUNBUFFERED = '1'
$env:CAPIVARA_AGENT_LOG = $logPath

function Rotate-AgentLog {
    if (-not (Test-Path $logPath)) { return }
    $item = Get-Item $logPath -ErrorAction SilentlyContinue
    if ($null -eq $item -or $item.Length -lt 10485760) { return }
    for ($i=4; $i -ge 1; $i--) {
        $source = "$logPath.$i"
        $target = "$logPath." + ($i + 1)
        if (Test-Path $source) { Move-Item $source $target -Force }
    }
    Move-Item $logPath "$logPath.1" -Force
}
Rotate-AgentLog

$runtimeDir = Split-Path -Parent $AgentScript
$entrypoint = Join-Path $runtimeDir 'agent_entrypoint.py'
$scriptToRun = if (Test-Path $entrypoint -PathType Leaf) { $entrypoint } else { $AgentScript }

& $PythonExe $scriptToRun *>> $logPath
exit $LASTEXITCODE
