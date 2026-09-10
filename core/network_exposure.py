#!/usr/bin/env python3
"""Resolve fail-closed per-port exposure from Catalog runtime contracts."""
from __future__ import annotations

from typing import Any

_ALLOWED_EXPOSURE = {"public", "private", "none"}
_ALLOWED_PROTOCOLS = {"tcp", "udp"}


def desired_port_exposure(runtime: dict[str, Any], ports: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized desired exposure records for one resolved runtime instance.

    Missing Catalog exposure is deliberately normalized to ``none``.  This
    helper never infers public reachability from the fact that a port was
    reserved.
    """
    network = runtime.get("network") if isinstance(runtime.get("network"), dict) else {}
    declared = network.get("ports") if isinstance(network.get("ports"), list) else []
    resolved = ports if isinstance(ports, dict) else {}
    result: list[dict[str, Any]] = []
    for item in declared:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        protocol = str(item.get("protocol") or "").strip().lower()
        exposure = str(item.get("exposure") or "none").strip().lower()
        if not name:
            raise ValueError("network port name is required")
        if protocol not in _ALLOWED_PROTOCOLS:
            raise ValueError(f"unsupported network protocol for {name}: {protocol!r}")
        if exposure not in _ALLOWED_EXPOSURE:
            raise ValueError(f"unsupported network exposure for {name}: {exposure!r}")
        binding = resolved.get(name)
        if not isinstance(binding, dict):
            raise ValueError(f"resolved port is unavailable for {name}")
        try:
            port = int(binding.get("port"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"resolved port is invalid for {name}") from exc
        if not 1 <= port <= 65535:
            raise ValueError(f"resolved port is outside TCP/UDP range for {name}")
        resolved_protocol = str(binding.get("protocol") or protocol).strip().lower()
        if resolved_protocol != protocol:
            raise ValueError(
                f"resolved protocol mismatch for {name}: catalog={protocol} resolved={resolved_protocol}"
            )
        result.append({"name": name, "protocol": protocol, "port": port, "exposure": exposure})
    return result


def public_port_exposure(runtime: dict[str, Any], ports: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only ports explicitly declared public by the Catalog."""
    return [item for item in desired_port_exposure(runtime, ports) if item["exposure"] == "public"]


__all__ = ["desired_port_exposure", "public_port_exposure"]
