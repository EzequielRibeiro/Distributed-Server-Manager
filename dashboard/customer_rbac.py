#!/usr/bin/env python3
"""Customer account RBAC policy for Capivara DSM.

Account roles and per-instance profiles are intentionally separate domains.
`owner` controls the customer account/team. `viewer`, `operator` and `manager`
remain instance_access profiles and never imply account ownership.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from customer_account_service import permissions_for
from customer_team_repository import CustomerTeamRepository

INSTANCE_WRITE_PROFILES = {"operator", "manager"}


def account_role_for_user(user: dict[str, Any] | None, backend) -> str | None:
    if not user or user.get("role") != "customer" or not user.get("scope_id"):
        return None
    return CustomerTeamRepository(backend).account_role(str(user["scope_id"]), str(user["username"]))


def may_manage_team(user: dict[str, Any] | None, backend) -> bool:
    return account_role_for_user(user, backend) == "owner"


def may_create_instance(user: dict[str, Any] | None, backend) -> bool:
    role = account_role_for_user(user, backend)
    return bool(role and "instance.create" in permissions_for(role))


def instance_profile(user: dict[str, Any] | None, instance_id: str, backend) -> str | None:
    if not user or user.get("role") != "customer" or not user.get("scope_id"):
        return None
    return CustomerTeamRepository(backend).permission_profile(
        str(user["scope_id"]), str(user["username"]), str(instance_id)
    )


def can_access_instance(user: dict[str, Any] | None, instance_path: str | Path, backend, *, write: bool = False) -> bool:
    profile = instance_profile(user, Path(instance_path).name, backend)
    if not profile:
        return False
    return profile in INSTANCE_WRITE_PROFILES if write else True
