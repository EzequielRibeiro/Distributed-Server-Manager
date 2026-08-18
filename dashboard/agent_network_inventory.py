"""Controller/Admin inventory of Agent network resources."""

from __future__ import annotations

from typing import Any


def build_agent_network_inventory(
    summary: dict[str, Any],
) -> dict[str, Any]:
    ranges = [dict(item) for item in summary.get("ranges", [])]
    reservations = [
        dict(item)
        for item in summary.get("reservations", [])
    ]

    protocol_totals = {
        "tcp": {
            "capacity": 0,
            "reserved": 0,
            "available": 0,
        },
        "udp": {
            "capacity": 0,
            "reserved": 0,
            "available": 0,
        },
    }

    for item in ranges:
        protocol = str(item["protocol"]).lower()

        bucket = protocol_totals.setdefault(
            protocol,
            {
                "capacity": 0,
                "reserved": 0,
                "available": 0,
            },
        )

        bucket["capacity"] += int(item.get("capacity", 0))
        bucket["reserved"] += int(item.get("reserved", 0))
        bucket["available"] += int(item.get("available", 0))

    return {
        "agent": dict(summary["agent"]),
        "ranges": ranges,
        "reservations": reservations,
        "conflicts": [
            dict(item)
            for item in summary.get("conflicts", [])
        ],
        "protocol_totals": protocol_totals,
        "health": {
            "conflict_count": int(
                summary.get("conflict_count", 0)
            ),
            "near_exhaustion": any(
                bool(item.get("near_exhaustion"))
                for item in ranges
            ),
        },
    }
