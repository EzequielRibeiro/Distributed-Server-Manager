#!/usr/bin/env python3
"""Phase 14 Agent installation planning and progress tracking."""

from __future__ import annotations

from typing import Any

from agent_install_command import linux_agent_install_command
from agent_pairing_repository import AgentPairingRepository
from alert_repository import AlertSession, dialect_for_backend
from infrastructure_repository import InfrastructureRepository


def _role(user: dict[str, Any] | None) -> str:
    if not user:
        raise PermissionError("authentication required")
    return str(user.get("role", "")).strip().lower()


def _controller_scope(user: dict[str, Any], requested: str | None) -> str:
    role = _role(user)
    requested_id = str(requested or "").strip()
    if role == "admin":
        if not requested_id:
            raise ValueError("controller_id is required")
        return requested_id
    if role == "controller":
        scope_id = str(user.get("scope_id", "")).strip()
        if not scope_id:
            raise PermissionError("controller scope is required")
        if requested_id and requested_id != scope_id:
            raise PermissionError("controller is outside user scope")
        return scope_id
    raise PermissionError("Agent installation is not permitted")


def _location(backend, region_id: str, datacenter_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    infrastructure = InfrastructureRepository(backend)
    regions = infrastructure.regions(active_only=True)
    datacenters = infrastructure.datacenters(region_id=region_id, active_only=True)
    region = next((item for item in regions if str(item["id"]) == region_id), None)
    datacenter = next((item for item in datacenters if str(item["id"]) == datacenter_id), None)
    if region is None:
        raise ValueError("region not found or inactive")
    if datacenter is None:
        raise ValueError("datacenter not found in selected region or inactive")
    return region, datacenter


def create_agent_installation_for_user(
    user: dict[str, Any] | None,
    backend,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    controller_id = _controller_scope(user or {}, payload.get("controller_id"))
    platform = str(payload.get("platform", "linux")).strip().lower()
    method = str(payload.get("method", "github")).strip().lower()
    region_id = str(payload.get("region_id", "")).strip()
    datacenter_id = str(payload.get("datacenter_id", "")).strip()
    controller_url = str(payload.get("controller_url", "")).strip().rstrip("/")

    if platform not in {"linux", "windows"}:
        raise ValueError("unsupported Agent platform")
    if platform == "windows":
        raise NotImplementedError("Windows Agent ainda não está disponível")
    if method not in {"github", "local"}:
        raise ValueError("unsupported installation method")
    if not controller_url:
        raise ValueError("controller_url is required")

    region, datacenter = _location(backend, region_id, datacenter_id)
    issued = AgentPairingRepository(backend).issue_token(
        controller_id=controller_id,
        created_by=str((user or {}).get("username", "")).strip() or None,
        ttl_seconds=int(payload.get("ttl_seconds", 900) or 900),
    )

    dialect = dialect_for_backend(backend)
    ph = dialect.placeholder
    with backend.transaction() as connection:
        session = AlertSession(backend, connection)
        try:
            session.execute(
                "UPDATE agent_pairing_tokens SET platform=" + ph + ",install_method=" + ph +
                ",region_id=" + ph + ",datacenter_id=" + ph + " WHERE id=" + ph,
                (platform, method, region_id, datacenter_id, issued.token_id),
            )
        finally:
            session.close()

    if method == "github":
        instruction = linux_agent_install_command(
            controller_url=controller_url,
            pairing_token=issued.token,
        )
    else:
        instruction = (
            "sudo ./install-agent.sh --controller-url " + controller_url +
            " --pairing-token " + issued.token
        )

    return {
        "installation_id": issued.token_id,
        "controller_id": controller_id,
        "platform": platform,
        "method": method,
        "region": {"id": region["id"], "name": region["name"]},
        "datacenter": {"id": datacenter["id"], "name": datacenter["name"]},
        "expires_at": issued.expires_at,
        "instruction": instruction,
        "state": "waiting",
        "state_label": "Aguardando Agent",
    }


def agent_installation_status_for_user(
    user: dict[str, Any] | None,
    backend,
    installation_id: str,
) -> dict[str, Any]:
    installation_id = str(installation_id).strip()
    if not installation_id:
        raise ValueError("installation_id is required")
    dialect = dialect_for_backend(backend)
    ph = dialect.placeholder
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            row = session.execute(
                "SELECT controller_id,platform,install_method,region_id,datacenter_id,agent_id,consumed_at,expires_at "
                "FROM agent_pairing_tokens WHERE id=" + ph,
                (installation_id,),
            ).fetchone()
            if row is None:
                raise LookupError("installation not found")
            _controller_scope(user or {}, str(row["controller_id"]))
            agent = None
            inventory = None
            if row["agent_id"]:
                agent = session.execute(
                    "SELECT id,status FROM agents WHERE id=" + ph,
                    (str(row["agent_id"]),),
                ).fetchone()
                inventory = session.execute(
                    "SELECT health_status,last_seen FROM agent_runtime_inventory WHERE agent_id=" + ph,
                    (str(row["agent_id"]),),
                ).fetchone()
        finally:
            session.close()

    state = "waiting"
    label = "Aguardando Agent"
    if row["consumed_at"]:
        state, label = "pairing", "Pareando"
    if agent is not None and str(agent["status"]).lower() == "active":
        state, label = "validating", "Validando"
    if inventory is not None and str(inventory["health_status"] or "").lower() == "online":
        state, label = "online", "Online"

    return {
        "installation_id": installation_id,
        "agent_id": str(row["agent_id"]) if row["agent_id"] else None,
        "state": state,
        "state_label": label,
        "agent_status": str(agent["status"]) if agent is not None else None,
        "health_status": str(inventory["health_status"]) if inventory is not None else None,
        "last_seen": inventory["last_seen"] if inventory is not None else None,
        "expires_at": row["expires_at"],
    }


def bind_installation_after_enrollment(backend, *, pairing_token: str, agent_id: str) -> None:
    """Bind enrollment to its dashboard installation and apply intended location."""
    from core.agent_identity import secret_digest
    from location_repository import LocationRepository

    dialect = dialect_for_backend(backend)
    ph = dialect.placeholder
    token_hash = secret_digest(pairing_token)
    with backend.transaction() as connection:
        session = AlertSession(backend, connection)
        try:
            row = session.execute(
                "SELECT id,datacenter_id FROM agent_pairing_tokens WHERE token_hash=" + ph,
                (token_hash,),
            ).fetchone()
            if row is None:
                return
            session.execute(
                "UPDATE agent_pairing_tokens SET agent_id=" + ph + " WHERE id=" + ph,
                (agent_id, str(row["id"])),
            )
        finally:
            session.close()

    if row["datacenter_id"]:
        LocationRepository(backend).upsert_agent_location(
            agent_id=agent_id,
            datacenter_id=str(row["datacenter_id"]),
            status="active",
        )
