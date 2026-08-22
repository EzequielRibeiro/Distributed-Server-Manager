#!/usr/bin/env python3
"""Generate the minimal administrator command for Linux Agent installation."""

from __future__ import annotations

import shlex


def linux_agent_install_command(
    *, controller_url: str, pairing_token: str, release_tag: str | None = None
) -> str:
    controller_url = str(controller_url).strip().rstrip("/")
    pairing_token = str(pairing_token).strip()
    release_tag = str(release_tag or "latest").strip()
    if not controller_url or not pairing_token:
        raise ValueError("controller_url and pairing_token are required")
    bootstrap_url = controller_url + "/agent/install.sh"
    command = (
        f"curl -fsSL {shlex.quote(bootstrap_url)} | sudo bash -s -- "
        f"--controller-url {shlex.quote(controller_url)} "
        f"--pairing-token {shlex.quote(pairing_token)}"
    )
    if release_tag and release_tag != "latest":
        command += f" --version {shlex.quote(release_tag)}"
    return command
