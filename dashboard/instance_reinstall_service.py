"""Safe reinstall orchestration for an existing game instance."""
from __future__ import annotations
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Callable

_LOCK = threading.RLock()
_ACTIVE: set[str] = set()
MAP_PATHS = ("mpmissions", "missions", "world", "worlds")


def reinstall_busy(instance_id: str) -> bool:
    with _LOCK:
        return instance_id in _ACTIVE


def reinstall_instance(instance: Path, *, preserve_config: bool, preserve_map: bool, runner: Callable[[bool], dict]) -> dict:
    """Run exactly one reinstall per instance and optionally preserve map state.

    ``runner`` is the existing provider/game-data reinstall implementation. Config
    preservation remains delegated to it; this service adds map/persistence
    preservation without coupling provider details to the HTTP layer.
    """
    instance_id = instance.name
    with _LOCK:
        if instance_id in _ACTIVE:
            raise RuntimeError("Já existe uma reinstalação em andamento para esta instância.")
        _ACTIVE.add(instance_id)
    temporary_root = None
    try:
        snapshots: list[tuple[Path, Path]] = []
        if preserve_map and instance.is_dir():
            temporary_root = Path(tempfile.mkdtemp(prefix=f"capivara-reinstall-{instance_id}-"))
            for relative in MAP_PATHS:
                source = instance / "serverfiles" / relative
                if source.exists():
                    target = temporary_root / relative
                    if source.is_dir(): shutil.copytree(source, target)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target)
                    snapshots.append((target, source))
        result = runner(bool(preserve_config))
        if preserve_map:
            for snapshot, destination in snapshots:
                if destination.exists():
                    shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
                destination.parent.mkdir(parents=True, exist_ok=True)
                if snapshot.is_dir(): shutil.copytree(snapshot, destination)
                else: shutil.copy2(snapshot, destination)
        return {**(result if isinstance(result, dict) else {"result": result}), "preserve_config": bool(preserve_config), "preserve_map": bool(preserve_map)}
    finally:
        if temporary_root:
            shutil.rmtree(temporary_root, ignore_errors=True)
        with _LOCK:
            _ACTIVE.discard(instance_id)
