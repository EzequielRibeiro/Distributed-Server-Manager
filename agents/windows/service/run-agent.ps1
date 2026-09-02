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

# Windows PowerShell 5.1 converts native stderr redirected with *>> into
# NativeCommandError records. Besides being noisy, with strict error handling
# that behavior used to terminate this long-running launcher on routine Agent
# transport failures. Keep PowerShell strict for launcher setup and let cmd.exe
# perform only the native stdout/stderr redirection so agent.log receives the
# Python output verbatim while the Python process remains the source of truth
# for the exit code.
foreach ($path in @($PythonExe, $scriptToRun, $logPath)) {
    if ($path.Contains('"')) {
        throw "Unsupported quote character in launcher path: $path"
    }
}

$commandLine = '""{0}" "{1}" >> "{2}" 2>&1"' -f $PythonExe, $scriptToRun, $logPath
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    & $env:ComSpec /d /s /c $commandLine
    $pythonExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}

if ($null -eq $pythonExitCode) {
    $pythonExitCode = 1
}
exit $pythonExitCode
