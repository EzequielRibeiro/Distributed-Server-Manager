#!/usr/bin/env python3
"""Collect occupied TCP/UDP ports from the Linux host."""

from __future__ import annotations

import subprocess


def _parse_ss(protocol: str, args: list[str]) -> list[int]:
    try:
        completed = subprocess.run(
            ["ss", "-H", "-l", "-n", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    ports: set[int] = set()
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) < 5:
            continue
        local = fields[4]
        port_text = local.rsplit(":", 1)[-1].strip("[]")
        try:
            port = int(port_text)
        except ValueError:
            continue
        if 1 <= port <= 65535:
            ports.add(port)
    return sorted(ports)


def collect_network_inventory() -> dict[str, object]:
    """Return listening/claimed TCP and UDP sockets observed by ``ss``."""
    return {
        "source": "ss",
        "tcp_listen": _parse_ss("tcp", ["-t"]),
        "udp_listen": _parse_ss("udp", ["-u"]),
    }


__all__ = ["collect_network_inventory"]
