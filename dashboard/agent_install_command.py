#!/usr/bin/env python3
"""Generate the minimal administrator command for Linux Agent installation."""

from __future__ import annotations

import shlex

DEFAULT_BOOTSTRAP_URL = (
    "https://raw.githubusercontent.com/EzequielRibeiro/Distributed-Server-Manager/"
    "main/agents/linux/installer/install-agent.sh"
)


def linux_agent_install_command(
    *,
    controller_url: str,
    pairing_token: str,
    bootstrap_url: str = DEFAULT_BOOTSTRAP_URL,
) -> str:
    controller_url = str(controller_url).strip().rstrip("/")
    pairing_token = str(pairing_token).strip()
    bootstrap_url = str(bootstrap_url).strip()
    if not controller_url or not pairing_token or not bootstrap_url:
        raise ValueError("controller_url, pairing_token and bootstrap_url are required")
    return (
        f"curl -fsSL {shlex.quote(bootstrap_url)} | sudo bash -s -- "
        f"--controller-url {shlex.quote(controller_url)} "
        f"--pairing-token {shlex.quote(pairing_token)}"
    )
