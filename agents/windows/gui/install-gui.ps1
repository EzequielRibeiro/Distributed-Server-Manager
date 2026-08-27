param(
    [string]$InstallRoot = "$env:ProgramFiles\CapivaraAgent",
    [string]$DataRoot = "$env:ProgramData\CapivaraAgent",
    [ValidateSet('auto','on','off')][string]$GuiMode = 'auto'
)
$ErrorActionPreference='Stop'
function Test-GuiAvailable {
    if (-not (Test-Path "$env:WINDIR\explorer.exe" -PathType Leaf)) { return $false }
    try { Add-Type -AssemblyName PresentationFramework -ErrorAction Stop; Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop; return $true } catch { return $false }
}
function New-CapivaraShortcut([string]$Path,[string]$Arguments) {
    $shell=New-Object -ComObject WScript.Shell;$shortcut=$shell.CreateShortcut($Path)
    $shortcut.TargetPath="$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe";$shortcut.Arguments=$Arguments;$shortcut.WorkingDirectory=$InstallRoot;$shortcut.Description='Capivara Agent - Administração local';$shortcut.IconLocation="$env:WINDIR\System32\shell32.dll,13";$shortcut.Save()
}
$available=Test-GuiAvailable
$enabled=if($GuiMode -eq 'on'){if(-not $available){throw 'GuiMode=on solicitado, mas o Windows não oferece shell gráfico/WPF'};$true}elseif($GuiMode -eq 'off'){$false}else{$available}
$desktop=[Environment]::GetFolderPath('CommonDesktopDirectory');$startup=[Environment]::GetFolderPath('CommonStartup')
$desktopShortcut=if($desktop){Join-Path $desktop 'Capivara Agent.lnk'}else{$null};$startupShortcut=if($startup){Join-Path $startup 'Capivara Agent Tray.lnk'}else{$null}
if(-not $enabled){
    foreach($path in @($desktopShortcut,$startupShortcut)){if($path -and (Test-Path $path)){Remove-Item $path -Force}}
    Write-Output '{"gui_enabled":false}';exit 0
}
$main=Join-Path $InstallRoot 'gui\CapivaraAgentGui.ps1';$bridge=Join-Path $InstallRoot 'gui\Invoke-CapivaraAdminCommand.ps1'
if(-not (Test-Path $main -PathType Leaf) -or -not (Test-Path $bridge -PathType Leaf)){throw 'arquivos da GUI do Capivara Agent não estão instalados'}
New-Item -ItemType Directory -Force -Path "$DataRoot\state\gui","$DataRoot\logs" | Out-Null
& icacls "$DataRoot\state\gui" /grant:r "*S-1-5-32-545:(OI)(CI)RX" | Out-Null
& icacls "$DataRoot\logs" /grant:r "*S-1-5-32-545:(OI)(CI)RX" | Out-Null
$guiArgs='-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -InstallRoot "{1}" -DataRoot "{2}"' -f $main,$InstallRoot,$DataRoot;$trayArgs=$guiArgs+' -TrayOnly'
if($desktopShortcut){New-CapivaraShortcut $desktopShortcut $guiArgs};if($startupShortcut){New-CapivaraShortcut $startupShortcut $trayArgs}
Write-Output '{"gui_enabled":true}'
