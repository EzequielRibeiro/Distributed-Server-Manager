#!/usr/bin/env python3
"""Canonical contracts for E1 Multi-Datacenter Federation."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
FEDERATION_ROLES = {"global", "regional", "datacenter"}
MEMBER_STATES = {"pending", "active", "degraded", "offline", "disabled"}
POLICY_MODES = {"local_first", "region_first", "global"}


class FederationValidationError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_id(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not _ID.fullmatch(text):
        raise FederationValidationError(f"invalid {field}")
    return text


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def deterministic_snapshot_id(controller_id: str, generated_at: str, payload: Any) -> str:
    raw = f"{controller_id}\0{generated_at}\0{canonical_json(payload)}".encode()
    return "fs_" + hashlib.sha256(raw).hexdigest()[:32]


@dataclass(frozen=True)
class FederationMember:
    controller_id: str
    role: str
    region_id: str | None = None
    datacenter_id: str | None = None
    public_endpoint: str | None = None
    status: str = "pending"

    def normalized(self) -> dict[str, Any]:
        controller_id = validate_id(self.controller_id, "controller_id")
        role = str(self.role or "").strip().lower()
        status = str(self.status or "").strip().lower()
        if role not in FEDERATION_ROLES:
            raise FederationValidationError("invalid federation role")
        if status not in MEMBER_STATES:
            raise FederationValidationError("invalid federation member status")
        region_id = validate_id(self.region_id, "region_id") if self.region_id else None
        datacenter_id = validate_id(self.datacenter_id, "datacenter_id") if self.datacenter_id else None
        endpoint = str(self.public_endpoint or "").strip() or None
        if endpoint and not endpoint.startswith("https://"):
            raise FederationValidationError("federation endpoint must use https")
        if role == "datacenter" and not datacenter_id:
            raise FederationValidationError("datacenter member requires datacenter_id")
        return {
            "controller_id": controller_id,
            "role": role,
            "region_id": region_id,
            "datacenter_id": datacenter_id,
            "public_endpoint": endpoint,
            "status": status,
        }


def normalize_capabilities(raw: Iterable[Any] | None) -> list[str]:
    values: list[str] = []
    for item in raw or ():
        value = str(item or "").strip().lower()
        if value and value not in values:
            values.append(value)
    return sorted(values)


def build_inventory_snapshot(
    *, controller_id: str, generated_at: str | None = None,
    agents: list[dict[str, Any]] | None = None,
    instances: list[dict[str, Any]] | None = None,
    capacity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    controller_id = validate_id(controller_id, "controller_id")
    generated_at = generated_at or utc_now()
    payload = {
        "schema_version": 1,
        "controller_id": controller_id,
        "agents": agents or [],
        "instances": instances or [],
        "capacity": capacity or {},
    }
    payload["snapshot_id"] = deterministic_snapshot_id(controller_id, generated_at, payload)
    payload["generated_at"] = generated_at
    return payload


def new_federation_secret() -> str:
    return "capfed_" + secrets.token_urlsafe(32)
