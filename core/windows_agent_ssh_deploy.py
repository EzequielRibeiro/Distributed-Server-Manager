#!/usr/bin/env python3
"""Windows Agent bootstrap over OpenSSH with explicit success verification."""
from __future__ import annotations

import json

from core.agent_ssh_deploy import (
    AgentDeployError,
    SSHDeployOptions,
    SSHRunner,
    _default_runner,
    _powershell_encoded_command,
    _reason,
    _run_ssh,
)

_BOOTSTRAP_OK = "CAPIVARA_WINDOWS_BOOTSTRAP_OK"
_VERIFY_OK = "CAPIVARA_WINDOWS_INSTALL_VERIFY_OK"


def _windows_bootstrap_stdin(
    controller_url: str,
    pairing_token: str,
    release_tag: str,
) -> str:
    payload = json.dumps(
        {
            "controller_url": controller_url,
            "pairing_token": pairing_token,
            "release_tag": release_tag,
        }
    ).replace("'", "''")
    return (
        "$utf8 = New-Object System.Text.UTF8Encoding($false)\n"
        "[Console]::OutputEncoding = $utf8\n"
        "$OutputEncoding = $utf8\n"
        "$ProgressPreference='SilentlyContinue'\n"
        "$ErrorActionPreference='Stop'\n"
        "try {\n"
        f"  $payload=ConvertFrom-Json '{payload}'\n"
        "  $url=$payload.controller_url.TrimEnd('/')+'/agent/install.ps1'\n"
        "  $script=(Invoke-WebRequest -UseBasicParsing -Uri $url).Content\n"
        "  & ([scriptblock]::Create($script)) -ControllerUrl $payload.controller_url "
        "-PairingToken $payload.pairing_token -ReleaseTag $payload.release_tag\n"
        "  if (-not (Test-Path 'C:\\Program Files\\CapivaraAgent\\runtime\\agent.py' -PathType Leaf)) { throw 'runtime agent.py not installed' }\n"
        "  if (-not (Test-Path 'C:\\ProgramData\\CapivaraAgent\\agent.json' -PathType Leaf)) { throw 'agent.json not installed' }\n"
        "  if (-not (Get-ScheduledTask -TaskName 'CapivaraAgent' -ErrorAction SilentlyContinue)) { throw 'CapivaraAgent scheduled task not installed' }\n"
        f"  Write-Output '{_BOOTSTRAP_OK}'\n"
        "} catch {\n"
        "  [Console]::Error.WriteLine('CAPIVARA_BOOTSTRAP_ERROR: ' + $_.Exception.Message)\n"
        "  exit 1\n"
        "}\n"
    )


def _installed_state_command(success_marker: str) -> str:
    powershell = (
        "$ErrorActionPreference='Stop';"
        "$runtime=Test-Path 'C:\\Program Files\\CapivaraAgent\\runtime\\agent.py' -PathType Leaf;"
        "$config=Test-Path 'C:\\ProgramData\\CapivaraAgent\\agent.json' -PathType Leaf;"
        "$task=$null -ne (Get-ScheduledTask -TaskName 'CapivaraAgent' -ErrorAction SilentlyContinue);"
        f"if($runtime -and $config -and $task){{Write-Output '{success_marker}';exit 0}}else{{exit 1}}"
    )
    return _powershell_encoded_command(powershell)


def remote_windows_agent_present_ssh(
    options: SSHDeployOptions,
    *,
    runner: SSHRunner = _default_runner,
) -> bool:
    """Return true when any current Windows Agent installation artifact exists."""
    powershell = (
        "$runtime=Test-Path 'C:\\Program Files\\CapivaraAgent\\runtime\\agent.py' -PathType Leaf;"
        "$config=Test-Path 'C:\\ProgramData\\CapivaraAgent\\agent.json' -PathType Leaf;"
        "$task=$null -ne (Get-ScheduledTask -TaskName 'CapivaraAgent' -ErrorAction SilentlyContinue);"
        "if($runtime -or $config -or $task){exit 0}else{exit 1}"
    )
    result = _run_ssh(
        options,
        _powershell_encoded_command(powershell),
        runner=runner,
        timeout=options.connect_timeout + 8,
    )
    return result.returncode == 0


def bootstrap_windows_agent_ssh(
    options: SSHDeployOptions,
    *,
    controller_url: str,
    pairing_token: str,
    release_tag: str = "latest",
    runner: SSHRunner = _default_runner,
    timeout: int = 900,
) -> None:
    controller_url = str(controller_url or "").strip().rstrip("/")
    pairing_token = str(pairing_token or "").strip()
    release_tag = str(release_tag or "latest").strip()
    if not controller_url.startswith(("http://", "https://")):
        raise AgentDeployError("controller_url must use http:// or https://")
    if not pairing_token:
        raise AgentDeployError("pairing token is required")

    result = _run_ssh(
        options,
        "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command -",
        runner=runner,
        stdin_text=_windows_bootstrap_stdin(
            controller_url,
            pairing_token,
            release_tag,
        ),
        timeout=timeout,
    )
    if result.returncode != 0 or _BOOTSTRAP_OK not in result.stdout:
        raise AgentDeployError(
            "Windows Agent bootstrap failed: "
            + _reason(result, "remote Windows Agent bootstrap did not confirm installation")
        )

    verified = _run_ssh(
        options,
        _installed_state_command(_VERIFY_OK),
        runner=runner,
        timeout=options.connect_timeout + 12,
    )
    if verified.returncode != 0 or _VERIFY_OK not in verified.stdout:
        raise AgentDeployError(
            "Windows Agent bootstrap failed: "
            + _reason(verified, "remote Windows Agent post-install verification failed")
        )


__all__ = [
    "bootstrap_windows_agent_ssh",
    "remote_windows_agent_present_ssh",
]
