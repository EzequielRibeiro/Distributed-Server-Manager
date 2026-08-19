"""Persistent, exclusive instance deletion operations for the dashboard."""

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

_ACTIVE_STATES = {"queued", "stopping", "final_backup", "deleting"}
_CONFIG_SUFFIXES = {
    ".cfg", ".conf", ".config", ".ini", ".json", ".properties",
    ".toml", ".xml", ".yaml", ".yml",
}
_CONFIG_NAMES = {"serverDZ.cfg", "server.properties", "instance.conf"}
_MAP_PARTS = {
    "mpmissions", "missions", "mission", "world", "worlds", "map", "maps",
    "storage_1", "storage1",
}
_LOCK = threading.RLock()
_RUNNING: set[str] = set()


def _now() -> float:
    return time.time()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _operation_dir(root: Path, instance_id: str) -> Path:
    return root / "runtime" / "operations" / "instance-deletion" / instance_id


def _state_path(root: Path, instance_id: str) -> Path:
    return _operation_dir(root, instance_id) / "current.json"


def get_deletion_operation(root: Path, instance_id: str) -> dict:
    return _read_json(_state_path(root, instance_id))


def _save(root: Path, operation: dict, **changes) -> dict:
    operation = dict(operation)
    operation.update(changes)
    operation["updated_at"] = _now()
    _atomic_json(_state_path(root, operation["instance_id"]), operation)
    return operation


def _is_backup_file(instance: Path, path: Path) -> bool:
    relative = path.relative_to(instance)
    parts = {part.lower() for part in relative.parts}
    if parts & _MAP_PARTS:
        return True
    if path.name in _CONFIG_NAMES or path.suffix.lower() in _CONFIG_SUFFIXES:
        return True
    if ".dsm" in parts and path.is_file():
        return True
    return False


def _backup_files(instance: Path) -> list[Path]:
    files = []
    for path in instance.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink() and _is_backup_file(instance, path):
                files.append(path)
        except OSError:
            continue
    return files


def _final_backup(root: Path, instance: Path, operation: dict) -> tuple[dict, Path]:
    files = _backup_files(instance)
    total = max(1, sum(path.stat().st_size for path in files))
    backup_dir = root / "backups" / "instances" / instance.name
    backup_dir.mkdir(parents=True, exist_ok=True)

    # One canonical deletion backup per instance. A new logical deletion
    # replaces the previous backup only after the new archive is complete.
    destination = backup_dir / "final-delete.tar.gz"
    temporary = backup_dir / "final-delete.tar.gz.part"
    temporary.unlink(missing_ok=True)

    operation = _save(
        root, operation,
        state="final_backup", stage="final_backup",
        total_bytes=total, processed_bytes=0, progress=0,
        backup_name=destination.name,
        backup_scope="configuration_and_game_map",
        message="Criando backup final de configurações e mapa…",
    )

    processed = 0
    last_saved = {"bytes": 0, "time": 0.0}

    def report(delta: int) -> None:
        nonlocal processed
        processed += delta
        now = _now()
        if processed - last_saved["bytes"] < 4 * 1024 * 1024 and now - last_saved["time"] < 1:
            return
        last_saved.update(bytes=processed, time=now)
        _save(root, operation, processed_bytes=processed, progress=min(99, int(processed * 100 / total)))

    try:
        with tarfile.open(temporary, "w:gz") as archive:
            for path in files:
                arcname = Path(instance.name) / path.relative_to(instance)
                info = archive.gettarinfo(str(path), arcname=str(arcname))
                with path.open("rb") as raw:
                    remaining = info.size
                    class Reader:
                        def read(self, size=-1):
                            nonlocal remaining
                            data = raw.read(size)
                            remaining -= len(data)
                            report(len(data))
                            return data
                    archive.addfile(info, Reader())
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    operation = _save(
        root, operation,
        processed_bytes=sum(path.stat().st_size for path in files),
        total_bytes=total, progress=100,
        backup_size=destination.stat().st_size,
        backup_files=len(files),
    )
    return operation, destination


def _worker(root: Path, instance: Path, operation: dict, stop_instance: Callable[[], None], delete_record: Callable[[str], bool], audit: Callable[[str, str, str | None], None]) -> None:
    instance_id = operation["instance_id"]
    try:
        operation = _save(root, operation, state="stopping", stage="stopping", message="Preparando exclusão…")
        if instance.is_dir():
            stop_instance()
        if operation["final_backup"] and instance.is_dir():
            operation, _ = _final_backup(root, instance, operation)
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
        # Strict exclusion: while an operation is active, every later request is
        # rejected as busy. It never starts, resumes or queues another worker.
        if current.get("state") in _ACTIVE_STATES or instance_id in _RUNNING:
            busy = dict(current)
            busy["busy"] = True
            busy["accepted"] = False
            busy["message"] = "Já existe uma exclusão em andamento para esta instância."
            return busy, False

        operation = {
            "operation_id": uuid.uuid4().hex,
            "type": "instance_delete",
            "instance_id": instance_id,
            "server": server,
            "game": game,
            "final_backup": bool(final_backup),
            "state": "queued",
            "stage": "queued",
            "progress": 0,
            "processed_bytes": 0,
            "total_bytes": 0,
            "accepted": True,
            "message": "Exclusão da instância em andamento",
            "created_at": _now(),
            "updated_at": _now(),
        }
        _atomic_json(_state_path(root, instance_id), operation)
        _RUNNING.add(instance_id)
        thread = threading.Thread(target=_worker, args=(root, instance, operation, stop_instance, delete_record, audit), daemon=True, name=f"delete-{instance_id}")
        thread.start()
        return operation, True
