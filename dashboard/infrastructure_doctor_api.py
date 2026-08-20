#!/usr/bin/env python3
"""Dashboard-facing access to the modern infrastructure Doctor.

This module is transport-neutral and deliberately keeps Doctor execution
read-only. Reconciliation remains a CLI/administrative operation and is never
triggered by a Dashboard GET request.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT_DIR / "database"
for module_dir in (ROOT_DIR, DATABASE_DIR, ROOT_DIR / "dashboard"):
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))

from infrastructure_doctor_contract import build_infrastructure_doctor_payload
from runtime_backend import backend_from_environment

_ALLOWED_ROLES = {"admin", "operator", "controller"}


def infrastructure_doctor_for_user(
    user: dict[str, Any] | None,
    backend,
) -> dict[str, Any]:
    """Return the canonical read-only Doctor payload for Dashboard consumers."""
    if not user:
        raise PermissionError("authentication required")

    role = str(user.get("role") or "").strip().lower()
    if role not in _ALLOWED_ROLES:
        raise PermissionError("infrastructure Doctor requires Controller access")

    return build_infrastructure_doctor_payload(
        backend,
        reconcile=False,
    )


def main() -> int:
    """Compatibility entry point used by the temporary dashboard shell adapter."""
    role = str(os.environ.get("DSM_ROLE", "")).strip().lower()
    username = str(os.environ.get("DSM_USER", "system")).strip() or "system"
    user = {"role": role, "username": username}

    backend = backend_from_environment()
    try:
        try:
            payload = infrastructure_doctor_for_user(user, backend)
        except PermissionError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
            return 3
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    finally:
        backend.close()


__all__ = ["infrastructure_doctor_for_user"]


if __name__ == "__main__":
    raise SystemExit(main())
