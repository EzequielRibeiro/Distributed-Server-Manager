#!/usr/bin/env python3
"""Public network identity and player-facing endpoint helpers for Agents."""
from __future__ import annotations

import ipaddress
import json
import re
import socket
from typing import Any

from alert_repository import AlertSession, dialect_for_backend

_HOST_RE = re.compile(r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")


def normalize_public_hostname(value: Any) -> str | None:
    host = str(value or "").strip().rstrip(".").lower()
    if not host:
        return None
    if not _HOST_RE.fullmatch(host):
        raise ValueError("public_hostname must be a valid DNS hostname")
    return host


def normalize_public_ipv4(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        ip = ipaddress.ip_address(text)
    except ValueError as exc:
        raise ValueError("public_ipv4 must be a valid IPv4 address") from exc
    if ip.version != 4:
        raise ValueError("public_ipv4 must be IPv4")
    return str(ip)


def normalize_public_network(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    return {
        "public_hostname": normalize_public_hostname(data.get("public_hostname")),
        "public_ipv4": normalize_public_ipv4(data.get("public_ipv4")),
    }


def _metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def dns_status(public_hostname: str | None, public_ipv4: str | None) -> dict[str, Any]:
    if not public_hostname:
        return {"status": "not_configured", "resolved_ipv4": []}
    try:
        infos = socket.getaddrinfo(public_hostname, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
        resolved = sorted({str(item[4][0]) for item in infos if item and item[4]})
    except OSError as exc:
        return {"status": "unresolved", "resolved_ipv4": [], "error": str(exc)[:300]}
    status = "active"
    if public_ipv4 and public_ipv4 not in resolved:
        status = "mismatch"
    return {"status": status, "resolved_ipv4": resolved}


def player_endpoint(network: dict[str, Any] | None, port: int | None) -> dict[str, Any] | None:
    if port is None:
        return None
    try:
        number = int(port)
    except (TypeError, ValueError):
        return None
    if not 1 <= number <= 65535:
        return None
    data = network if isinstance(network, dict) else {}
    hostname = normalize_public_hostname(data.get("public_hostname")) if data.get("public_hostname") else None
    ipv4 = normalize_public_ipv4(data.get("public_ipv4")) if data.get("public_ipv4") else None
    host = hostname or ipv4
    if not host:
        return None
    return {
        "host": host,
        "port": number,
        "address": f"{host}:{number}",
        "source": "dns" if hostname else "ipv4",
    }


class AgentPublicNetworkRepository:
    """Store canonical public network identity inside Agents.metadata_json."""

    def __init__(self, backend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def get(self, agent_id: str, *, resolve_dns: bool = False) -> dict[str, Any]:
        agent_id = str(agent_id or "").strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT metadata_json FROM agents WHERE id={ph}", (agent_id,)
                ).fetchone()
            finally:
                session.close()
        if row is None:
            raise LookupError("Agent not found")
        metadata = _metadata(row["metadata_json"])
        current = normalize_public_network(metadata.get("public_network") if isinstance(metadata.get("public_network"), dict) else {})
        if resolve_dns:
            current["dns"] = dns_status(current["public_hostname"], current["public_ipv4"])
        return current

    def set(self, agent_id: str, payload: dict[str, Any] | None, *, actor: str | None = None) -> dict[str, Any]:
        agent_id = str(agent_id or "").strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        normalized = normalize_public_network(payload)
        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT metadata_json FROM agents WHERE id={ph}", (agent_id,)
                ).fetchone()
                if row is None:
                    raise LookupError("Agent not found")
                metadata = _metadata(row["metadata_json"])
                metadata["public_network"] = normalized
                metadata["last_admin_change"] = {
                    "kind": "public_network",
                    "actor": str(actor or "system"),
                }
                session.execute(
                    f"UPDATE agents SET metadata_json={ph},updated_at=CURRENT_TIMESTAMP WHERE id={ph}",
                    (json.dumps(metadata, ensure_ascii=False, separators=(",", ":")), agent_id),
                )
            finally:
                session.close()
        return self.get(agent_id, resolve_dns=True)


__all__ = [
    "AgentPublicNetworkRepository",
    "dns_status",
    "normalize_public_hostname",
    "normalize_public_ipv4",
    "normalize_public_network",
    "player_endpoint",
]
