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
_SCOPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


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


def normalize_public_ipv6(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        ip = ipaddress.ip_address(text)
    except ValueError as exc:
        raise ValueError("public_ipv6 must be a valid IPv6 address") from exc
    if ip.version != 6:
        raise ValueError("public_ipv6 must be IPv6")
    return str(ip)


def normalize_nat_scope(value: Any) -> str | None:
    scope = str(value or "").strip().lower()
    if not scope:
        return None
    if not _SCOPE_RE.fullmatch(scope):
        raise ValueError("nat_scope must use only letters, numbers, dot, underscore, colon, or dash")
    return scope


def _port(value: Any, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer port") from exc
    if not 1 <= number <= 65535:
        raise ValueError(f"{field} must be between 1 and 65535")
    return number


def normalize_port_mappings(value: Any) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("port_mappings must be a list")
    result: list[dict[str, Any]] = []
    seen_local: set[tuple[str, int]] = set()
    seen_public: set[tuple[str, int]] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each port mapping must be an object")
        protocol = str(item.get("protocol") or "udp").strip().lower()
        if protocol not in {"tcp", "udp"}:
            raise ValueError("port mapping protocol must be tcp or udp")
        bind_port = _port(item.get("bind_port"), "bind_port")
        public_port = _port(item.get("public_port"), "public_port")
        local_key = (protocol, bind_port)
        public_key = (protocol, public_port)
        if local_key in seen_local:
            raise ValueError("duplicate local port mapping")
        if public_key in seen_public:
            raise ValueError("duplicate public port mapping")
        seen_local.add(local_key)
        seen_public.add(public_key)
        result.append({"protocol": protocol, "bind_port": bind_port, "public_port": public_port})
    return result


def normalize_public_network(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    return {
        "public_hostname": normalize_public_hostname(data.get("public_hostname")),
        "public_ipv4": normalize_public_ipv4(data.get("public_ipv4")),
        "public_ipv6": normalize_public_ipv6(data.get("public_ipv6")),
        "nat_scope": normalize_nat_scope(data.get("nat_scope")),
        "port_mappings": normalize_port_mappings(data.get("port_mappings")),
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


def public_address_key(network: dict[str, Any] | None) -> str | None:
    data = network if isinstance(network, dict) else {}
    if data.get("public_ipv4"):
        return f"ipv4:{normalize_public_ipv4(data.get('public_ipv4'))}"
    if data.get("public_ipv6"):
        return f"ipv6:{normalize_public_ipv6(data.get('public_ipv6'))}"
    if data.get("public_hostname"):
        return f"dns:{normalize_public_hostname(data.get('public_hostname'))}"
    return None


def public_port_keys(network: dict[str, Any] | None) -> set[tuple[str, int]]:
    data = normalize_public_network(network)
    return {(item["protocol"], int(item["public_port"])) for item in data["port_mappings"]}


def mapped_public_port(network: dict[str, Any] | None, bind_port: Any, protocol: Any = "udp") -> int | None:
    try:
        local = _port(bind_port, "bind_port")
    except ValueError:
        return None
    wanted = str(protocol or "udp").strip().lower()
    try:
        mappings = normalize_port_mappings((network or {}).get("port_mappings"))
    except ValueError:
        return None
    for item in mappings:
        if item["protocol"] == wanted and item["bind_port"] == local:
            return int(item["public_port"])
    return None


def player_endpoint(
    network: dict[str, Any] | None,
    port: int | None,
    *,
    protocol: str | None = None,
    public_port: int | None = None,
) -> dict[str, Any] | None:
    if port is None:
        return None
    try:
        bind_port = _port(port, "bind_port")
    except ValueError:
        return None
    data = network if isinstance(network, dict) else {}
    hostname = normalize_public_hostname(data.get("public_hostname")) if data.get("public_hostname") else None
    ipv4 = normalize_public_ipv4(data.get("public_ipv4")) if data.get("public_ipv4") else None
    ipv6 = normalize_public_ipv6(data.get("public_ipv6")) if data.get("public_ipv6") else None
    host = hostname or ipv4 or ipv6
    if not host:
        return None
    if public_port is not None:
        try:
            advertised_port = _port(public_port, "public_port")
        except ValueError:
            return None
    else:
        advertised_port = mapped_public_port(data, bind_port, protocol or "udp") or bind_port
    display_host = f"[{host}]" if not hostname and not ipv4 and ipv6 else host
    source = "dns" if hostname else ("ipv4" if ipv4 else "ipv6")
    return {
        "host": host,
        "port": advertised_port,
        "bind_port": bind_port,
        "public_port": advertised_port,
        "address": f"{display_host}:{advertised_port}",
        "source": source,
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
                row = session.execute(f"SELECT metadata_json FROM agents WHERE id={ph}", (agent_id,)).fetchone()
            finally:
                session.close()
        if row is None:
            raise LookupError("Agent not found")
        metadata = _metadata(row["metadata_json"])
        current = normalize_public_network(metadata.get("public_network") if isinstance(metadata.get("public_network"), dict) else {})
        if resolve_dns:
            current["dns"] = dns_status(current["public_hostname"], current["public_ipv4"])
        return current

    def _assert_public_port_uniqueness(self, session: AlertSession, agent_id: str, network: dict[str, Any]) -> None:
        scope = network.get("nat_scope")
        address = public_address_key(network)
        keys = public_port_keys(network)
        if not scope or not address or not keys:
            return
        ph = self.dialect.placeholder
        rows = session.execute(f"SELECT id,metadata_json FROM agents WHERE id<>{ph}", (agent_id,)).fetchall()
        for row in rows:
            metadata = _metadata(row["metadata_json"])
            raw = metadata.get("public_network")
            if not isinstance(raw, dict):
                continue
            try:
                other = normalize_public_network(raw)
            except ValueError:
                continue
            if other.get("nat_scope") != scope or public_address_key(other) != address:
                continue
            overlap = keys & public_port_keys(other)
            if overlap:
                protocol, port = sorted(overlap)[0]
                raise ValueError(
                    f"public port collision in nat_scope {scope}: {protocol}/{port} already reserved by Agent {row['id']}"
                )

    def set(self, agent_id: str, payload: dict[str, Any] | None, *, actor: str | None = None) -> dict[str, Any]:
        agent_id = str(agent_id or "").strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        normalized = normalize_public_network(payload)
        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(f"SELECT metadata_json FROM agents WHERE id={ph}", (agent_id,)).fetchone()
                if row is None:
                    raise LookupError("Agent not found")
                self._assert_public_port_uniqueness(session, agent_id, normalized)
                metadata = _metadata(row["metadata_json"])
                metadata["public_network"] = normalized
                metadata["last_admin_change"] = {"kind": "public_network", "actor": str(actor or "system")}
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
    "mapped_public_port",
    "normalize_nat_scope",
    "normalize_port_mappings",
    "normalize_public_hostname",
    "normalize_public_ipv4",
    "normalize_public_ipv6",
    "normalize_public_network",
    "player_endpoint",
    "public_address_key",
    "public_port_keys",
]
