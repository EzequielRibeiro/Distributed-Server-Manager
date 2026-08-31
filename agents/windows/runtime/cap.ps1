param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$CapArgs
)

$ErrorActionPreference = 'Stop'
$RuntimeRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Cli = Join-Path $RuntimeRoot 'local_cli.py'

if (-not (Test-Path -LiteralPath $Cli -PathType Leaf)) {
    Write-Error "Capivara CLI runtime not found: $Cli"
    exit 2
}

$python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $python) {
    $candidates = @(
        'C:\Program Files\Python313\python.exe',
        'C:\Program Files\Python312\python.exe',
        'C:\Program Files\Python311\python.exe'
    )
    $python = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if (-not $python) {
    Write-Error 'Python 3 runtime not found.'
    exit 2
}

& $python $Cli @CapArgs
exit $LASTEXITCODE
