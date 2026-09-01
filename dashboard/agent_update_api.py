#!/usr/bin/env python3
"""RBAC-aware remote Agent update planning, release selection and rollout status."""

from __future__ import annotations

from typing import Any

from agent_release_service import AgentReleaseError, list_agent_releases
from agent_update_repository import AgentUpdateRepository
from alert_repository import AlertSession, dialect_for_backend


def _role(user: dict[str, Any] | None) -> str:
    if not user:
        raise PermissionError("authentication required")
    return str(user.get("role", "")).strip().lower()


def _scoped_agents(user: dict[str, Any], backend, requested: list[str]) -> list[str]:
    role = _role(user)
    ids = [str(item).strip() for item in requested if str(item).strip()]
    if not ids:
        raise ValueError("agent_ids is required")
    dialect = dialect_for_backend(backend)
    placeholders = dialect.parameters(len(ids))
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            rows = session.execute(
                f"SELECT id,controller_id FROM agents WHERE id IN ({placeholders})",
                tuple(ids),
            ).fetchall()
        finally:
            session.close()
    found = {str(row["id"]): str(row["controller_id"]) for row in rows}
    if set(found) != set(ids):
        raise ValueError("one or more Agents do not exist")
    if role == "admin":
        return ids
    if role == "controller":
        scope = str(user.get("scope_id", "")).strip()
        if not scope or any(controller_id != scope for controller_id in found.values()):
            raise PermissionError("Agent is outside controller scope")
        return ids
    raise PermissionError("Agent update administration is not permitted")


def _agent_platforms(backend, agent_ids: list[str]) -> dict[str, str]:
    """Return the heartbeat-reported platform for every target Agent."""
    dialect = dialect_for_backend(backend)
    placeholders = dialect.parameters(len(agent_ids))
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            rows = session.execute(
                "SELECT agent_id,os_name FROM agent_runtime_inventory "
                f"WHERE agent_id IN ({placeholders})",
                tuple(agent_ids),
            ).fetchall()
        finally:
            session.close()
    platforms = {
        str(row["agent_id"]): str(row["os_name"] or "").strip().lower()
        for row in rows
    }
    missing = [agent_id for agent_id in agent_ids if platforms.get(agent_id) not in {"linux", "windows"}]
    if missing:
        raise ValueError(
            "plataforma do Agent ainda não foi publicada pelo heartbeat: " + ", ".join(missing)
        )
    return platforms


def _published_versions_for_platform(platform: str, channel: str) -> list[dict[str, Any]]:
    channel = str(channel or "stable").strip().lower()
    if channel not in {"stable", "beta"}:
        if channel == "local/manual":
            return []
        raise ValueError("invalid update channel")
    try:
        releases = list_agent_releases(
            platform,
            include_prereleases=(channel == "beta"),
            limit=50,
        )
    except AgentReleaseError as exc:
        raise ValueError(str(exc)) from exc
    result: list[dict[str, Any]] = []
    for release in releases:
        if channel == "stable" and release.get("prerelease"):
            continue
        tag = str(release.get("tag") or "").strip()
        version = tag.lstrip("v")
        if not version:
            continue
        result.append({**release, "version": version})
    return result


def agent_update_versions_for_user(
    user,
    backend,
    agent_id: str,
    channel: str = "stable",
) -> dict[str, Any]:
    agent_id = _scoped_agents(user or {}, backend, [agent_id])[0]
    platform = _agent_platforms(backend, [agent_id])[agent_id]
    normalized_channel = str(channel or "stable").strip().lower()
    releases = _published_versions_for_platform(platform, normalized_channel)
    stable = _published_versions_for_platform(platform, "stable")
    recommended = stable[0]["version"] if stable else None
    return {
        "agent_id": agent_id,
        "platform": platform,
        "channel": normalized_channel,
        "recommended_version": recommended,
        "releases": releases,
    }


def _validate_rollout_release(backend, agent_ids: list[str], desired_version: str, channel: str) -> str:
    channel = str(channel or "stable").strip().lower()
    if channel == "local/manual":
        raise ValueError(
            "o canal local/manual não aceita rollout por versão; forneça o pacote por um fluxo administrativo local"
        )
    if channel not in {"stable", "beta"}:
        raise ValueError("invalid update channel")
    version = str(desired_version or "").strip().lstrip("v")
    if not version:
        raise ValueError("desired_version is required")
    platforms = set(_agent_platforms(backend, agent_ids).values())
    for platform in sorted(platforms):
        allowed = {
            str(release.get("version") or "").strip()
            for release in _published_versions_for_platform(platform, channel)
        }
        if version not in allowed:
            raise ValueError(
                f"versão {version} não é uma release publicada compatível com Agent {platform} no canal {channel}"
            )
    return version


def create_agent_rollout_for_user(user, backend, payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    agent_ids = _scoped_agents(user or {}, backend, list(payload.get("agent_ids") or []))
    channel = str(payload.get("update_channel", "stable")).strip().lower()
    desired_version = _validate_rollout_release(
        backend,
        agent_ids,
        str(payload.get("desired_version", "")),
        channel,
    )
    repository = AgentUpdateRepository(backend)
    repository.initialize()
    return repository.create_rollout(
        agent_ids,
        desired_version=desired_version,
        channel=channel,
        batch_size=int(payload.get("batch_size", 1) or 1),
    )


def set_agent_update_channel_for_user(user, backend, payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    agent_id = _scoped_agents(user or {}, backend, [str(payload.get("agent_id", ""))])[0]
    repository = AgentUpdateRepository(backend)
    repository.initialize()
    return repository.set_channel(agent_id, str(payload.get("update_channel", "")))


def agent_update_status_for_user(user, backend, agent_id: str) -> dict[str, Any]:
    agent_id = _scoped_agents(user or {}, backend, [agent_id])[0]
    repository = AgentUpdateRepository(backend)
    repository.initialize()
    return repository.snapshot(agent_id)


__all__ = [
    "create_agent_rollout_for_user",
    "set_agent_update_channel_for_user",
    "agent_update_status_for_user",
    "agent_update_versions_for_user",
]
