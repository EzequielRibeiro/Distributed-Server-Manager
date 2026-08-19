"""Persistent, idempotent instance deletion operations for the dashboard."""

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


def _tree_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            continue
    return total


class _ProgressReader:
    def __init__(self, raw, callback: Callable[[int], None]):
        self.raw = raw
        self.callback = callback
        self.count = 0

    def read(self, size=-1):
        data = self.raw.read(size)
        self.count += len(data)
        self.callback(self.count)
        return data

    def __getattr__(self, name):
        return getattr(self.raw, name)


def _final_backup(root: Path, instance: Path, operation: dict) -> tuple[dict, Path]:
    total = max(1, _tree_size(instance))
    backup_dir = root / "backups" / "instances" / instance.name
    backup_dir.mkdir(parents=True, exist_ok=True)
    name = f"final-delete-{operation['operation_id']}.tar.gz"
    destination = backup_dir / name
    temporary = destination.with_suffix(destination.suffix + ".part")

    operation = _save(
        root,
        operation,
        state="final_backup",
        stage="final_backup",
        total_bytes=total,
        processed_bytes=0,
        progress=0,
        backup_name=name,
        message="Criando backup final…",
    )

    last_saved = {"bytes": 0, "time": 0.0}

    def report(processed: int) -> None:
        now = _now()
        if processed - last_saved["bytes"] < 4 * 1024 * 1024 and now - last_saved["time"] < 1:
            return
        last_saved.update(bytes=processed, time=now)
        percent = min(99, int(processed * 100 / total))
        _save(root, operation, processed_bytes=processed, progress=percent)

    try:
        with tarfile.open(temporary, "w:gz") as archive:
            for path in instance.rglob("*"):
                if path.is_symlink():
                    continue
                arcname = Path(instance.name) / path.relative_to(instance)
                if path.is_dir():
                    archive.add(path, arcname=str(arcname), recursive=False)
                    continue
                if not path.is_file():
                    continue
                info = archive.gettarinfo(str(path), arcname=str(arcname))
                with path.open("rb") as raw:
                    archive.addfile(info, _ProgressReader(raw, report))
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    operation = _save(
        root,
        operation,
        processed_bytes=total,
        total_bytes=total,
        progress=100,
        backup_size=destination.stat().st_size,
    )
    return operation, destination


def _worker(
    root: Path,
    instance: Path,
    operation: dict,
    stop_instance: Callable[[], None],
    delete_record: Callable[[str], bool],
    audit: Callable[[str, str, str | None], None],
) -> None:
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


def start_deletion(
    root: Path,
    instance: Path,
    *,
    server: str,
    game: str,
    final_backup: bool,
    stop_instance: Callable[[], None],
    delete_record: Callable[[str], bool],
    audit: Callable[[str, str, str | None], None],
) -> tuple[dict, bool]:
    instance_id = instance.name
    with _LOCK:
        current = get_deletion_operation(root, instance_id)
        if current.get("state") in _ACTIVE_STATES:
            if instance_id not in _RUNNING:
                _RUNNING.add(instance_id)
                thread = threading.Thread(
                    target=_worker,
                    args=(root, instance, current, stop_instance, delete_record, audit),
                    daemon=True,
                    name=f"delete-{instance_id}",
                )
                thread.start()
            return current, False

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
            "message": "Exclusão da instância em andamento",
            "created_at": _now(),
            "updated_at": _now(),
        }
        _atomic_json(_state_path(root, instance_id), operation)
        _RUNNING.add(instance_id)
        thread = threading.Thread(
            target=_worker,
            args=(root, instance, operation, stop_instance, delete_record, audit),
            daemon=True,
            name=f"delete-{instance_id}",
        )
        thread.start()
        return operation, True
