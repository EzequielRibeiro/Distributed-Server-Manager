#!/usr/bin/env python3

"""Transport-neutral HTTP contract for instance lifecycle operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs


DELETE_STATUS_PATH = "/api/instance/delete/status"
DELETE_PATH = "/api/instance/delete"
REINSTALL_PATH = "/api/instance/reinstall/v2"


def _single_query_value(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name, [])
    if not values:
        return ""
    return str(values[0]).strip()


def _identity_from_query(query_string: str) -> tuple[str, str, str]:
    query = parse_qs(query_string, keep_blank_values=True)
    return (
        _single_query_value(query, "server"),
        _single_query_value(query, "game").lower(),
        _single_query_value(query, "instance"),
    )


def _identity_from_payload(payload: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(payload.get("server", "")).strip(),
        str(payload.get("game", "")).strip().lower(),
        str(payload.get("instance", "")).strip(),
    )


def _require_identity(server: str, game: str, instance: str) -> None:
    if not all((server, game, instance)):
        raise ValueError("server, game and instance are required")


def dispatch_instance_lifecycle_get(path: str, query_string: str, *, user: dict[str, Any] | None, root: Path, resolve_instance: Callable[[str, str, str], Path | str], can_access: Callable[..., bool], deletion_status: Callable[[Path, str], dict[str, Any]]) -> tuple[int, dict[str, Any]] | None:
    if path != DELETE_STATUS_PATH:
        return None
    server, game, instance_id = _identity_from_query(query_string)
    _require_identity(server, game, instance_id)
    instance_path = Path(resolve_instance(server, game, instance_id))
    if not can_access(user, instance_path, write=True):
        raise PermissionError("Usuário sem permissão para acessar esta instância.")
    return 200, deletion_status(root, instance_id)


def dispatch_instance_lifecycle_post(path: str, payload: dict[str, Any], *, user: dict[str, Any] | None, root: Path, resolve_instance: Callable[[str, str, str], Path | str], has_permission: Callable[..., bool], begin_deletion: Callable[..., tuple[int, dict[str, Any]]], stop_instance: Callable[[], None], delete_record: Callable[[str], bool], audit: Callable[[str, str, str | None], None], reinstall_busy: Callable[[str], bool] | None = None) -> tuple[int, dict[str, Any]] | None:
    if path != DELETE_PATH:
        return None
    server, game, instance_id = _identity_from_payload(payload)
    _require_identity(server, game, instance_id)
    instance_path = Path(resolve_instance(server, game, instance_id))
    if not has_permission(user, instance_path, "instance.delete"):
        raise PermissionError("Usuário sem permissão para excluir esta instância.")
    if reinstall_busy is not None and reinstall_busy(instance_id):
        return 409, {"error": "Reinstalação em andamento; a exclusão está bloqueada.", "busy": True, "instance_id": instance_id}
    if str(payload.get("confirmation", "")) != instance_path.name:
        raise ValueError("instance identifier confirmation does not match")
    final_backup = payload.get("final_backup") is True
    owner = user if isinstance(user, dict) else {}
    status, operation = begin_deletion(
        root,
        instance_path,
        server=server,
        game=game,
        final_backup=final_backup,
        stop_instance=stop_instance,
        delete_record=delete_record,
        audit=audit,
        backup_owner={
            "username": owner.get("username", ""),
            "scope_id": owner.get("scope_id", ""),
            "role": owner.get("role", ""),
        },
    )
    return status, operation


def dispatch_instance_reinstall_post(path: str, payload: dict[str, Any], *, user: dict[str, Any] | None, resolve_instance: Callable[[str, str, str], Path | str], can_access: Callable[..., bool], reinstall_busy: Callable[[str], bool], reinstall_instance: Callable[..., dict[str, Any]], runner: Callable[[bool], dict[str, Any]], deletion_status: Callable[[Path, str], dict[str, Any]] | None = None, root: Path | None = None) -> tuple[int, dict[str, Any]] | None:
    if path != REINSTALL_PATH:
        return None
    server, game, instance_id = _identity_from_payload(payload)
    _require_identity(server, game, instance_id)
    instance_path = Path(resolve_instance(server, game, instance_id))
    if not can_access(user, instance_path, write=True):
        raise PermissionError("Usuário sem permissão para reinstalar esta instância.")
    deletion_active = False
    if deletion_status is not None:
        if root is None:
            raise ValueError("root is required when deletion_status is provided")
        deletion_operation = deletion_status(root, instance_id)
        deletion_active = bool(isinstance(deletion_operation, dict) and deletion_operation.get("active"))
    if deletion_active or reinstall_busy(instance_id):
        return 409, {"error": "Já existe uma operação incompatível em andamento para esta instância.", "busy": True, "instance_id": instance_id}
    preserve_config = payload.get("preserve_config", True) is True
    preserve_map = payload.get("preserve_map", True) is True
    result = reinstall_instance(instance_path, preserve_config=preserve_config, preserve_map=preserve_map, runner=runner)
    return 200, result
