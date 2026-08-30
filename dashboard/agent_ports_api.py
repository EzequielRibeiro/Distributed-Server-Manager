"""RBAC-aware Agent port administration for Dashboard."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from agent_port_availability import effective_port_summary
from agent_port_repository import AgentPortRepository
from agent_runtime_repository import AgentRuntimeRepository, AgentRuntimeNotFound
from alert_repository import AlertSession, dialect_for_backend


def _json_ready(value: Any) -> Any:
    """Return an API-safe copy with temporal values normalized to ISO-8601."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    return value


def _repository(backend):
    repository = AgentPortRepository(backend)
    repository.initialize()
    return repository


def _agent_metadata(backend, agent_id: str) -> dict[str, Any]:
    dialect = dialect_for_backend(backend)
    ph = dialect.placeholder
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            row = session.execute(
                f"SELECT metadata_json FROM agents WHERE id={ph}",
                (agent_id,),
            ).fetchone()
        finally:
            session.close()
    if not row:
        return {}
    raw = row["metadata_json"]
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {}
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _agent_location(backend, agent_id: str) -> dict[str, Any]:
    dialect = dialect_for_backend(backend)
    ph = dialect.placeholder
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            row = session.execute(
                "SELECT al.datacenter_id,al.public_host,al.latitude,al.longitude,"
                "d.name AS datacenter_name,d.city,d.country_code,"
                "r.id AS region_id,r.name AS region_name "
                "FROM agent_locations al "
                "JOIN datacenters d ON d.id=al.datacenter_id "
                "JOIN regions r ON r.id=d.region_id "
                f"WHERE al.agent_id={ph} AND al.status='active'",
                (agent_id,),
            ).fetchone()
        finally:
            session.close()
    return dict(row) if row else {}


def _allowed(user: dict[str, Any] | None, agent: dict[str, Any]) -> bool:
    if not user:
        return False
    role = user.get("role")
    if role == "admin":
        return True
    if role == "controller":
        return bool(user.get("scope_id") and user.get("scope_id") == agent.get("controller_id"))
    return False


def _runtime_network_identity(snapshot: dict[str, Any]) -> dict[str, Any]:
    network = snapshot.get("network") if isinstance(snapshot.get("network"), dict) else {}
    address = snapshot.get("address") or network.get("primary_ipv4") or network.get("primary_ipv6")
    return {"hostname": snapshot.get("hostname"), "address": address, "network": network}


def list_agents_for_user(user, backend):
    if not user:
        raise PermissionError("authentication required")
    repository = _repository(backend)
    if user.get("role") == "admin":
        agents = repository.list_agents()
    elif user.get("role") == "controller" and user.get("scope_id"):
        agents = repository.list_agents(user["scope_id"])
    else:
        raise PermissionError("agent administration is not permitted")
    runtime = AgentRuntimeRepository(backend)
    runtime.refresh_health(controller_id=user.get("scope_id") if user.get("role") == "controller" else None)
    enriched = []
    for agent in agents:
        item = dict(agent)
        try:
            snapshot = runtime.snapshot(str(item["id"]), refresh_health=False)
        except AgentRuntimeNotFound:
            snapshot = {}
        item["health_status"] = snapshot.get("health_status") or "offline"
        item["last_seen"] = snapshot.get("last_seen")
        item["capabilities"] = snapshot.get("capabilities") or {}
        item["os_name"] = snapshot.get("os_name")
        item["architecture"] = snapshot.get("architecture")
        item["capivara_version"] = snapshot.get("capivara_version")
        item.update(_runtime_network_identity(snapshot))
        item.update(_agent_location(backend, str(item["id"])))
        enriched.append(item)
    return _json_ready(enriched)


def agent_ports_for_user(user, backend, agent_id):
    repository = _repository(backend)
    agent = repository.agent(str(agent_id).strip())
    if agent is None:
        raise ValueError("agent not found")
    if not _allowed(user, agent):
        raise PermissionError("agent is outside user scope")

    result = effective_port_summary(backend, agent["id"])
    metadata = _agent_metadata(backend, agent["id"])
    result_agent = result.get("agent") if isinstance(result.get("agent"), dict) else {}
    try:
        runtime = AgentRuntimeRepository(backend).snapshot(str(agent["id"]), refresh_health=False)
    except AgentRuntimeNotFound:
        runtime = {}
    result_agent.update({
        "capabilities": runtime.get("capabilities") or {},
        "os_name": runtime.get("os_name"),
        "architecture": runtime.get("architecture"),
        "capivara_version": runtime.get("capivara_version"),
        "health_status": runtime.get("health_status") or "offline",
        "last_seen": runtime.get("last_seen"),
        **_runtime_network_identity(runtime),
        **_agent_location(backend, str(agent["id"])),
    })
    result_agent["metadata"] = metadata
    result_agent["recent_logs"] = metadata.get("recent_logs", [])
    result_agent["telemetry"] = metadata.get("telemetry", {})
    result["agent"] = result_agent
    result["recent_logs"] = metadata.get("recent_logs", [])
    result["telemetry"] = metadata.get("telemetry", {})
    return _json_ready(result)


def set_agent_ports_for_user(user, backend, payload):
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    repository = _repository(backend)
    agent_id = str(payload.get("agent_id", "")).strip()
    agent = repository.agent(agent_id)
    if agent is None:
        raise ValueError("agent not found")
    if not _allowed(user, agent):
        raise PermissionError("agent is outside user scope")
    protocol = str(payload.get("protocol", "both")).strip().lower()
    if protocol == "both":
        protocols = ("tcp", "udp")
    elif protocol in {"tcp", "udp"}:
        protocols = (protocol,)
    else:
        raise ValueError("invalid protocol")
    try:
        start_port = int(payload.get("start_port"))
        end_port = int(payload.get("end_port"))
    except (TypeError, ValueError) as exc:
        raise ValueError("start_port and end_port must be integers") from exc
    force = bool(payload.get("force", False))
    if force and user.get("role") != "admin":
        raise PermissionError("forced range changes require admin")
    result = repository.set_ranges(
        agent_id,
        protocols=protocols,
        start_port=start_port,
        end_port=end_port,
        force=force,
    )
    result["summary"] = effective_port_summary(backend, agent_id)
    return _json_ready(result)
