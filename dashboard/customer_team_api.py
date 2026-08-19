#!/usr/bin/env python3
"""Dedicated customer team and per-instance permission API surface."""
from __future__ import annotations

import re
from typing import Any

from customer_account_api import member_capabilities, require_customer, require_member_management
from customer_team_repository import CustomerTeamRepository
from users import hash_password

CUSTOMER_TEAM_PATHS = {
    "/api/customer/team",
    "/api/customer/team/members/create",
    "/api/customer/team/members/role",
    "/api/customer/team/members/remove",
    "/api/customer/team/access",
}
_USERNAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}")


def _actor(repository: CustomerTeamRepository, user: dict[str, Any] | None) -> tuple[str, str, str]:
    username, customer_id = require_customer(user)
    account_role = repository.account_role(customer_id, username)
    if account_role is None:
        raise PermissionError("customer account membership is required")
    return username, customer_id, account_role


def _snapshot(repository: CustomerTeamRepository, customer_id: str, actor_role: str) -> dict[str, Any]:
    return {
        "members": repository.list_members(customer_id),
        "instances": repository.list_instances(customer_id),
        "capabilities": member_capabilities(actor_role),
        "rbac": {
            "account_roles": ["owner", "manager", "member"],
            "delegable_account_roles": ["manager", "member"],
            "instance_profiles": ["viewer", "operator", "manager"],
            "account_role_is_not_instance_profile": True,
            "owner_manages_team": True,
        },
    }


def _target(body: dict[str, Any]) -> str:
    username = str(body.get("username", "")).strip().lower()
    if not _USERNAME_RE.fullmatch(username):
        raise ValueError("invalid username")
    return username


def dispatch_customer_team(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None,
    user: dict[str, Any] | None,
    backend,
) -> tuple[int, dict[str, Any]] | None:
    if path not in CUSTOMER_TEAM_PATHS:
        return None
    repository = CustomerTeamRepository(backend)
    body = payload or {}
    try:
        _username, customer_id, actor_role = _actor(repository, user)
        if path == "/api/customer/team":
            if method != "GET":
                return 405, {"error": "method not allowed"}
            return 200, _snapshot(repository, customer_id, actor_role)

        if method != "POST":
            return 405, {"error": "method not allowed"}
        require_member_management(actor_role)
        target = _target(body)

        if path == "/api/customer/team/members/create":
            password = str(body.get("password", ""))
            if len(password) < 8:
                raise ValueError("password must have at least 8 characters")
            repository.create_member(
                customer_id,
                target,
                hash_password(password),
                str(body.get("account_role", "member")).strip().lower(),
            )
        elif path == "/api/customer/team/members/role":
            repository.set_account_role(
                customer_id,
                target,
                str(body.get("account_role", "member")).strip().lower(),
            )
        elif path == "/api/customer/team/members/remove":
            repository.remove_member(customer_id, target)
        elif path == "/api/customer/team/access":
            instance_id = str(body.get("instance_id", "")).strip()
            if not instance_id:
                raise ValueError("instance_id is required")
            profile = str(body.get("permission_profile", "")).strip().lower() or None
            repository.set_instance_access(customer_id, target, instance_id, profile)

        return 200, _snapshot(repository, customer_id, actor_role)
    except PermissionError as exc:
        return 403, {"error": str(exc)}
    except (ValueError, LookupError) as exc:
        return 400, {"error": str(exc)}
    except Exception:
        return 500, {"error": "customer team operation failed"}
