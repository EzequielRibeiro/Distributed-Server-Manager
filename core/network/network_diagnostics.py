"""Network diagnostics for instance and Agent reservations."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def diagnose_port_states(
    states: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    states = [dict(item) for item in states]

    reserved_only = [
        item
        for item in states
        if item.get("state") == "reserved"
    ]

    listening = [
        item
        for item in states
        if item.get("state") == "listening"
    ]

    findings = []

    for item in reserved_only:
        findings.append(
            {
                "severity": "warning",
                "code": "port_reserved_not_listening",
                "name": item.get("name"),
                "protocol": item.get("protocol"),
                "port": item.get("port"),
                "message": (
                    "A porta estÃ¡ reservada pelo Capivara, "
                    "mas nenhum socket correspondente foi detectado."
                ),
            }
        )

    return {
        "healthy": not findings,
        "total": len(states),
        "listening": len(listening),
        "reserved_not_listening": len(reserved_only),
        "findings": findings,
    }
