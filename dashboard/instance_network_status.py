"""RBAC-aware network status surface for an instance."""

from __future__ import annotations

from typing import Any, Mapping


CUSTOMER_VISIBLE_NAMES = {
    "game",
    "game_ipv4",
    "game_ipv6",
    "steam_query",
    "query",
    "rcon",
}


DEFAULT_PURPOSES = {
    "game": "Porta principal do jogo",
    "game_aux": "Porta auxiliar do jogo",
    "game_ipv4": "Porta principal IPv4",
    "game_ipv6": "Porta principal IPv6",
    "steam_query": "Steam Query",
    "steam_master": "Steam Master",
    "query": "Consulta de servidor",
    "rcon": "Console remoto RCON",
    "battleye": "BattlEye",
    "von_reserved": "VoN / comunicaÃ§Ã£o de voz",
}


def network_status_for_role(
    states: list[Mapping[str, Any]],
    role: str,
) -> dict[str, Any]:
    role = str(role).strip().lower()

    if role in {"admin", "controller"}:
        visible = [dict(item) for item in states]
    else:
        visible = [
            dict(item)
            for item in states
            if item.get("name") in CUSTOMER_VISIBLE_NAMES
            or bool(item.get("public"))
        ]

    for item in visible:
        item["purpose"] = (
            item.get("purpose")
            or DEFAULT_PURPOSES.get(item.get("name"))
        )

    listening = sum(
        1
        for item in visible
        if item.get("state") == "listening"
    )

    reserved = sum(
        1
        for item in visible
        if item.get("state") == "reserved"
    )

    return {
        "ports": visible,
        "summary": {
            "total": len(visible),
            "listening": listening,
            "reserved": reserved,
        },
    }
