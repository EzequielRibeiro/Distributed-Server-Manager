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

# The Windows package ships cap.cmd/cap.ps1 beside agent.py. Register the
# runtime directory once in the machine PATH so new administrative terminals
# can use `cap ...` without knowing installation paths. Keep the current
# process PATH in sync as well. This is idempotent and never removes unrelated
# PATH entries.
$runtimeDir = Split-Path -Parent $AgentScript
try {
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $parts = @($machinePath -split ';' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $present = $false
    foreach ($part in $parts) {
        if ($part.TrimEnd('\') -ieq $runtimeDir.TrimEnd('\')) {
            $present = $true
            break
        }
    }
    if (-not $present) {
        $newMachinePath = (($parts + $runtimeDir) -join ';')
        [Environment]::SetEnvironmentVariable('Path', $newMachinePath, 'Machine')
    }
    if (-not (($env:Path -split ';') | Where-Object { $_.TrimEnd('\') -ieq $runtimeDir.TrimEnd('\') })) {
        $env:Path = $env:Path.TrimEnd(';') + ';' + $runtimeDir
    }
} catch {
    # CLI PATH registration must never prevent the Agent from starting.
    Write-Warning "Capivara CLI PATH registration failed: $($_.Exception.Message)"
}

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
& $PythonExe $AgentScript *>> $logPath
exit $LASTEXITCODE
