param(
    [Parameter(Mandatory=$true)][string]$ControllerUrl,
    [Parameter(Mandatory=$true)][string]$PairingToken,
    [string]$ReleaseTag = $env:CAPIVARA_RELEASE_TAG,
    [string]$Repository = "EzequielRibeiro/Distributed-Server-Manager"
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ReleaseTag)) { throw "ReleaseTag não definido pelo Controller" }
$version = $ReleaseTag.TrimStart('v')
$archiveName = "capivara-agent-windows-$version.zip"
$base = "https://github.com/$Repository/releases/download/$ReleaseTag"
$temp = Join-Path ([IO.Path]::GetTempPath()) ("capivara-agent-win-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp | Out-Null
try {
    $archive = Join-Path $temp $archiveName
    $checksum = "$archive.sha256"
    Invoke-WebRequest -UseBasicParsing -Uri "$base/$archiveName" -OutFile $archive
    Invoke-WebRequest -UseBasicParsing -Uri "$base/$archiveName.sha256" -OutFile $checksum
    $expected = ((Get-Content $checksum -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
    $actual = (Get-FileHash -Algorithm SHA256 -Path $archive).Hash.ToLowerInvariant()
    if ($expected -ne $actual) { throw "checksum SHA-256 inválido" }
    $extract = Join-Path $temp "extract"
    Expand-Archive -Path $archive -DestinationPath $extract
    $package = Join-Path $extract "capivara-agent-windows-$version"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $package "install-agent.ps1") -ControllerUrl $ControllerUrl -PairingToken $PairingToken -PackageDir $package
    if ($LASTEXITCODE -ne 0) { throw "instalador Windows retornou erro $LASTEXITCODE" }
}
finally {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $temp
}
