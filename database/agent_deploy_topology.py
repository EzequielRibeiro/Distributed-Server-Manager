#!/usr/bin/env python3
"""Topology validation for remote Agent deployment."""

from __future__ import annotations

from alert_repository import AlertSession, dialect_for_backend
from agent_ssh_deploy import AgentDeployError


def validate_deploy_location(
    backend,
    *,
    region_id: str | None,
    datacenter_id: str | None,
) -> tuple[str | None, str | None]:
    """Validate an optional Region/Datacenter pair before remote mutation.

    Location is either omitted completely or provided as an active, matching pair.
    This prevents a successful remote Agent installation from being followed by a
    failed topology bind because of stale or inconsistent administrative IDs.
    """

    region = str(region_id or "").strip() or None
    datacenter = str(datacenter_id or "").strip() or None

    if bool(region) != bool(datacenter):
        raise AgentDeployError("--region-id and --datacenter-id must be provided together")
    if region is None:
        return None, None

    dialect = dialect_for_backend(backend)
    ph = dialect.placeholder
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            region_row = session.execute(
                f"SELECT id,status FROM regions WHERE id={ph}",
                (region,),
            ).fetchone()
            if region_row is None:
                raise AgentDeployError(f"Region not found: {region}")
            if str(region_row["status"]).strip().lower() != "active":
                raise AgentDeployError(f"Region is not active: {region}")

            datacenter_row = session.execute(
                f"SELECT id,region_id,status FROM datacenters WHERE id={ph}",
                (datacenter,),
            ).fetchone()
            if datacenter_row is None:
                raise AgentDeployError(f"Datacenter not found: {datacenter}")
            if str(datacenter_row["status"]).strip().lower() != "active":
                raise AgentDeployError(f"Datacenter is not active: {datacenter}")
            if str(datacenter_row["region_id"]) != region:
                raise AgentDeployError(
                    f"Datacenter {datacenter} does not belong to Region {region}"
                )
        finally:
            session.close()

    return region, datacenter
