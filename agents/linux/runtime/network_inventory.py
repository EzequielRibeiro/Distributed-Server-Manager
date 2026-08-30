#!/usr/bin/env python3
"""Collect network identity, interfaces, routes, DNS and occupied ports."""

from __future__ import annotations

import ipaddress
import json
import socket
import subprocess
from pathlib import Path
from typing import Any


def _run(args: list[str], *, timeout: int = 5) -> tuple[str, bool]:
    try:
        completed = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return "", False
    return completed.stdout, True


def _run_json(args: list[str]) -> tuple[list[dict[str, Any]], bool]:
    output, complete = _run(args)
    if not complete:
        return [], False
    try:
        value = json.loads(output or "[]")
    except (TypeError, ValueError):
        return [], False
    if not isinstance(value, list):
        return [], False
    return [item for item in value if isinstance(item, dict)], True


def _parse_ss(args: list[str]) -> tuple[list[int], bool]:
    """Return observed ports and whether the socket query completed reliably."""
    output, complete = _run(["ss", "-H", "-l", "-n", *args])
    if not complete:
        return [], False

    ports: set[int] = set()
    for line in output.splitlines():
        fields = line.split()
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


def _prefix_address(address: str, prefixlen: Any) -> str:
    try:
        prefix = int(prefixlen)
        return str(ipaddress.ip_interface(f"{address}/{prefix}"))
    except (TypeError, ValueError):
        return address


def _interfaces() -> tuple[list[dict[str, Any]], bool]:
    rows, complete = _run_json(["ip", "-j", "address", "show"])
    interfaces: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("ifname") or "").strip()
        if not name:
            continue
        ipv4: list[str] = []
        ipv6: list[str] = []
        for address in row.get("addr_info") or []:
            if not isinstance(address, dict):
                continue
            local = str(address.get("local") or "").strip()
            if not local:
                continue
            rendered = _prefix_address(local, address.get("prefixlen"))
            family = str(address.get("family") or "").lower()
            if family == "inet":
                ipv4.append(rendered)
            elif family == "inet6":
                ipv6.append(rendered)
        interfaces.append(
            {
                "name": name,
                "state": str(row.get("operstate") or "unknown").lower(),
                "mac": str(row.get("address") or "").lower() or None,
                "mtu": row.get("mtu"),
                "flags": [str(item) for item in row.get("flags") or []],
                "ipv4": ipv4,
                "ipv6": ipv6,
                "kind": ((row.get("linkinfo") or {}).get("info_kind") if isinstance(row.get("linkinfo"), dict) else None),
            }
        )
    return interfaces, complete


def _default_routes() -> tuple[dict[str, Any], dict[str, Any], bool]:
    rows, complete = _run_json(["ip", "-j", "route", "show", "default"])
    routes: dict[str, dict[str, Any]] = {}
    for row in rows:
        family = str(row.get("family") or "").lower()
        if family not in {"inet", "inet6"}:
            gateway = str(row.get("gateway") or "")
            family = "inet6" if ":" in gateway else "inet"
        if family in routes:
            continue
        routes[family] = {
            "interface": row.get("dev"),
            "gateway": row.get("gateway"),
            "source": row.get("prefsrc") or row.get("src"),
            "metric": row.get("metric"),
            "protocol": row.get("protocol"),
        }
    return routes.get("inet", {}), routes.get("inet6", {}), complete


def _dns_servers(path: Path = Path("/etc/resolv.conf")) -> tuple[list[str], bool]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return [], False
    servers: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if len(fields) >= 2 and fields[0].lower() == "nameserver":
            value = fields[1]
            try:
                ipaddress.ip_address(value)
            except ValueError:
                continue
            if value not in servers:
                servers.append(value)
    return servers, True


def _first_address(interfaces: list[dict[str, Any]], interface: str | None, family: str) -> str | None:
    candidates = interfaces
    if interface:
        preferred = [item for item in interfaces if item.get("name") == interface]
        if preferred:
            candidates = preferred + [item for item in interfaces if item.get("name") != interface]
    for item in candidates:
        if item.get("name") == "lo":
            continue
        for raw in item.get(family) or []:
            address = str(raw).split("/", 1)[0]
            try:
                parsed = ipaddress.ip_address(address)
            except ValueError:
                continue
            if not parsed.is_loopback and not parsed.is_unspecified:
                return address
    return None


def collect_network_inventory() -> dict[str, object]:
    """Return a best-effort network inventory while preserving legacy socket keys."""
    tcp_ports, tcp_complete = _parse_ss(["-t"])
    udp_ports, udp_complete = _parse_ss(["-u"])
    interfaces, interfaces_complete = _interfaces()
    default_ipv4, default_ipv6, routes_complete = _default_routes()
    dns_servers, dns_complete = _dns_servers()

    primary_interface = default_ipv4.get("interface") or default_ipv6.get("interface")
    primary_ipv4 = default_ipv4.get("source") or _first_address(interfaces, primary_interface, "ipv4")
    primary_ipv6 = default_ipv6.get("source") or _first_address(interfaces, primary_interface, "ipv6")

    return {
        "source": "linux-iproute2",
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "primary_interface": primary_interface,
        "primary_ipv4": primary_ipv4,
        "primary_ipv6": primary_ipv6,
        "default_gateway_ipv4": default_ipv4.get("gateway"),
        "default_gateway_ipv6": default_ipv6.get("gateway"),
        "default_route_ipv4": default_ipv4,
        "default_route_ipv6": default_ipv6,
        "dns_servers": dns_servers,
        "interfaces": interfaces,
        "tcp_listen": tcp_ports,
        "udp_listen": udp_ports,
        "tcp_complete": tcp_complete,
        "udp_complete": udp_complete,
        "interfaces_complete": interfaces_complete,
        "routes_complete": routes_complete,
        "dns_complete": dns_complete,
        "complete": tcp_complete and udp_complete and interfaces_complete and routes_complete and dns_complete,
    }


__all__ = ["collect_network_inventory"]
