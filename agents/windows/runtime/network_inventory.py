#!/usr/bin/env python3
"""Collect occupied TCP/UDP ports on Windows without third-party modules."""

from __future__ import annotations

import subprocess


def _parse_netstat(protocol: str) -> list[int]:
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", protocol],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    ports: set[int] = set()
    for raw in completed.stdout.splitlines():
        line = raw.strip()
        if not line.upper().startswith(protocol.upper()):
            continue
        fields = line.split()
        if len(fields) < 2:
            continue
        local = fields[1]
        port_text = local.rsplit(":", 1)[-1].strip("[]")
        try:
            port = int(port_text)
        except ValueError:
            continue
        if 1 <= port <= 65535:
            ports.add(port)
    return sorted(ports)


def collect_network_inventory() -> dict[str, object]:
    return {
        "source": "netstat",
        "tcp_listen": _parse_netstat("tcp"),
        "udp_listen": _parse_netstat("udp"),
    }


__all__ = ["collect_network_inventory"]
