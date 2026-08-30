#!/usr/bin/env python3
"""Collect host network identity and occupied TCP/UDP ports on Windows."""

from __future__ import annotations

import json
import socket
import subprocess
from typing import Any


def _run(command: list[str], timeout: int = 10) -> tuple[str, bool]:
    """Run legacy socket collectors through subprocess.run."""
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return "", False
    return completed.stdout, True


def _parse_netstat(protocol: str) -> tuple[list[int], bool]:
    output, complete = _run(["netstat", "-ano", "-p", protocol])
    if not complete:
        return [], False
    ports: set[int] = set()
    for raw in output.splitlines():
        line = raw.strip()
        if not line.upper().startswith(protocol.upper()):
            continue
        fields = line.split()
        if len(fields) < 2:
            continue
        port_text = fields[1].rsplit(":", 1)[-1].strip("[]")
        try:
            port = int(port_text)
        except ValueError:
            continue
        if 1 <= port <= 65535:
            ports.add(port)
    return sorted(ports), True


def _powershell_inventory() -> tuple[dict[str, Any], bool]:
    """Collect Windows adapter identity without reusing subprocess.run."""
    script = r"""
$ErrorActionPreference = 'Stop'
$adapters = Get-NetIPConfiguration | ForEach-Object {
  $adapter = $_.NetAdapter
  [pscustomobject]@{
    name = $_.InterfaceAlias
    interface_index = $_.InterfaceIndex
    status = if ($adapter) { [string]$adapter.Status } else { $null }
    mac = if ($adapter) { [string]$adapter.MacAddress } else { $null }
    mtu = if ($adapter) { [int]$adapter.MtuSize } else { $null }
    ipv4 = @($_.IPv4Address | ForEach-Object { $_.IPAddress })
    ipv6 = @($_.IPv6Address | ForEach-Object { $_.IPAddress })
    gateway4 = @($_.IPv4DefaultGateway | ForEach-Object { $_.NextHop })
    gateway6 = @($_.IPv6DefaultGateway | ForEach-Object { $_.NextHop })
    dns = @($_.DNSServer.ServerAddresses)
  }
}
$default4 = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric,InterfaceMetric | Select-Object -First 1
$default6 = Get-NetRoute -DestinationPrefix '::/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric,InterfaceMetric | Select-Object -First 1
[pscustomobject]@{
  adapters = @($adapters)
  default4 = if ($default4) { [pscustomobject]@{ interface_index=$default4.InterfaceIndex; gateway=$default4.NextHop } } else { $null }
  default6 = if ($default6) { [pscustomobject]@{ interface_index=$default6.InterfaceIndex; gateway=$default6.NextHop } } else { $null }
} | ConvertTo-Json -Depth 8 -Compress
"""
    process = None
    try:
        process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        output, _ = process.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        if process is not None:
            process.kill()
            process.communicate()
        return {}, False
    except (OSError, subprocess.SubprocessError):
        return {}, False
    if process.returncode != 0:
        return {}, False
    try:
        payload = json.loads(output)
    except (TypeError, ValueError):
        return {}, False
    return payload if isinstance(payload, dict) else {}, True


def _items(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in values if str(item).strip()]


def collect_network_inventory() -> dict[str, object]:
    tcp_ports, tcp_complete = _parse_netstat("tcp")
    udp_ports, udp_complete = _parse_netstat("udp")
    payload, identity_complete = _powershell_inventory()

    raw_adapters = payload.get("adapters", []) if isinstance(payload, dict) else []
    if isinstance(raw_adapters, dict):
        raw_adapters = [raw_adapters]
    default4 = payload.get("default4") if isinstance(payload, dict) else None
    default6 = payload.get("default6") if isinstance(payload, dict) else None
    default4_index = default4.get("interface_index") if isinstance(default4, dict) else None
    default6_index = default6.get("interface_index") if isinstance(default6, dict) else None

    adapters: list[dict[str, Any]] = []
    dns_servers: list[str] = []
    primary_interface = None
    primary_ipv4 = None
    primary_ipv6 = None

    for raw in raw_adapters if isinstance(raw_adapters, list) else []:
        if not isinstance(raw, dict):
            continue
        ipv4 = _items(raw.get("ipv4"))
        ipv6 = [item for item in _items(raw.get("ipv6")) if not item.lower().startswith("fe80:")]
        dns = _items(raw.get("dns"))
        index = raw.get("interface_index")
        item = {
            "name": raw.get("name"),
            "interface_index": index,
            "status": str(raw.get("status") or "").lower() or None,
            "mac": raw.get("mac") or None,
            "mtu": raw.get("mtu"),
            "ipv4": ipv4,
            "ipv6": ipv6,
            "gateway_ipv4": _items(raw.get("gateway4")),
            "gateway_ipv6": _items(raw.get("gateway6")),
            "dns": dns,
        }
        adapters.append(item)
        for server in dns:
            if server not in dns_servers:
                dns_servers.append(server)
        if primary_interface is None and index in {default4_index, default6_index}:
            primary_interface = raw.get("name")
            primary_ipv4 = ipv4[0] if ipv4 else None
            primary_ipv6 = ipv6[0] if ipv6 else None

    if primary_interface is None:
        candidate = next((item for item in adapters if item["ipv4"]), None)
        if candidate:
            primary_interface = candidate.get("name")
            primary_ipv4 = candidate["ipv4"][0]
            primary_ipv6 = candidate["ipv6"][0] if candidate["ipv6"] else None

    hostname = socket.gethostname()
    try:
        fqdn = socket.getfqdn()
    except OSError:
        fqdn = hostname

    return {
        "source": "windows-powershell+netstat",
        "hostname": hostname,
        "fqdn": fqdn,
        "primary_interface": primary_interface,
        "primary_ipv4": primary_ipv4,
        "primary_ipv6": primary_ipv6,
        "gateway_ipv4": default4.get("gateway") if isinstance(default4, dict) else None,
        "gateway_ipv6": default6.get("gateway") if isinstance(default6, dict) else None,
        "dns_servers": dns_servers,
        "interfaces": adapters,
        "tcp_listen": tcp_ports,
        "udp_listen": udp_ports,
        "identity_complete": identity_complete,
        "tcp_complete": tcp_complete,
        "udp_complete": udp_complete,
        "complete": identity_complete and tcp_complete and udp_complete,
    }


__all__ = ["collect_network_inventory"]
