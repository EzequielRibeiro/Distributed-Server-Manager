#!/usr/bin/env python3
"""Interactive authentication for destructive administrative CLI actions."""

from __future__ import annotations

import getpass

from user_repository import UserRepository
from users import verify_password


def require_admin(backend, username: str) -> dict:
    normalized = str(username or "").strip().lower()
    if not normalized:
        raise PermissionError("admin username is required")

    repository = UserRepository(backend)
    user = repository.get(normalized)
    if user is None:
        raise PermissionError("administrator not found")
    if str(user.get("role") or "").strip().lower() != "admin":
        raise PermissionError("this operation requires an admin user")
    if not bool(user.get("active")):
        raise PermissionError("administrator is disabled")

    password = getpass.getpass(f"Senha do admin {normalized}: ")
    if not verify_password(password, str(user.get("password_hash") or "")):
        raise PermissionError("invalid administrator credentials")
    return user


__all__ = ["require_admin"]
