#!/usr/bin/env python3
"""Read-only preflight for Agent Port Pools and observed host sockets."""

from __future__ import annotations

from typing import Any

from agent_port_availability import effective_port_summary


def _normalize_protocol(value: str) -> str:
    protocol = str(value or "").strip().lower()
    if protocol not in {"tcp", "udp"}:
        raise ValueError("protocol must be tcp or udp")
    return protocol


def _normalize_width(value: int | str | None) -> int:
    try:
        width = int(value or 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("required_contiguous must be an integer") from exc
    if not 1 <= width <= 65535:
        raise ValueError("required_contiguous must be between 1 and 65535")
    return width


def port_pool_preflight(
    backend,
    agent_id: str,
    *,
    protocol: str | None = None,
    required_contiguous: int | str | None = 1,
) -> dict[str, Any]:
    """Return allocation readiness without mutating reservations or health."""
    width = _normalize_width(required_contiguous)
    summary = effective_port_summary(
        backend,
        str(agent_id).strip(),
        refresh_runtime_health=False,
    )
    requested_protocol = _normalize_protocol(protocol) if protocol else None
    ranges = []
    ready_ranges = []

    for raw in summary.get("ranges", []):
        item = dict(raw)
        item_protocol = str(item.get("protocol") or "").lower()
        if requested_protocol and item_protocol != requested_protocol:
            continue
        contiguous = int(item.get("largest_contiguous_available") or 0)
        item["required_contiguous"] = width
        item["ready"] = contiguous >= width
        ranges.append(item)
        if item["ready"]:
            ready_ranges.append(item)

    network = summary.get("agent", {}).get("network")
    if not isinstance(network, dict):
        network = {}

    reasons: list[str] = []
    if not ranges:
        reasons.append("no_matching_port_pool")
    if ranges and not ready_ranges:
        reasons.append("insufficient_contiguous_capacity")
    if int(summary.get("observed_conflict_count") or 0):
        reasons.append("unmanaged_os_socket_overlap")
    if network and not bool(network.get("complete", True)):
        reasons.append("network_inventory_incomplete")

    return {
        "agent_id": str(agent_id).strip(),
        "protocol": requested_protocol,
        "required_contiguous": width,
        "ready": bool(ready_ranges),
        "ranges": ranges,
        "eligible_range_count": len(ready_ranges),
        "conflict_count": int(summary.get("conflict_count") or 0),
        "observed_conflict_count": int(summary.get("observed_conflict_count") or 0),
        "reasons": reasons,
    }


__all__ = ["port_pool_preflight"]
