param(
    [string]$InstallRoot = "$env:ProgramFiles\CapivaraAgent",
    [string]$DataRoot = "$env:ProgramData\CapivaraAgent",
    [string]$TaskName = "CapivaraAgent",
    [switch]$Purge
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) { throw "[Capivara Agent] $Message" }

function Assert-SafeRoot([string]$Path, [string]$Label) {
    if ([string]::IsNullOrWhiteSpace($Path)) { Fail "$Label vazio" }
    $full = [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    $driveRoot = [System.IO.Path]::GetPathRoot($full).TrimEnd('\')
    if ($full -eq $driveRoot) { Fail "$Label não pode ser a raiz do volume" }
    if ($full.Length -lt 10) { Fail "$Label inseguro: $full" }
    return $full
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail "execute o PowerShell como Administrador"
}

$InstallRoot = Assert-SafeRoot $InstallRoot "InstallRoot"
$DataRoot = Assert-SafeRoot $DataRoot "DataRoot"

# Serialize concurrent/retried uninstall launches. A duplicate detached launcher may
# still start after a Controller retry, but only one uninstall body runs at a time.
$mutex = New-Object System.Threading.Mutex($false, "Global\CapivaraAgentUninstall")
$lockAcquired = $false
try {
    $lockAcquired = $mutex.WaitOne(0)
    if (-not $lockAcquired) {
        Write-Host "[Capivara Agent] outra desinstalação já está em andamento; encerrando tentativa duplicada."
        exit 0
    }

    Write-Host "[Capivara Agent] removendo integração do Windows..."

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue } catch {}
        Start-Sleep -Milliseconds 800
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    }

    $installRegex = [regex]::Escape($InstallRoot)
    $dataRegex = [regex]::Escape($DataRoot)

    # preserve-data must not terminate game-server processes merely because their
    # command line references DataRoot\instances. Only Agent/runtime processes
    # under InstallRoot are stopped. purge may additionally stop DataRoot users.
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ProcessId -ne $PID -and
            $_.CommandLine -and
            (
                $_.CommandLine -match $installRegex -or
                ($Purge -and $_.CommandLine -match $dataRegex)
            )
        } |
        ForEach-Object {
            try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}
        }

    $desktop = [Environment]::GetFolderPath('CommonDesktopDirectory')
    $startup = [Environment]::GetFolderPath('CommonStartup')
    foreach ($shortcut in @(
        $(if ($desktop) { Join-Path $desktop 'Capivara Agent.lnk' }),
        $(if ($startup) { Join-Path $startup 'Capivara Agent Tray.lnk' })
    )) {
        if ($shortcut) { Remove-Item $shortcut -Force -ErrorAction SilentlyContinue }
    }

    if (Test-Path $DataRoot -PathType Container) {
        if ($Purge) {
            Remove-Item $DataRoot -Recurse -Force -ErrorAction Stop
        } else {
            $preserve = @('instances', 'backups')
            Get-ChildItem $DataRoot -Force -ErrorAction SilentlyContinue |
                Where-Object { $preserve -notcontains $_.Name } |
                Remove-Item -Recurse -Force -ErrorAction Stop

            $remaining = @(Get-ChildItem $DataRoot -Force -ErrorAction SilentlyContinue)
            if ($remaining.Count -eq 0) {
                Remove-Item $DataRoot -Force -ErrorAction SilentlyContinue
            }
        }
    }

    if (Test-Path $InstallRoot -PathType Container) {
        Remove-Item $InstallRoot -Recurse -Force -ErrorAction Stop
    }

    if ($Purge) {
        Write-Host "[Capivara Agent] desinstalação completa concluída (purge)."
    } else {
        Write-Host "[Capivara Agent] Agent removido. instances/backups foram preservados quando existentes."
    }
}
finally {
    if ($lockAcquired) {
        try { $mutex.ReleaseMutex() } catch {}
    }
    $mutex.Dispose()
}
