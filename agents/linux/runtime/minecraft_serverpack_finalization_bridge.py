"""Durable, lock-scoped reconciliation for already-finalized provisioning.

This bridge does not start/stop game processes, archive data, or invoke
rollback. The caller must hold the instance_lock and supply Agent-owned state
paths. Production scheduling remains separately gated.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from minecraft_serverpack_finalization_coordinator import reconcile_finalization


class FinalizationBridgeError(RuntimeError):
    pass


def _safe_file(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise FinalizationBridgeError("unsafe or missing journal")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FinalizationBridgeError("unreadable journal") from exc
    if not isinstance(data, dict):
        raise FinalizationBridgeError("invalid journal")
    return data


def _durable_completed_operation(path: Path, payload: dict[str, Any]) -> None:
    """Write journal with restrictive mode and fsync before releasing barrier."""
    if path.is_symlink() or not path.is_file():
        raise FinalizationBridgeError("operation journal became unsafe")
    parent=path.parent
    old=path.stat()
    temporary=path.with_name(f".{path.name}.{os.getpid()}.reconcile.tmp")
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags|=os.O_NOFOLLOW
    fd=os.open(temporary,flags,0o600)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as output:
            data=json.dumps(payload,sort_keys=True,indent=2)+"\n"
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary,0o600)
        current=temporary.stat()
        if (current.st_uid,current.st_gid)!=(old.st_uid,old.st_gid):
            os.chown(temporary,old.st_uid,old.st_gid)
        if path.is_symlink() or not path.is_file() or path.stat().st_ino!=old.st_ino:
            raise FinalizationBridgeError("operation journal replaced before write")
        os.replace(temporary,path)
        directory_fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def reconcile_published_migration(
    *,
    instance_id: str,
    agent_id: str,
    operation_path: Path,
    provisioning_path: Path,
    history_root: Path,
) -> dict[str, Any]:
    """Reconcile after a crash between provisioning success and outer completion.

    IMPORTANT: exclusively invoked under the per-instance runtime lock.
    All paths are supplied by the trusted Agent; no path comes from input JSON.
    """
    operation = _safe_file(operation_path)
    result = _safe_file(provisioning_path)
    detail = result.get("minecraft_serverpack_migration")
    if not isinstance(detail, dict):
        raise FinalizationBridgeError("missing migration detail")
    final = detail.get("finalization")
    if not isinstance(final, dict) or final.get("status") not in {"archived", "already_archived"}:
        raise FinalizationBridgeError("missing archival evidence")
    # Validate the real journal within the instance-specific history tree,
    # not an untrusted path embedded in provisioning or filesystem journal.
    root = Path(history_root)
    if root.is_symlink() or not root.is_dir():
        raise FinalizationBridgeError("unsafe migration history")
    proof_digest = str(final.get("sha256") or "").strip().lower()
    if len(proof_digest) != 64 or any(x not in "0123456789abcdef" for x in proof_digest):
        raise FinalizationBridgeError("archive digest not attested")
    archived_dir = root / proof_digest[:24]
    archived_journal = archived_dir / "minecraft-serverpack-migration.json"
    if archived_dir.is_symlink() or not archived_dir.is_dir():
        raise FinalizationBridgeError("unsafe archive directory")
    if archived_journal.is_symlink() or not archived_journal.is_file():
        raise FinalizationBridgeError("archived journal missing")
    content = archived_journal.read_bytes()
    if hashlib.sha256(content).hexdigest() != proof_digest:
        raise FinalizationBridgeError("archived journal checksum mismatch")
    try:
        archived = json.loads(content)
    except ValueError as exc:
        raise FinalizationBridgeError("archived journal cannot be decoded") from exc
    if (not isinstance(archived, dict)
            or archived.get("phase") != "committed"
            or archived.get("migration_plan_sha256") != detail.get("migration_plan_sha256")
            or archived.get("target_loader_version") != detail.get("target_loader_version")):
        raise FinalizationBridgeError("archived journal does not match completed migration")

    def finish(outer: dict[str, Any]) -> None:
        # Read under lock again before any mutation; refuse lost updates.
        current = _safe_file(operation_path)
        if current != outer or current.get("status") != "finalization_pending":
            raise FinalizationBridgeError("operation changed during reconciliation")
        written = dict(current)
        written["status"] = "completed"
        written["finalization_reconciled"] = True
        _durable_completed_operation(operation_path, written)

    return reconcile_finalization(
        operation=operation,
        result=result,
        instance_id=instance_id,
        agent_id=agent_id,
        complete_operation=finish,
        run_recovery=lambda: (_ for _ in ()).throw(FinalizationBridgeError("recovery not allowed by this bridge")),
        complete_provisioning=lambda _: (_ for _ in ()).throw(FinalizationBridgeError("provisioning is not completed")),
    )
