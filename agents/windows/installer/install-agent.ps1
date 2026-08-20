param(
    [Parameter(Mandatory=$true)][string]$ControllerUrl,
    [Parameter(Mandatory=$true)][string]$PairingToken,
    [string]$PackageDir = $PSScriptRoot,
    [string]$InstallRoot = "$env:ProgramFiles\CapivaraAgent",
    [string]$DataRoot = "$env:ProgramData\CapivaraAgent",
    [string]$TaskName = "CapivaraAgent"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) { throw "[Capivara Agent] $Message" }

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail "execute o PowerShell como Administrador"
}
if ($ControllerUrl -notmatch '^https?://') { Fail "ControllerUrl inválida" }
if ([string]::IsNullOrWhiteSpace($PairingToken)) { Fail "PairingToken é obrigatório" }

$python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $python) { Fail "Python 3 não encontrado no PATH" }

$PackageDir = (Resolve-Path $PackageDir).Path
$required = @(
    "manifest.json", "VERSION",
    "agent\common\identity.py",
    "agent\runtime\agent.py", "agent\runtime\capabilities.py", "agent\runtime\network_inventory.py", "agent\runtime\update_client.py",
    "agent\updater\updater.py",
    "service\register-task.ps1"
)
foreach ($relative in $required) {
    if (-not (Test-Path (Join-Path $PackageDir $relative) -PathType Leaf)) { Fail "arquivo obrigatório ausente: $relative" }
}

$verify = @'
import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1])
manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
assert manifest.get('kind')=='CapivaraAgentPackage' and manifest.get('platform')=='windows', 'manifest Windows inválido'
version=(root/'VERSION').read_text(encoding='utf-8').strip()
assert manifest.get('version')==version, 'versão diverge do manifest'
for relative in manifest.get('required_files',[]):
    path=root/relative
    assert path.is_file(), f'arquivo ausente: {relative}'
    expected=(manifest.get('files',{}).get(relative) or {}).get('sha256')
    assert expected and hashlib.sha256(path.read_bytes()).hexdigest()==expected, f'hash inválido: {relative}'
'@
& $python -c $verify $PackageDir
if ($LASTEXITCODE -ne 0) { Fail "falha ao validar pacote" }

$version = (Get-Content (Join-Path $PackageDir "VERSION") -Raw).Trim()
New-Item -ItemType Directory -Force -Path "$InstallRoot\runtime", "$InstallRoot\common", "$InstallRoot\updater", "$InstallRoot\service", "$DataRoot\state" | Out-Null
Copy-Item (Join-Path $PackageDir "agent\runtime\*.py") "$InstallRoot\runtime" -Force
Copy-Item (Join-Path $PackageDir "agent\common\identity.py") "$InstallRoot\common\identity.py" -Force
Copy-Item (Join-Path $PackageDir "agent\updater\updater.py") "$InstallRoot\updater\updater.py" -Force
Copy-Item (Join-Path $PackageDir "service\register-task.ps1") "$InstallRoot\service\register-task.ps1" -Force
Copy-Item (Join-Path $PackageDir "manifest.json") "$InstallRoot\manifest.json" -Force
Set-Content -Path "$InstallRoot\VERSION" -Value $version -Encoding UTF8

$identityCode = @'
import importlib.util,json,pathlib,sys
p=pathlib.Path(sys.argv[1]); s=importlib.util.spec_from_file_location('cap_identity',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
print(json.dumps(m.generate_local_identity()))
'@
$identityJson = & $python -c $identityCode "$InstallRoot\common\identity.py"
if ($LASTEXITCODE -ne 0) { Fail "falha ao gerar identidade local" }
$localIdentity = $identityJson | ConvertFrom-Json
$config = [ordered]@{
    agent_id = $localIdentity.agent_id
    node_id = $localIdentity.node_id
    hostname = $localIdentity.hostname
    fingerprint = $localIdentity.fingerprint
    identity_nonce = $localIdentity.identity_nonce
    controller_url = $ControllerUrl.TrimEnd('/')
    pairing_token = $PairingToken
    capivara_version = $version
    heartbeat_interval_seconds = 30
    degraded_after_seconds = 60
    offline_after_seconds = 120
}
$config | ConvertTo-Json -Depth 6 | Set-Content -Path "$DataRoot\agent.json" -Encoding UTF8
& icacls "$DataRoot\agent.json" /inheritance:r /grant:r "SYSTEM:F" "Administrators:F" | Out-Null

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$InstallRoot\service\register-task.ps1" -PythonExe $python -AgentScript "$InstallRoot\runtime\agent.py" -TaskName $TaskName
if ($LASTEXITCODE -ne 0) { Fail "falha ao registrar supervisor do Agent" }
Write-Host "Capivara Agent Windows $version instalado. Enrollment e heartbeat usarão o mesmo protocolo do Agent Linux."
