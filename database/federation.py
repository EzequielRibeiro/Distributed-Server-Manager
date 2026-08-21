#!/usr/bin/env python3
"""Multi-datacenter federation contracts for Capivara DSM.

E1 federates *control-plane metadata*, not operational Agent databases.  Local
Controllers stay authoritative for their Agents and instances even when the WAN
link to a global Controller is unavailable.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

FEDERATION_SCHEMA_VERSION = 1
CONTROLLER_ROLES = {"global", "regional", "datacenter"}
CONTROLLER_STATES = {"unknown", "pending", "online", "degraded", "offline", "disabled"}
ROUTE_SCOPES = {"region", "datacenter", "customer", "game", "global"}
ROUTING_MODES = {"local_first", "region_first", "global"}
HANDOFF_STATES = {"pending", "accepted", "rejected", "completed", "failed"}
MAX_SNAPSHOT_ROWS = 5000
MAX_EVENT_BATCH = 500
MAX_CLOCK_SKEW_SECONDS = 300
_TOKEN_PREFIX = "capfed_"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,190}$")
_FORBIDDEN_KEYS = {
    "authorization", "token", "api_token", "enrollment_token", "password", "passwd",
    "secret", "secret_hash", "credential", "credentials", "rcon_password", "shell", "script",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def snapshot_checksum(payload: Mapping[str, Any]) -> str:
    return _sha256(_canonical(payload))


def issue_federation_secret(controller_id: str) -> tuple[str, str, str]:
    """Issue a one-time presented credential while returning only its verifier."""
    controller_id = str(controller_id or "").strip()
    if not _SAFE_ID.fullmatch(controller_id):
        raise ValueError("invalid federation controller_id")
    token_id = uuid.uuid4().hex[:16]
    secret = secrets.token_urlsafe(32)
    prefix = f"{_TOKEN_PREFIX}{token_id}"
    presented = f"{prefix}_{secret}"
    return prefix, presented, _sha256(secret)


def split_federation_secret(value: str) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text.startswith(_TOKEN_PREFIX) or "_" not in text[len(_TOKEN_PREFIX):]:
        raise ValueError("invalid federation credential")
    prefix, secret = text.rsplit("_", 1)
    if not prefix or not secret:
        raise ValueError("invalid federation credential")
    return prefix, secret


def verify_federation_secret(secret: str, digest: str) -> bool:
    return hmac.compare_digest(_sha256(str(secret)), str(digest or ""))


def validate_request_freshness(timestamp: str, *, now: datetime | None = None, max_skew_seconds: int = MAX_CLOCK_SKEW_SECONDS) -> None:
    """Reject stale/future federation requests before a nonce is claimed."""
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except Exception as exc:
        raise ValueError("invalid federation request timestamp") from exc
    current = now or datetime.now(timezone.utc)
    if abs((current - parsed.astimezone(timezone.utc)).total_seconds()) > max(30, int(max_skew_seconds)):
        raise ValueError("stale federation request")


def validate_nonce(value: str) -> str:
    nonce = str(value or "").strip()
    if not (16 <= len(nonce) <= 191) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", nonce):
        raise ValueError("invalid federation request nonce")
    return nonce


def _reject_secret_keys(value: Any, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _FORBIDDEN_KEYS or normalized.endswith("_password") or normalized.endswith("_secret"):
                raise ValueError(f"secret-bearing field is forbidden in federation metadata: {path}.{key}")
            _reject_secret_keys(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_secret_keys(nested, f"{path}[{index}]")


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
        if not _SAFE_ID.fullmatch(str(self.controller_id or "")):
            raise ValueError("invalid controller_id")
        endpoint = str(self.endpoint or "").strip().rstrip("/")
        if not endpoint.startswith("https://"):
            raise ValueError("federation endpoint must use HTTPS")
        if self.role not in CONTROLLER_ROLES:
            raise ValueError("unsupported federation controller role")
        if self.status not in CONTROLLER_STATES:
            raise ValueError("unsupported federation controller status")
        if not 0 <= int(self.priority) <= 1_000_000:
            raise ValueError("invalid federation controller priority")
        if self.role == "datacenter" and not self.datacenter_id:
            raise ValueError("datacenter controller requires datacenter_id")
        if self.role == "regional" and not self.region_id:
            raise ValueError("regional controller requires region_id")


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
        if not str(self.scope_id or "").strip() or not str(self.controller_id or "").strip():
            raise ValueError("route scope_id and controller_id are required")
        if not 0 <= int(self.priority) <= 1_000_000:
            raise ValueError("invalid federation route priority")


@dataclass(frozen=True)
class FederationPlacementRequest:
    request_id: str
    instance_id: str
    game_id: str
    customer_id: Optional[str] = None
    region_id: Optional[str] = None
    datacenter_id: Optional[str] = None
    mode: str = "local_first"
    cross_region_fallback: bool = False

    def validate(self) -> None:
        for field, value in (("request_id", self.request_id), ("instance_id", self.instance_id), ("game_id", self.game_id)):
            if not _SAFE_ID.fullmatch(str(value or "")):
                raise ValueError(f"invalid federation placement {field}")
        if self.mode not in ROUTING_MODES:
            raise ValueError("unsupported federation routing mode")


def _bounded_clean(rows: Iterable[Mapping[str, Any]], allowed: set[str]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for index, row in enumerate(rows):
        if index >= MAX_SNAPSHOT_ROWS:
            raise ValueError("federation inventory exceeds bounded row limit")
        if not isinstance(row, Mapping):
            raise ValueError("federation inventory row must be an object")
        item = {key: row.get(key) for key in sorted(allowed) if key in row}
        _reject_secret_keys(item)
        result.append(item)
    return result


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
    if not _SAFE_ID.fullmatch(str(controller_id or "")):
        raise ValueError("invalid controller_id")
    if not isinstance(sequence, int) or sequence < 0:
        raise ValueError("sequence must be non-negative")
    safe_capacity = dict(capacity or {})
    _reject_secret_keys(safe_capacity, "capacity")
    payload: Dict[str, Any] = {
        "schema_version": FEDERATION_SCHEMA_VERSION,
        "controller_id": controller_id,
        "sequence": sequence,
        "generated_at": utc_now(),
        "regions": _bounded_clean(regions, {"region_id", "name", "status"}),
        "datacenters": _bounded_clean(datacenters, {"datacenter_id", "region_id", "name", "status"}),
        "agents": _bounded_clean(agents, {"agent_id", "datacenter_id", "status", "health", "capabilities"}),
        "instances": _bounded_clean(instances, {"instance_id", "agent_id", "game_id", "customer_id", "desired_state", "observed_state"}),
        "capacity": safe_capacity,
    }
    return {"snapshot_id": str(uuid.uuid4()), "checksum": snapshot_checksum(payload), "payload": payload}


def validate_inventory_snapshot(snapshot: Mapping[str, Any], expected_controller_id: Optional[str] = None) -> Dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        raise ValueError("federation snapshot must be an object")
    try:
        uuid.UUID(str(snapshot.get("snapshot_id")))
    except Exception as exc:
        raise ValueError("invalid federation snapshot_id") from exc
    payload = snapshot.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("federation snapshot payload is required")
    _reject_secret_keys(payload)
    if payload.get("schema_version") != FEDERATION_SCHEMA_VERSION:
        raise ValueError("unsupported federation snapshot schema")
    if expected_controller_id and payload.get("controller_id") != expected_controller_id:
        raise ValueError("federation controller identity mismatch")
    checksum = str(snapshot.get("checksum") or "")
    if not checksum or checksum != snapshot_checksum(payload):
        raise ValueError("federation snapshot checksum mismatch")
    if not isinstance(payload.get("sequence"), int) or payload["sequence"] < 0:
        raise ValueError("invalid federation snapshot sequence")
    try:
        datetime.fromisoformat(str(payload.get("generated_at")).replace("Z", "+00:00"))
    except Exception as exc:
        raise ValueError("invalid federation snapshot generated_at") from exc
    for key in ("regions", "datacenters", "agents", "instances"):
        rows = payload.get(key)
        if not isinstance(rows, list) or len(rows) > MAX_SNAPSHOT_ROWS:
            raise ValueError(f"invalid or unbounded federation {key}")
    return payload


def select_controller(
    controllers: Iterable[FederationController],
    routes: Iterable[FederationRoute],
    *,
    region_id: Optional[str] = None,
    datacenter_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    game_id: Optional[str] = None,
    mode: str = "local_first",
    cross_region_fallback: bool = False,
) -> Optional[FederationController]:
    """Select a healthy Controller deterministically using E1 routing policy."""
    if mode not in ROUTING_MODES:
        raise ValueError("unsupported federation routing mode")
    validated: list[FederationController] = []
    for controller in controllers:
        controller.validate()
        if controller.status in {"online", "degraded"}:
            validated.append(controller)
    available = {c.controller_id: c for c in validated}
    route_matches: list[tuple[int, int, FederationController]] = []
    specificity = {"customer": 0, "game": 1, "datacenter": 2, "region": 3, "global": 4}
    for route in routes:
        route.validate()
        if not route.enabled or route.controller_id not in available:
            continue
        matches = (
            (route.scope_type == "customer" and customer_id and route.scope_id == customer_id)
            or (route.scope_type == "game" and game_id and route.scope_id == game_id)
            or (route.scope_type == "datacenter" and datacenter_id and route.scope_id == datacenter_id)
            or (route.scope_type == "region" and region_id and route.scope_id == region_id)
            or (route.scope_type == "global" and route.scope_id in {"*", "global"})
        )
        if matches:
            route_matches.append((specificity[route.scope_type], route.priority, available[route.controller_id]))
    if route_matches:
        route_matches.sort(key=lambda item: (item[0], item[1], item[2].priority, item[2].controller_id))
        selected = route_matches[0][2]
        if not cross_region_fallback and region_id and selected.region_id not in {None, region_id}:
            return None
        return selected

    def rank(c: FederationController) -> tuple[int, int, str]:
        same_dc = bool(datacenter_id and c.datacenter_id == datacenter_id)
        same_region = bool(region_id and c.region_id == region_id)
        if mode == "global": tier = 0
        elif mode == "region_first": tier = 0 if same_region else 1
        else: tier = 0 if same_dc else (1 if same_region else 2)
        return tier, c.priority, c.controller_id

    candidates = sorted(available.values(), key=rank)
    for controller in candidates:
        if region_id and controller.region_id not in {None, region_id} and not cross_region_fallback:
            continue
        if mode == "local_first" and datacenter_id and controller.datacenter_id != datacenter_id:
            if controller.region_id != region_id and not cross_region_fallback:
                continue
        return controller
    return None


def aggregate_inventory(snapshots: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Create a global read model without merging local authority/state stores."""
    result: Dict[str, Any] = {"controllers": [], "regions": {}, "datacenters": {}, "agents": {}, "instances": {}, "capacity": {}}
    for raw in snapshots:
        payload = validate_inventory_snapshot(raw)
        cid = str(payload["controller_id"])
        result["controllers"].append({"controller_id": cid, "sequence": payload["sequence"], "generated_at": payload["generated_at"]})
        for key, identity in (("regions", "region_id"), ("datacenters", "datacenter_id"), ("agents", "agent_id"), ("instances", "instance_id")):
            for row in payload[key]:
                rid = str(row.get(identity) or "")
                if rid:
                    result[key][f"{cid}:{rid}"] = dict(row, federation_controller_id=cid)
        for key, value in (payload.get("capacity") or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result["capacity"][key] = float(result["capacity"].get(key, 0)) + float(value)
    result["generated_at"] = utc_now()
    return result


def build_handoff(request: FederationPlacementRequest, target: FederationController) -> Dict[str, Any]:
    request.validate(); target.validate()
    if target.status not in {"online", "degraded"}:
        raise ValueError("target federation controller is unavailable")
    payload = {
        "schema_version": FEDERATION_SCHEMA_VERSION,
        "handoff_id": str(uuid.uuid4()),
        "request_id": request.request_id,
        "instance_id": request.instance_id,
        "game_id": request.game_id,
        "customer_id": request.customer_id,
        "requested_region_id": request.region_id,
        "requested_datacenter_id": request.datacenter_id,
        "routing_mode": request.mode,
        "target_controller_id": target.controller_id,
        "created_at": utc_now(),
    }
    _reject_secret_keys(payload)
    payload["checksum"] = snapshot_checksum(payload)
    return payload


def build_event_batch(controller_id: str, sequence: int, events: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    if not _SAFE_ID.fullmatch(str(controller_id or "")) or not isinstance(sequence, int) or sequence < 0:
        raise ValueError("invalid federation event batch identity")
    if len(events) > MAX_EVENT_BATCH:
        raise ValueError("federation event batch exceeds limit")
    safe_events = [dict(event) for event in events]
    _reject_secret_keys(safe_events, "events")
    payload = {"schema_version": FEDERATION_SCHEMA_VERSION, "controller_id": controller_id, "sequence": sequence, "generated_at": utc_now(), "events": safe_events}
    return {"batch_id": str(uuid.uuid4()), "checksum": snapshot_checksum(payload), "payload": payload}


def validate_event_batch(batch: Mapping[str, Any], expected_controller_id: Optional[str] = None) -> Dict[str, Any]:
    payload = batch.get("payload") if isinstance(batch, Mapping) else None
    if not isinstance(payload, dict):
        raise ValueError("federation event batch payload is required")
    _reject_secret_keys(payload)
    if payload.get("schema_version") != FEDERATION_SCHEMA_VERSION:
        raise ValueError("unsupported federation event schema")
    if expected_controller_id and payload.get("controller_id") != expected_controller_id:
        raise ValueError("federation event controller identity mismatch")
    if not isinstance(payload.get("sequence"), int) or payload["sequence"] < 0:
        raise ValueError("invalid federation event sequence")
    events = payload.get("events")
    if not isinstance(events, list) or len(events) > MAX_EVENT_BATCH:
        raise ValueError("invalid federation event batch")
    if str(batch.get("checksum") or "") != snapshot_checksum(payload):
        raise ValueError("federation event batch checksum mismatch")
    return payload


__all__ = [
    "CONTROLLER_ROLES", "CONTROLLER_STATES", "FEDERATION_SCHEMA_VERSION", "HANDOFF_STATES",
    "MAX_CLOCK_SKEW_SECONDS", "MAX_EVENT_BATCH", "MAX_SNAPSHOT_ROWS", "ROUTE_SCOPES", "ROUTING_MODES",
    "FederationController", "FederationPlacementRequest", "FederationRoute", "aggregate_inventory",
    "build_event_batch", "build_handoff", "build_inventory_snapshot", "issue_federation_secret",
    "select_controller", "snapshot_checksum", "split_federation_secret", "utc_now", "validate_event_batch",
    "validate_inventory_snapshot", "validate_nonce", "validate_request_freshness", "verify_federation_secret",
]
