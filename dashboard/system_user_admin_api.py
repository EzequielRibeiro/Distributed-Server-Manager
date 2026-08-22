#!/usr/bin/env python3
"""System-user administration API with temporary password enforcement."""
from __future__ import annotations

from customer_audit import audit_customer_event
from system_user_admin_repository import SYSTEM_ROLES, SystemUserAdminRepository

SYSTEM_USER_GET_PATHS = {"/api/system-users", "/api/system/auth/password-state"}
SYSTEM_USER_POST_PATHS = {
    "/api/system-users/save",
    "/api/system-users/reset-password",
    "/api/system/auth/change-password",
}


def _require_system_user(user):
    if not user or user.get("role") not in SYSTEM_ROLES:
        raise PermissionError("system user authentication required")
    return str(user.get("username") or "").strip().lower()


def _require_admin(user):
    username = _require_system_user(user)
    if user.get("role") != "admin":
        raise PermissionError("administrator access required")
    return username


def dispatch_system_user_get(path, query, *, user, backend):
    if path not in SYSTEM_USER_GET_PATHS:
        return None
    repository = SystemUserAdminRepository(backend)
    try:
        actor = _require_system_user(user)
        if path == "/api/system/auth/password-state":
            return 200, {
                "username": actor,
                "must_change_password": repository.password_change_required(actor),
            }
        _require_admin(user)
        return 200, {"users": repository.list_users()}
    except PermissionError as exc:
        return 403, {"error": str(exc)}
    except Exception:
        return 500, {"error": "system user query failed"}


def dispatch_system_user_post(path, payload, *, user, backend):
    if path not in SYSTEM_USER_POST_PATHS:
        return None
    repository = SystemUserAdminRepository(backend)
    body = payload or {}
    try:
        actor = _require_system_user(user)
        if path == "/api/system/auth/change-password":
            new_password = str(body.get("password") or "")
            repository.change_temporary_password(actor, new_password)
            audit_customer_event(
                backend,
                username=actor,
                action="system_user.temporary_password_changed",
                details={"role": user.get("role")},
            )
            return 200, {"changed": True, "must_change_password": False}
        _require_admin(user)
        if path == "/api/system-users/reset-password":
            target = str(body.get("username") or "").strip().lower()
            result = repository.reset_password(target)
            audit_customer_event(
                backend,
                username=actor,
                action="system_user.password_reset",
                details={"target": target},
            )
            return 200, result
        result = repository.save_user(
            actor=actor,
            username=str(body.get("username") or ""),
            role=str(body.get("role") or ""),
            scope_id=str(body.get("scope_id") or "").strip() or None,
            active=bool(body.get("active", True)),
            password=(str(body.get("password")) if body.get("password") else None),
        )
        audit_customer_event(
            backend,
            username=actor,
            action="system_user.saved",
            details={
                "target": result["username"],
                "role": result["role"],
                "active": result["active"],
                "temporary_password": bool(result["must_change_password"]),
            },
        )
        return 200, result
    except PermissionError as exc:
        return 403, {"error": str(exc)}
    except (ValueError, LookupError) as exc:
        return 400, {"error": str(exc)}
    except Exception:
        return 500, {"error": "system user operation failed"}


__all__ = [
    "SYSTEM_USER_GET_PATHS",
    "SYSTEM_USER_POST_PATHS",
    "dispatch_system_user_get",
    "dispatch_system_user_post",
]
