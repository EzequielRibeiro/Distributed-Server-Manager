#!/usr/bin/env python3
"""Secure Windows Agent deployment over WinRM HTTPS.

The Dashboard never accepts a Windows password.  An administrator prepares a
certificate mapping once and subsequent deployments authenticate with the
Controller certificate stored in its private state directory.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class WinRMDeployError(RuntimeError):
    pass


_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")


def validate_winrm_host(value: str) -> str:
    host = str(value or "").strip().strip("[]")
    if not host or any(char in host for char in " /\\@;`$\n\r\t"):
        raise WinRMDeployError("invalid WinRM host")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not _HOST_RE.fullmatch(host):
            raise WinRMDeployError("invalid WinRM host")
    return host


@dataclass(frozen=True)
class WinRMOptions:
    host: str
    port: int = 5986
    certificate_pem: str | None = None
    private_key_pem: str | None = None
    server_certificate_validation: str = "validate"
    connect_timeout: int = 15
    operation_timeout: int = 60

    def __post_init__(self) -> None:
        object.__setattr__(self, "host", validate_winrm_host(self.host))
        if not 1 <= int(self.port) <= 65535:
            raise WinRMDeployError("WinRM port must be between 1 and 65535")
        if self.server_certificate_validation not in {"validate", "ignore"}:
            raise WinRMDeployError("invalid server certificate validation policy")

    @property
    def endpoint(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"https://{host}:{self.port}/wsman"


@dataclass(frozen=True)
class WinRMResult:
    status_code: int
    stdout: str
    stderr: str


class WinRMRunner(Protocol):
    def run_ps(self, options: WinRMOptions, script: str) -> WinRMResult: ...


class PyWinRMRunner:
    """Lazy pywinrm adapter so unrelated Controller commands need no dependency."""

    def run_ps(self, options: WinRMOptions, script: str) -> WinRMResult:
        try:
            import winrm  # type: ignore
        except ImportError as exc:
            raise WinRMDeployError(
                "WinRM support is not installed; install the Controller optional dependency pywinrm"
            ) from exc
        if not options.certificate_pem or not options.private_key_pem:
            raise WinRMDeployError("prepared WinRM certificate profile not found")
        session = winrm.Session(
            options.endpoint,
            cert_pem=options.certificate_pem,
            cert_key_pem=options.private_key_pem,
            transport="certificate",
            server_cert_validation=options.server_certificate_validation,
            read_timeout_sec=max(options.operation_timeout + 10, 30),
            operation_timeout_sec=options.operation_timeout,
        )
        try:
            response = session.run_ps(script)
        except Exception as exc:
            raise WinRMDeployError(f"WinRM connection failed: {exc}") from exc
        return WinRMResult(
            int(response.status_code),
            bytes(response.std_out or b"").decode("utf-8", "replace").strip(),
            bytes(response.std_err or b"").decode("utf-8", "replace").strip(),
        )


def _run(options: WinRMOptions, script: str, runner: WinRMRunner | None) -> WinRMResult:
    result = (runner or PyWinRMRunner()).run_ps(options, script)
    if result.status_code:
        detail = result.stderr or result.stdout or f"exit status {result.status_code}"
        raise WinRMDeployError(f"remote PowerShell failed: {detail[:2000]}")
    return result


def preflight_winrm(options: WinRMOptions, runner: WinRMRunner | None = None) -> dict[str, Any]:
    script = r"""
$ErrorActionPreference='Stop'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($identity)
[ordered]@{
  platform='windows'; architecture=$env:PROCESSOR_ARCHITECTURE
  hostname=$env:COMPUTERNAME
  administrator=$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  powershell=$PSVersionTable.PSVersion.ToString()
} | ConvertTo-Json -Compress
"""
    result = _run(options, script, runner)
    try:
        payload = json.loads(result.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise WinRMDeployError("invalid WinRM preflight response") from exc
    if not payload.get("administrator"):
        raise WinRMDeployError("prepared WinRM identity is not an Administrator")
    return payload


def remote_windows_agent_present(options: WinRMOptions, runner: WinRMRunner | None = None) -> bool:
    result = _run(
        options,
        "if (Test-Path 'C:\\ProgramData\\CapivaraDSM\\Agent') {'PRESENT'} else {'ABSENT'}",
        runner,
    )
    return result.stdout.splitlines()[-1:] == ["PRESENT"]


def bootstrap_windows_agent(
    options: WinRMOptions,
    *,
    controller_url: str,
    pairing_token: str,
    release_tag: str,
    runner: WinRMRunner | None = None,
) -> None:
    if not str(controller_url).startswith(("http://", "https://")):
        raise WinRMDeployError("Controller URL must use HTTP or HTTPS")
    # UTF-16LE encoded command avoids shell interpolation.  WinRM HTTPS protects
    # the one-time token in transit; neither the command nor token is logged.
    def psq(value: str) -> str:
        return "'" + str(value).replace("'", "''") + "'"
    url = str(controller_url).rstrip("/") + "/agent/install.ps1"
    script = (
        "$ErrorActionPreference='Stop';"
        f"$source=(Invoke-WebRequest -UseBasicParsing -Uri {psq(url)}).Content;"
        f"& ([scriptblock]::Create($source)) -ControllerUrl {psq(str(controller_url).rstrip('/'))} "
        f"-PairingToken {psq(pairing_token)} -ReleaseTag {psq(release_tag)};"
        "if($LASTEXITCODE -and $LASTEXITCODE -ne 0){exit $LASTEXITCODE};'BOOTSTRAP_OK'"
    )
    result = _run(options, script, runner)
    if "BOOTSTRAP_OK" not in result.stdout:
        raise WinRMDeployError("Windows bootstrap did not confirm completion")


def default_profile_dir() -> Path:
    return Path(os.environ.get("DSM_WINRM_PROFILE_DIR", "/opt/dsm/.winrm"))


def profile_path(host: str, profile_dir: Path | None = None) -> Path:
    safe = validate_winrm_host(host).replace(":", "_").lower()
    return (profile_dir or default_profile_dir()) / f"{safe}.json"


def load_winrm_profile(host: str, profile_dir: Path | None = None) -> WinRMOptions:
    path = profile_path(host, profile_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WinRMDeployError(f"WinRM is not prepared for {host}; run cap agent winrm-prepare") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise WinRMDeployError(f"invalid WinRM profile: {path}") from exc
    return WinRMOptions(
        host=host,
        port=int(data.get("port", 5986)),
        certificate_pem=str(path.parent / data["certificate"]),
        private_key_pem=str(path.parent / data["private_key"]),
        server_certificate_validation=str(data.get("server_certificate_validation", "validate")),
    )


__all__ = [
    "WinRMDeployError", "WinRMOptions", "WinRMResult", "PyWinRMRunner",
    "preflight_winrm", "remote_windows_agent_present", "bootstrap_windows_agent",
    "load_winrm_profile", "profile_path", "validate_winrm_host",
]
