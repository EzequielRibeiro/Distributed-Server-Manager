#!/usr/bin/env python3
"""Generate Windows Agent installation command without administrative secrets."""

from __future__ import annotations


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def windows_agent_install_command(
    *, controller_url: str, pairing_token: str, release_tag: str | None = None
) -> str:
    base = str(controller_url).strip().rstrip("/")
    token = str(pairing_token).strip()
    release_tag = str(release_tag or "latest").strip()
    if not base or not token:
        raise ValueError("controller_url and pairing_token are required")
    url = base + "/agent/install.ps1"
    command = (
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "
        + '"$script=(Invoke-WebRequest -UseBasicParsing -Uri '
        + _ps_quote(url)
        + ').Content; & ([scriptblock]::Create($script)) -ControllerUrl '
        + _ps_quote(base)
        + ' -PairingToken '
        + _ps_quote(token)
    )
    if release_tag and release_tag != "latest":
        command += " -ReleaseTag " + _ps_quote(release_tag)
    return command + '"'


__all__ = ["windows_agent_install_command"]
