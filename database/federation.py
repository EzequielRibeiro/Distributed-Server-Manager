#!/usr/bin/env python3
"""Multi-datacenter federation primitives for Capivara DSM.

The federation layer exchanges bounded inventory snapshots between Controllers.
It deliberately does not replicate operational Agent databases and does not
execute remote shell commands. Local datacenters remain authoritative for
local Agents and instances.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

FEDERATION_SCHEMA_VERSION = 1
CONTROLLER_ROLES = {"global", "datacenter"}
CONTROLLER_STATES = {"unknown", "online", "degraded", "offline", "disabled"}
ROUTE_SCOPES = {"region", "datacenter", "customer", "game", "global"}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def snapshot_checksum(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FederationController:
    controller_id: str
    endpoint: str
    region_id: Optional[str] = None
    datacenter_id: Optional[str] = None
    role: str = "datacenter"
    status: str = "unknown"
    priority: int = 100

    def validate(self) -> None:
        if not self.controller_id.strip():
            raise ValueError("controller_id is required")
        if not self.endpoint.startswith("https://"):
            raise ValueError("federation endpoint must use HTTPS")
        if self.role not in CONTROLLER_ROLES:
            raise ValueError("unsupported federation controller role")
        if self.status not in CONTROLLER_STATES:
            raise ValueError("unsupported federation controller status")
        if self.role == "datacenter" and not self.datacenter_id:
            raise ValueError("datacenter controller requires datacenter_id")


@dataclass(frozen=True)
class FederationRoute:
    scope_type: str
    scope_id: str
    controller_id: str
    priority: int = 100
    enabled: bool = True

    def validate(self) -> None:
        if self.scope_type not in ROUTE_SCOPES:
            raise ValueError("unsupported federation route scope")
        if not self.scope_id or not self.controller_id:
            raise ValueError("route scope_id and controller_id are required")


def build_inventory_snapshot(
    *,
    controller_id: str,
    sequence: int,
    regions: Iterable[Mapping[str, Any]] = (),
    datacenters: Iterable[Mapping[str, Any]] = (),
    agents: Iterable[Mapping[str, Any]] = (),
    instances: Iterable[Mapping[str, Any]] = (),
    capacity: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a bounded, non-secret federation inventory projection."""
    if not controller_id:
        raise ValueError("controller_id is required")
    if sequence < 0:
        raise ValueError("sequence must be non-negative")

    def clean(rows: Iterable[Mapping[str, Any]], allowed: set[str]) -> List[Dict[str, Any]]:
        return [{key: row.get(key) for key in sorted(allowed) if key in row} for row in rows]

    payload: Dict[str, Any] = {
        "schema_version": FEDERATION_SCHEMA_VERSION,
        "controller_id": controller_id,
        "sequence": sequence,
        "generated_at": _utcnow(),
        "regions": clean(regions, {"region_id", "name", "status"}),
        "datacenters": clean(datacenters, {"datacenter_id", "region_id", "name", "status"}),
        "agents": clean(agents, {"agent_id", "datacenter_id", "status", "health", "capabilities"}),
        "instances": clean(instances, {"instance_id", "agent_id", "game_id", "customer_id", "desired_state", "observed_state"}),
        "capacity": dict(capacity or {}),
    }
    return {"snapshot_id": str(uuid.uuid4()), "checksum": snapshot_checksum(payload), "payload": payload}


def validate_inventory_snapshot(snapshot: Mapping[str, Any], expected_controller_id: Optional[str] = None) -> Dict[str, Any]:
    payload = snapshot.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("federation snapshot payload is required")
    if payload.get("schema_version") != FEDERATION_SCHEMA_VERSION:
        raise ValueError("unsupported federation snapshot schema")
    if expected_controller_id and payload.get("controller_id") != expected_controller_id:
        raise ValueError("federation controller identity mismatch")
    checksum = str(snapshot.get("checksum") or "")
    if not checksum or checksum != snapshot_checksum(payload):
        raise ValueError("federation snapshot checksum mismatch")
    if not isinstance(payload.get("sequence"), int) or payload["sequence"] < 0:
        raise ValueError("invalid federation snapshot sequence")
    return payload


def select_controller(
    controllers: Iterable[FederationController],
    routes: Iterable[FederationRoute],
    *,
    region_id: Optional[str] = None,
    datacenter_id: Optional[str] = None,
) -> Optional[FederationController]:
    """Select an online/degraded controller using explicit routes first."""
    available = {c.controller_id: c for c in controllers if c.status in {"online", "degraded"}}
    candidates: List[tuple[int, FederationController]] = []
    for route in routes:
        route.validate()
        if not route.enabled or route.controller_id not in available:
            continue
        matches = (
            (route.scope_type == "datacenter" and datacenter_id and route.scope_id == datacenter_id)
            or (route.scope_type == "region" and region_id and route.scope_id == region_id)
            or route.scope_type == "global"
        )
        if matches:
            candidates.append((route.priority, available[route.controller_id]))
    if candidates:
        return sorted(candidates, key=lambda item: (item[0], item[1].priority, item[1].controller_id))[0][1]
    local = [c for c in available.values() if (not datacenter_id or c.datacenter_id == datacenter_id) and (not region_id or c.region_id == region_id)]
    return sorted(local, key=lambda c: (c.priority, c.controller_id))[0] if local else None
