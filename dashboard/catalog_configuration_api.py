"""RBAC layer for catalog configuration management."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from catalog_configuration import (
    CatalogConfigurationService,
)


def _role(user: dict[str, Any] | None) -> str:
    if not user:
        return ""

    return str(user.get("role", "")).strip().lower()


def _require_view(user):
    if _role(user) not in {
        "admin",
        "controller",
        "customer",
        "client",
        "operator",
    }:
        raise PermissionError(
            "catalog configuration viewing is not permitted"
        )


def _require_edit(user):
    if _role(user) != "admin":
        raise PermissionError(
            "catalog configuration editing requires admin"
        )


def list_catalog_files_for_user(
    user,
    root: Path,
):
    _require_view(user)

    service = CatalogConfigurationService(root)

    return {
        "files": service.list_files(),
        "can_edit": _role(user) == "admin",
    }


def read_catalog_file_for_user(
    user,
    root: Path,
    relative_path: str,
):
    _require_view(user)

    service = CatalogConfigurationService(root)
    result = service.read(relative_path)
    result["can_edit"] = _role(user) == "admin"

    return result


def write_catalog_file_for_user(
    user,
    root: Path,
    payload,
):
    _require_edit(user)

    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    relative_path = str(
        payload.get("path", "")
    ).strip()

    content = payload.get("content")

    if not isinstance(content, str):
        raise ValueError("content must be a string")

    service = CatalogConfigurationService(root)

    result = service.write(
        relative_path,
        content,
    )

    result["can_edit"] = True

    return result
