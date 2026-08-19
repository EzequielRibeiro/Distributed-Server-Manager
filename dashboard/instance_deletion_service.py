"""Exclusive asynchronous instance deletion with a selective final backup."""

from __future__ import annotations

import json
import os
import shutil
import tarfile
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

ACTIVE_STATES = {"queued", "stopping", "final_backup", "deleting"}
CONFIG_SUFFIXES = {".cfg", ".conf", ".config", ".ini", ".json", ".properties", ".toml", ".xml", ".yaml", ".yml"}
CONFIG_NAMES = {"serverDZ.cfg", "server.properties", "instance.conf"}
MAP_PARTS = {"mpmissions", "missions", "mission", "world", "worlds", "map", "maps", "storage_1", "storage1"}
_LOCK = threading.RLock()
_RUNNING: set[str] = set()


def _now() -> float:
    return time.time()


def _state_path(root: Path, instance_id: str) -> Path:
    return root / "runtime" / "operations" / "instance-deletion" / instance_id / "current.json"


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def get_deletion_operation(root: Path, instance_id: str) -> dict:
    try:
        return json.loads(_state_path(root, instance_id).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _save(root: Path, operation: dict, **changes) -> dict:
    operation = dict(operation)
    operation.update(changes)
    operation["updated_at"] = _now()
    _atomic_json(_state_path(root, operation["instance_id"]), operation)
    return operation


def _included(instance: Path, path: Path) -> bool:
    relative = path.relative_to(instance)
    parts = {part.lower() for part in relative.parts}
    return bool(parts & MAP_PARTS or path.name in CONFIG_NAMES or path.suffix.lower() in CONFIG_SUFFIXES or ".dsm" in parts)


def _backup_files(instance: Path) -> list[Path]:
    result = []
    for path in instance.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink() and _included(instance, path):
                result.append(path)
        except OSError:
            continue
    return result


def _final_backup(root: Path, instance: Path, operation: dict) -> dict:
    files = _backup_files(instance)
    total = max(1, sum(path.stat().st_size for path in files))
    directory = root / "backups" / "instances" / instance.name
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "final-delete.tar.gz"
    temporary = directory / "final-delete.tar.gz.part"
    temporary.unlink(missing_ok=True)
    operation = _save(
        root,
        operation,
        state="final_backup",
        stage="final_backup",
        total_bytes=total,
        processed_bytes=0,
        progress=0,
        backup_name=destination.name,
        backup_path=str(destination.relative_to(root)),
        backup_scope="configuration_and_game_map",
        backup_download_state="creating",
        backup_downloaded_at=None,
        backup_removed_at=None,
        message="Criando backup final…",
    )
    processed = 0
    checkpoint_bytes = 0
    checkpoint_time = 0.0

    def progress(delta: int) -> None:
        nonlocal processed, checkpoint_bytes, checkpoint_time
        processed += delta
        now = _now()
        if processed - checkpoint_bytes < 4 * 1024 * 1024 and now - checkpoint_time < 1:
            return
        checkpoint_bytes, checkpoint_time = processed, now
        _save(root, operation, processed_bytes=processed, progress=min(99, int(processed * 100 / total)))

    try:
        with tarfile.open(temporary, "w:gz") as archive:
            for path in files:
                info = archive.gettarinfo(str(path), arcname=str(Path(instance.name) / path.relative_to(instance)))
                with path.open("rb") as raw:
                    class Reader:
                        def read(self, size=-1):
                            data = raw.read(size)
                            progress(len(data))
                            return data
                    archive.addfile(info, Reader())
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return _save(
        root,
        operation,
        processed_bytes=total,
        total_bytes=total,
        progress=100,
        backup_size=destination.stat().st_size,
        backup_files=len(files),
        backup_download_state="pending",
        backup_ready_at=_now(),
    )


def _worker(root: Path, instance: Path, operation: dict, stop_instance: Callable[[], None], delete_record: Callable[[str], bool], audit: Callable[[str, str, str | None], None]) -> None:
    instance_id = operation["instance_id"]
    try:
        operation = _save(root, operation, state="stopping", stage="stopping", message="Preparando exclusão…")
        if instance.is_dir():
            stop_instance()
        if operation["final_backup"] and instance.is_dir():
            operation = _final_backup(root, instance, operation)
        operation = _save(root, operation, state="deleting", stage="deleting", progress=100, message="Excluindo instância…")
        quarantine = instance.with_name(f".{instance.name}.deleting-{operation['operation_id'][:8]}")
        existed = instance.is_dir()
        if existed:
            instance.rename(quarantine)
        try:
            if not delete_record(instance_id):
                raise ValueError("instance is not registered or was already deleted")
            if quarantine.exists():
                shutil.rmtree(quarantine)
            resource = root / "runtime" / "resources" / operation["server"] / operation["game"] / instance_id
            if resource.is_dir():
                shutil.rmtree(resource)
        except Exception:
            if existed and quarantine.exists() and not instance.exists():
                quarantine.rename(instance)
            raise
        _save(root, operation, state="completed", stage="completed", progress=100, message="Instância excluída com sucesso.", completed_at=_now())
        audit("instance.delete", "success", operation["operation_id"])
    except Exception as exc:
        _save(root, operation, state="failed", stage="failed", message="Não foi possível excluir a instância.", error=str(exc), failed_at=_now())
        audit("instance.delete", "error", str(exc))
    finally:
        with _LOCK:
            _RUNNING.discard(instance_id)


def start_deletion(root: Path, instance: Path, *, server: str, game: str, final_backup: bool, stop_instance: Callable[[], None], delete_record: Callable[[str], bool], audit: Callable[[str, str, str | None], None]) -> tuple[dict, bool]:
    instance_id = instance.name
    with _LOCK:
        current = get_deletion_operation(root, instance_id)
        if current.get("state") in ACTIVE_STATES or instance_id in _RUNNING:
            busy = dict(current)
            busy.update(busy=True, accepted=False, message="Já existe uma exclusão em andamento para esta instância.")
            return busy, False
        operation = {"operation_id": uuid.uuid4().hex, "type": "instance_delete", "instance_id": instance_id, "server": server, "game": game, "final_backup": bool(final_backup), "state": "queued", "stage": "queued", "progress": 0, "processed_bytes": 0, "total_bytes": 0, "accepted": True, "message": "Exclusão da instância em andamento", "created_at": _now(), "updated_at": _now()}
        _atomic_json(_state_path(root, instance_id), operation)
        _RUNNING.add(instance_id)
        threading.Thread(target=_worker, args=(root, instance, operation, stop_instance, delete_record, audit), daemon=True, name=f"delete-{instance_id}").start()
        return operation, True
