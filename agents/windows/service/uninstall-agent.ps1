param(
    [string]$InstallRoot = "$env:ProgramFiles\CapivaraAgent",
    [string]$DataRoot = "$env:ProgramData\CapivaraAgent",
    [string]$TaskName = "CapivaraAgent",
    [string]$LauncherTaskName = "",
    [string]$TerminalIdentityPath = "",
    [string]$LaunchLockPath = "",
    [switch]$Purge
)

$ErrorActionPreference = "Stop"

$UninstallLog = Join-Path $env:TEMP "capivara-agent-uninstall.log"
$UninstallMode = if ($Purge) { "purge" } else { "preserve-data" }
$InstancesPresentBefore = $false
$BackupsPresentBefore = $false

function Write-UninstallLog([string]$Message) {
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    try {
        Add-Content -LiteralPath $UninstallLog -Value "$stamp $Message" -Encoding UTF8
    } catch {}
}

function Fail([string]$Message) {
    Write-UninstallLog "FAILED: $Message"
    throw "[Capivara Agent] $Message"
}

function Send-TerminalUninstallResult(
    [string]$Status,
    [string]$ErrorMessage
) {
    if ([string]::IsNullOrWhiteSpace($TerminalIdentityPath)) {
        return $false
    }

    if (-not (
        Test-Path `
            -LiteralPath $TerminalIdentityPath `
            -PathType Leaf
    )) {
        return $false
    }

    try {
        $terminalIdentity = Get-Content `
            -LiteralPath $TerminalIdentityPath `
            -Raw `
            -Encoding UTF8 |
            ConvertFrom-Json

        $controllerUrl = [string]$terminalIdentity.controller_url
        $agentId = [string]$terminalIdentity.agent_id
        $fingerprint = [string]$terminalIdentity.fingerprint
        $credentialId = [string]$terminalIdentity.credential_id
        $credentialSecret = [string]$terminalIdentity.credential_secret
        $requestId = [string]$terminalIdentity.request_id

        if (
            [string]::IsNullOrWhiteSpace($controllerUrl) -or
            [string]::IsNullOrWhiteSpace($agentId) -or
            [string]::IsNullOrWhiteSpace($fingerprint) -or
            [string]::IsNullOrWhiteSpace($credentialId) -or
            [string]::IsNullOrWhiteSpace($credentialSecret) -or
            [string]::IsNullOrWhiteSpace($requestId)
        ) {
            Write-UninstallLog (
                "TERMINAL_REPORT_FAILED status=" +
                $Status +
                " reason=identity-incomplete"
            )
            return $false
        }

        $uri = $controllerUrl.TrimEnd('/') +
            "/api/agent/uninstall/result"

        $headers = @{
            "X-Capivara-Agent-Credential" = $credentialId
            "X-Capivara-Agent-Secret" = $credentialSecret
            "X-Capivara-Agent-Fingerprint" = $fingerprint
        }

        $instancesPath = Join-Path $DataRoot "instances"
        $backupsPath = Join-Path $DataRoot "backups"
        $instancesPresentAfter = Test-Path -LiteralPath $instancesPath
        $backupsPresentAfter = Test-Path -LiteralPath $backupsPath

        $hostCleanup = @{
            mode = $UninstallMode
            install_root_removed = (-not (
                Test-Path -LiteralPath $InstallRoot
            ))
            agent_config_removed = (-not (
                Test-Path -LiteralPath (
                    Join-Path $DataRoot "agent.json"
                )
            ))
            instances_present_before = $InstancesPresentBefore
            instances_present_after = $instancesPresentAfter
            backups_present_before = $BackupsPresentBefore
            backups_present_after = $backupsPresentAfter
            instances_preserved = (
                $InstancesPresentBefore -and $instancesPresentAfter
            )
            backups_preserved = (
                $BackupsPresentBefore -and $backupsPresentAfter
            )
        }

        $payload = @{
            agent_id = $agentId
            request_id = $requestId
            status = $Status
            completed_at = (
                Get-Date
            ).ToUniversalTime().ToString(
                "yyyy-MM-ddTHH:mm:ssZ"
            )
            host_cleanup = $hostCleanup
        }

        if (-not [string]::IsNullOrWhiteSpace($ErrorMessage)) {
            $limit = [Math]::Min(
                1000,
                $ErrorMessage.Length
            )
            $payload.error = $ErrorMessage.Substring(
                0,
                $limit
            )
        }

        $body = $payload |
            ConvertTo-Json -Depth 5 -Compress

        if ($uri.StartsWith("https://")) {
            [Net.ServicePointManager]::SecurityProtocol = `
                [Net.SecurityProtocolType]::Tls12
        }

        for ($attempt = 1; $attempt -le 5; $attempt++) {
            try {
                Invoke-RestMethod `
                    -Method Post `
                    -Uri $uri `
                    -Headers $headers `
                    -ContentType "application/json" `
                    -Body $body `
                    -TimeoutSec 20 |
                    Out-Null

                Write-UninstallLog (
                    "TERMINAL status=" +
                    $Status +
                    " attempt=" +
                    $attempt
                )

                return $true
            }
            catch {
                if ($attempt -lt 5) {
                    Start-Sleep -Seconds (
                        [Math]::Min(10, 2 * $attempt)
                    )
                }
            }
        }

        Write-UninstallLog (
            "TERMINAL_REPORT_FAILED status=" +
            $Status
        )

        return $false
    }
    catch {
        Write-UninstallLog (
            "TERMINAL_REPORT_FAILED status=" +
            $Status
        )

        return $false
    }
}


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
$InstancesPresentBefore = Test-Path -LiteralPath (Join-Path $DataRoot "instances")
$BackupsPresentBefore = Test-Path -LiteralPath (Join-Path $DataRoot "backups")

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

    Write-UninstallLog "START mode=$UninstallMode install=$InstallRoot data=$DataRoot"

    # The detached worker can start a fraction of a second before the Agent and
    # its scheduled-task wrapper have fully released files. Give Windows a
    # deterministic grace period before destructive cleanup.
    Start-Sleep -Seconds 3

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

    Write-UninstallLog "COMPLETED"

    [void](
        Send-TerminalUninstallResult `
            -Status "completed" `
            -ErrorMessage ""
    )
}
catch {
    $failureMessage = $_.Exception.Message

    Write-UninstallLog (
        "ERROR: " + $failureMessage
    )

    [void](
        Send-TerminalUninstallResult `
            -Status "failed" `
            -ErrorMessage $failureMessage
    )

    throw
}
finally {
    if ($lockAcquired) {
        try { $mutex.ReleaseMutex() } catch {}
    }
    $mutex.Dispose()

    # Remove the temporary credential snapshot after terminal
    # reporting and before deleting the launcher task.
    if (-not [string]::IsNullOrWhiteSpace(
        $TerminalIdentityPath
    )) {
        try {
            Remove-Item `
                -LiteralPath $TerminalIdentityPath `
                -Force `
                -ErrorAction SilentlyContinue
        } catch {}
    }

    # Remove the detached-launch lock after the operation has
    # reached a terminal state.
    if (-not [string]::IsNullOrWhiteSpace(
        $LaunchLockPath
    )) {
        try {
            Remove-Item `
                -LiteralPath $LaunchLockPath `
                -Force `
                -ErrorAction SilentlyContinue
        } catch {}
    }

    # The remote launcher runs a staged copy from %TEMP%.
    # Delete that copy only for launcher-driven uninstalls.
    if (-not [string]::IsNullOrWhiteSpace(
        $LauncherTaskName
    )) {
        try {
            if (-not [string]::IsNullOrWhiteSpace(
                $PSCommandPath
            )) {
                Remove-Item `
                    -LiteralPath $PSCommandPath `
                    -Force `
                    -ErrorAction SilentlyContinue
            }
        } catch {}
    }

    # This script may itself be running from the temporary uninstall
    # Scheduled Task. Remove that task only after all destructive
    # cleanup and logging have finished.
    if (-not [string]::IsNullOrWhiteSpace($LauncherTaskName)) {
        try {
            Unregister-ScheduledTask `
                -TaskName $LauncherTaskName `
                -Confirm:$false `
                -ErrorAction SilentlyContinue
        } catch {}
    }
}
