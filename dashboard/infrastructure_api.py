#!/usr/bin/env python3
"""RBAC-aware infrastructure topology helpers for Dashboard."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT_DIR / "database"
for path in (ROOT_DIR, DATABASE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from infrastructure_repository import InfrastructureRepository
from infrastructure_service import InfrastructureService


def _service(backend) -> InfrastructureService:
    return InfrastructureService(InfrastructureRepository(backend))


def infrastructure_for_user(
    user: dict[str, Any] | None,
    backend,
    *,
    controller_id: str | None = None,
    active_only: bool = False,
) -> dict[str, Any]:
    """Return infrastructure visible to an authenticated operator.

    Admin users may request one Controller explicitly or receive all
    Controllers. Controller users are always constrained to their scope_id;
    a caller-supplied controller_id can never expand that scope. Customer and
    other roles intentionally receive no administrative topology here.
    """
    if not user:
        raise PermissionError("authentication required")

    role = str(user.get("role", "")).strip().lower()
    service = _service(backend)

    if role == "controller":
        scope_id = str(user.get("scope_id", "")).strip()
        if not scope_id:
            raise PermissionError("controller scope is required")
        if controller_id is not None and str(controller_id).strip() != scope_id:
            raise PermissionError("controller is outside user scope")

        tree = service.controller_tree(scope_id, active_only=active_only)
        if tree is None:
            raise ValueError("controller not found")
        return {"controllers": [tree]}

    if role == "admin":
        if controller_id is not None:
            requested_id = str(controller_id).strip()
            if not requested_id:
                raise ValueError("controller_id must not be empty")
            tree = service.controller_tree(requested_id, active_only=active_only)
            if tree is None:
                raise ValueError("controller not found")
            return {"controllers": [tree]}

        controllers = service.repository.controllers()
        trees = []
        for controller in controllers:
            if active_only and controller.get("status") != "active":
                continue
            tree = service.controller_tree(
                str(controller["id"]),
                active_only=active_only,
            )
            if tree is not None:
                trees.append(tree)
        return {"controllers": trees}

    raise PermissionError("infrastructure topology is not permitted")
