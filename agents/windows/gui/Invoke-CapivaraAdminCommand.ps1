param(
    [Parameter(Mandatory=$true)][string]$PythonExe,
    [Parameter(Mandatory=$true)][string]$Backend,
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [Parameter(Mandatory=$true)][string]$EncodedCommand
)
$ErrorActionPreference = 'Stop'
try {
    $bytes = [Convert]::FromBase64String($EncodedCommand)
    $commandLine = [Text.Encoding]::UTF8.GetString($bytes)
    $tokens = @($commandLine.Trim() -split '\s+')
    $output = & $PythonExe $Backend command @tokens 2>&1 | Out-String
    Set-Content -Path $OutputPath -Value $output -Encoding UTF8
    exit $LASTEXITCODE
} catch {
    Set-Content -Path $OutputPath -Value $_.Exception.Message -Encoding UTF8
    exit 1
}
