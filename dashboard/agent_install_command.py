#!/usr/bin/env python3
"""Generate the minimal administrator command for Linux Agent installation."""

from __future__ import annotations

import shlex


def linux_agent_install_command(*, controller_url: str, pairing_token: str) -> str:
    controller_url = str(controller_url).strip().rstrip("/")
    pairing_token = str(pairing_token).strip()
    if not controller_url or not pairing_token:
        raise ValueError("controller_url and pairing_token are required")
    bootstrap_url = controller_url + "/agent/install.sh"
    return (
        f"curl -fsSL {shlex.quote(bootstrap_url)} | sudo bash -s -- "
        f"--controller-url {shlex.quote(controller_url)} "
        f"--pairing-token {shlex.quote(pairing_token)}"
    )
