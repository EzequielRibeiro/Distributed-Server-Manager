"""RBAC-aware Agent port administration for Dashboard."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from agent_port_availability import effective_port_summary
from agent_port_repository import AgentPortRepository


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


def _allowed(user: dict[str, Any] | None, agent: dict[str, Any]) -> bool:
    if not user:
        return False
    role = user.get("role")
    if role == "admin":
        return True
    if role == "controller":
        return bool(user.get("scope_id") and user.get("scope_id") == agent.get("controller_id"))
    return False


def list_agents_for_user(user, backend):
    if not user:
        raise PermissionError("authentication required")
    repository = _repository(backend)
    if user.get("role") == "admin":
        return _json_ready(repository.list_agents())
    if user.get("role") == "controller" and user.get("scope_id"):
        return _json_ready(repository.list_agents(user["scope_id"]))
    raise PermissionError("agent administration is not permitted")


def agent_ports_for_user(user, backend, agent_id):
    repository = _repository(backend)
    agent = repository.agent(str(agent_id).strip())
    if agent is None:
        raise ValueError("agent not found")
    if not _allowed(user, agent):
        raise PermissionError("agent is outside user scope")
    return _json_ready(effective_port_summary(backend, agent["id"]))


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
