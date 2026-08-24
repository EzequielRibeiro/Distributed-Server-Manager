#!/usr/bin/env python3
"""Collect occupied TCP/UDP ports from the Linux host."""

from __future__ import annotations

import subprocess


def _parse_ss(args: list[str]) -> tuple[list[int], bool]:
    try:
        completed = subprocess.run(
            ["ss", "-H", "-l", "-n", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return [], False

    ports: set[int] = set()
    for line in completed.stdout.splitlines():
        fields = line.split()
        # ss -Hln{t,u}: local endpoint is the penultimate field.
        if len(fields) < 2:
            continue
        local = fields[-2]
        port_text = local.rsplit(":", 1)[-1].strip("[]")
        try:
            port = int(port_text)
        except ValueError:
            continue
        if 1 <= port <= 65535:
            ports.add(port)
    return sorted(ports), True


def collect_network_inventory() -> dict[str, object]:
    """Return listening/claimed TCP and UDP sockets observed by ``ss``."""
    tcp_ports, tcp_complete = _parse_ss(["-t"])
    udp_ports, udp_complete = _parse_ss(["-u"])
    return {
        "source": "ss",
        "tcp_listen": tcp_ports,
        "udp_listen": udp_ports,
        "tcp_complete": tcp_complete,
        "udp_complete": udp_complete,
        "complete": tcp_complete and udp_complete,
    }


__all__ = ["collect_network_inventory"]
