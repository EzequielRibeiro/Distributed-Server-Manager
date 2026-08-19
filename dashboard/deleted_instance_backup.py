"""Secure access to retained backups from deleted instances."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from instance_deletion_service import get_deletion_operation


def _same_owner(user: dict[str, Any], owner: dict[str, Any]) -> bool:
    role = str(user.get("role", ""))
    if role in {"admin", "controller"}:
        return True
    if role != "customer":
        return False
    user_scope = str(user.get("scope_id", ""))
    owner_scope = str(owner.get("scope_id", ""))
    if user_scope and owner_scope:
        return user_scope == owner_scope
    return bool(user.get("username")) and str(user.get("username")) == str(owner.get("username", ""))


def resolve_deleted_instance_backup(root: Path, instance_id: str, user: dict[str, Any] | None) -> tuple[Path, dict]:
    """Return a retained final backup only to the account that owned its deletion."""
    if not instance_id:
        raise ValueError("instance is required")
    if not isinstance(user, dict):
        raise PermissionError("authentication required")

    operation = get_deletion_operation(root, instance_id)
    if not operation:
        raise FileNotFoundError("backup record not found")
    if operation.get("state") != "completed":
        raise FileNotFoundError("backup is not ready")
    if operation.get("backup_download_state") != "pending":
        raise FileNotFoundError("backup is not pending download")
    if not _same_owner(user, operation.get("backup_owner", {})):
        raise PermissionError("Usuário sem permissão para baixar este backup.")

    relative = str(operation.get("backup_path", ""))
    if not relative:
        raise FileNotFoundError("backup path not registered")
    candidate = (root / relative).resolve()
    allowed = (root / "backups" / "instances" / instance_id).resolve()
    try:
        candidate.relative_to(allowed)
    except ValueError as exc:
        raise PermissionError("invalid backup path") from exc
    if not candidate.is_file() or candidate.is_symlink():
        raise FileNotFoundError("backup file not found")
    return candidate, operation
