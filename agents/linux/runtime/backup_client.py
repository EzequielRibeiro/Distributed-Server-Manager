#!/usr/bin/env python3
"""Safe local executor for Universal Smart Backup commands."""

from __future__ import annotations

import fnmatch
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from instance_runtime import get_instance, lifecycle, status
from backup_storage_accounting import quota_snapshot, source_size

STATE_ROOT = Path(
    os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent")
)
BACKUP_ROOT = Path(
    os.environ.get("CAPIVARA_BACKUP_ROOT", str(STATE_ROOT / "backups"))
).resolve()
RESULT_ROOT = STATE_ROOT / "backup-results"
PRIVILEGED_RESTORE_ROOT = STATE_ROOT / "privileged-backup-restore"
MANIFEST_NAME = ".capivara-backup-manifest.json"


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe(value):
    text = str(value or "").strip()
    if not text or "/" in text or "\\" in text or text in {".", ".."}:
        raise ValueError("unsafe backup identifier")
    return text


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def _backup_root(record):
    raw = (
        record.get("files_root")
        or record.get("instance_state_root")
        or record.get("configuration_root")
        or record.get("working_directory")
        or record.get("path")
    )
    if not str(raw or "").strip():
        raise ValueError("instance backup root is not configured")
    root = Path(str(raw)).resolve()
    if not root.is_dir():
        raise FileNotFoundError("instance backup root missing")
    return root


def _owned(config, instance_id):
    record = get_instance(_safe(instance_id))
    if not record:
        raise LookupError("instance not found")
    if str(record.get("agent_id") or "") != str(config.get("agent_id") or ""):
        raise PermissionError("instance belongs to another Agent")
    return record, _backup_root(record)


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _selected(root, policy):
    includes = list(policy.get("include_paths") or [])
    excludes = list(policy.get("exclude_paths") or [])
    mode = str(policy.get("mode") or "full")
    if mode != "full" and not includes:
        raise ValueError("non-full backup requires include_paths")

    candidates = []
    if includes:
        for relative in includes:
            path = (root / str(relative)).resolve()
            path.relative_to(root)
            if path.exists():
                candidates.append(path)
    else:
        candidates = [root]

    def excluded(path):
        relative = path.relative_to(root).as_posix()
        return any(
            fnmatch.fnmatch(relative, pattern)
            or fnmatch.fnmatch(relative + "/", pattern.rstrip("/") + "/")
            for pattern in excludes
        )

    selected = [path for path in candidates if not excluded(path)]
    if not selected:
        raise ValueError("backup selection contains no paths")
    return selected


def _manifest(record, backup_id):
    return {
        "schema_version": 1,
        "kind": "CapivaraInstanceBackup",
        "backup_format": "capivara-instance",
        "backup_id": backup_id,
        "source_instance": record.get("instance_id"),
        "game_id": record.get("game_id"),
        "runtime_id": record.get("runtime_id"),
        "game_version": record.get("game_version") or record.get("version"),
        "created_at": _now(),
    }


def _create_archive(root, paths, destination, compression, manifest):
    mode = "w:gz" if compression == "gzip" else "w"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, mode, dereference=False) as archive:
        encoded = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(encoded)
        info.mode = 0o600
        archive.addfile(info, __import__("io").BytesIO(encoded))
        for path in paths:
            arcname = "." if path == root else path.relative_to(root).as_posix()
            archive.add(
                path,
                arcname=arcname,
                recursive=True,
                filter=lambda item: None
                if item.issym() or item.islnk()
                else item,
            )


def _validate_archive_payload(archive_path):
    """Fail closed if an archive has no regular instance files.

    Also fully reads file payloads so truncated gzip/tar data cannot be
    mistaken for a verified backup. Never extracts anything.
    """
    found = False
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive:
            if member.name == MANIFEST_NAME:
                continue
            if member.issym() or member.islnk() or member.isdev():
                raise ValueError("backup contains links or devices")
            # Check path traversal before stopping an instance, not during extraction.
            parts = Path(member.name).parts
            if member.name.startswith("/") or ".." in parts or (not parts and member.name != "."):
                raise ValueError("backup contains unsafe path")
            if not member.isfile():
                continue
            found = True
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("backup contains unreadable file")
            while stream.read(1024 * 1024):
                pass
    if not found:
        raise ValueError("backup contains no instance files")


def _safe_extract(archive_path, destination):
    manifest = None
    with tarfile.open(archive_path, "r:*") as archive:
        members = archive.getmembers()
        base = destination.resolve()
        for member in members:
            if member.issym() or member.islnk() or member.isdev():
                raise ValueError("backup contains links or devices")
            target = (base / member.name).resolve()
            target.relative_to(base)
            if member.name == MANIFEST_NAME:
                handle = archive.extractfile(member)
                if handle:
                    try:
                        manifest = json.loads(handle.read().decode("utf-8"))
                    except Exception as exc:
                        raise ValueError("backup manifest is invalid") from exc
        archive.extractall(base, members=members, filter="data")

    if not any(p.is_file() for p in destination.rglob("*") if p.name != MANIFEST_NAME):
        raise ValueError("restore archive contains no instance files")

    if manifest is not None and (
        manifest.get("kind") != "CapivaraInstanceBackup"
        or manifest.get("backup_format") != "capivara-instance"
    ):
        raise ValueError("unsupported backup manifest")
    return manifest


def _retained_backup_capacity(instance_dir, policy):
    """Conservative headroom guard for explicitly enabled age retention.

    A failed preflight does not create a partial archive or delete older ones.
    The initial storage sizing must still be approved before production opt-in.
    """
    if "retention_days" not in policy:
        return
    days = policy["retention_days"]
    if type(days) is not int or not 1 <= days <= 365:
        raise ValueError("invalid retention_days in backup command")
    previous = sorted(
        (item for item in instance_dir.glob("*.tar*") if item.is_file()),
        key=lambda item: item.stat().st_mtime, reverse=True,
    )
    expected_bytes = previous[0].stat().st_size if previous else 0
    required_free = max(8 * 1024 ** 3, expected_bytes * 2 + 4 * 1024 ** 3)
    disk_root = instance_dir.parent
    while not disk_root.exists() and disk_root != disk_root.parent:
        disk_root = disk_root.parent
    available_free = shutil.disk_usage(disk_root).free
    if available_free < required_free:
        raise OSError("backup age retention capacity preflight failed: preserve existing backups")


def _create(config, command):
    """Serialize creates per instance to keep quota snapshots authoritative."""
    instance_id = _safe(command["instance_id"])
    # Non-mutating checks must run before creating even a lock file.
    record, root = _owned(config, instance_id)
    _selected(root, dict(command.get("policy") or {}))
    locks = STATE_ROOT / "backup-create-locks"
    locks.mkdir(parents=True, exist_ok=True)
    lock_path = locks / f"{instance_id}.lock"
    if lock_path.is_symlink():
        raise OSError("backup creation lock is unsafe")
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            return _create_unlocked(config, command)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _create_unlocked(config, command):
    instance_id = str(command["instance_id"])
    record, root = _owned(config, instance_id)
    policy = dict(command.get("policy") or {})
    consistency = str(policy.get("consistency") or "live")
    was_running = False
    # All non-mutating preflights must succeed before stopping a live game.
    instance_dir = BACKUP_ROOT / _safe(instance_id)
    _retained_backup_capacity(instance_dir, policy)
    selected_paths = _selected(root, policy)
    # Both limits are controller/Agent authoritative: the smaller one wins.
    # Never interpret an unknown quota as unlimited for a new customer backup.
    limits = []
    for raw in (record.get("storage_limit_bytes"), policy.get("storage_limit_bytes")):
        if raw is not None:
            if type(raw) is bool or int(raw) <= 0:
                raise ValueError("invalid storage quota for backup")
            limits.append(int(raw))
    if not limits:
        raise OSError("backup denied: instance storage quota is unavailable")
    quota_limit = min(limits)
    snapshot = quota_snapshot(record, BACKUP_ROOT)
    if (BACKUP_ROOT / _safe(instance_id)).resolve().is_relative_to(root):
        raise OSError("backup storage must not be inside the archived source directory")
    estimate = source_size(selected_paths, root)
    # TAR/gzip may expand slightly. Reserve an overhead and never assume
    # compression savings when checking capacity.
    reserve = estimate + max(2 * 1024 * 1024, estimate // 100)
    if snapshot["total_used_bytes"] + reserve > quota_limit:
        raise OSError("backup denied: instance plus archived backups exceed storage quota")
    disk_parent = BACKUP_ROOT
    while not disk_parent.exists() and disk_parent != disk_parent.parent:
        disk_parent = disk_parent.parent
    if shutil.disk_usage(disk_parent).free < reserve + 64 * 1024 * 1024:
        raise OSError("backup denied: insufficient disk space to preserve existing archives")

    if consistency == "quiesced":
        raise RuntimeError(
            "quiesced backup requires a game-specific consistency hook"
        )
    if consistency == "stopped":
        was_running = (
            status(config, instance_id).get("observed_state") == "running"
        )
        if was_running:
            lifecycle(config, instance_id, "stop")

    try:
        backup_id = str(uuid.uuid4())
        suffix = (
            ".tar.gz"
            if str(policy.get("compression") or "gzip") == "gzip"
            else ".tar"
        )
        path = instance_dir / f"{backup_id}{suffix}"
        manifest = _manifest(record, backup_id)
        if path.exists():
            raise FileExistsError(f"backup destination already exists: {path}")
        try:
            _create_archive(
                root,
                selected_paths,
                path,
                str(policy.get("compression") or "gzip"),
                manifest,
            )
            size = path.stat().st_size
            # Re-scan real files after writing; races or unexpectedly large
            # output must never commit a backup beyond the quota.
            after = quota_snapshot(record, BACKUP_ROOT)
            if after["total_used_bytes"] > quota_limit:
                raise OSError("backup denied: final archive exceeds storage quota")
            _validate_archive_payload(path)
            sha256 = _digest(path)
        except Exception:
            # Only this newly allocated destination may be removed on failure.
            # An earlier completed backup is never affected by a failed create.
            path.unlink(missing_ok=True)
            raise
        manifest["files_checksum"] = sha256
        # Retention is deliberately disabled until an explicit, separately
        # approved non-destructive policy is implemented. Never prune here.
        return {
            "backup_id": backup_id,
            "artifact_path": str(path),
            "size_bytes": size,
            "sha256": sha256,
            "manifest": manifest,
            "quota_limit_bytes": quota_limit,
            "quota_total_used_bytes": after["total_used_bytes"],
            "quota_backup_used_bytes": after["backup_used_bytes"],
        }
    finally:
        if consistency == "stopped" and was_running:
            lifecycle(config, instance_id, "start")


def _artifact(instance_id, backup_id):
    instance_dir = (BACKUP_ROOT / _safe(instance_id)).resolve()
    instance_dir.relative_to(BACKUP_ROOT)
    matches = list(instance_dir.glob(f"{_safe(backup_id)}.tar*"))
    if not matches:
        raise FileNotFoundError("backup artifact not found")
    if len(matches) > 1:
        raise RuntimeError("multiple backup artifacts found")
    return matches[0]


def _validate_manifest(record, manifest):
    if not manifest:
        return
    if str(manifest.get("game_id") or "") and str(
        manifest.get("game_id")
    ) != str(record.get("game_id") or ""):
        raise ValueError("backup game is incompatible with this instance")
    source_runtime = str(manifest.get("runtime_id") or "")
    target_runtime = str(record.get("runtime_id") or "")
    if source_runtime and target_runtime and source_runtime != target_runtime:
        raise ValueError("backup runtime is incompatible with this instance")



def _preserve_restored_owner(stage: Path, original: Path) -> None:
    """Restore the instance owner's UID/GID before activating a root-staged tree."""
    if os.geteuid() != 0:
        return
    owner = original.stat()
    pending = [stage]
    while pending:
        current = pending.pop()
        if current.is_symlink():
            raise RuntimeError(f"restore staging contains a symlink: {current}")
        if current.is_dir():
            pending.extend(current.iterdir())
        elif not current.is_file():
            raise RuntimeError(f"unsupported restore staging entry: {current}")
        os.chown(current, owner.st_uid, owner.st_gid)


def _restore_direct(config, command):
    """Restore locally when the Agent process owns the storage boundary."""
    instance_id = str(command["instance_id"])
    record, root = _owned(config, instance_id)
    artifact = _artifact(instance_id, str(command.get("backup_id") or ""))
    previous = root.with_name(root.name + ".c5-previous")
    if previous.exists():
        raise RuntimeError(
            f"refusing restore: pre-existing recovery directory {previous}"
        )
    was_running = status(config, instance_id).get("observed_state") == "running"
    # Validate before stopping the game or moving any live files.
    _validate_archive_payload(artifact)
    # Verify manifest compatibility before any lifecycle mutation.
    with tarfile.open(artifact, "r:*") as archive:
        manifest_member = next((m for m in archive if m.name == MANIFEST_NAME), None)
        if manifest_member is None or not manifest_member.isfile():
            raise ValueError("backup manifest is missing")
        handle = archive.extractfile(manifest_member)
        if handle is None:
            raise ValueError("backup manifest is unreadable")
        try:
            manifest = json.loads(handle.read().decode("utf-8"))
        except Exception as exc:
            raise ValueError("backup manifest is invalid") from exc
        if not isinstance(manifest, dict) or (
            manifest.get("kind") != "CapivaraInstanceBackup"
            or manifest.get("backup_format") != "capivara-instance"
        ):
            raise ValueError("unsupported backup manifest")
        _validate_manifest(record, manifest)
    if was_running:
        lifecycle(config, instance_id, "stop")

    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{root.name}.restore-",
            dir=str(root.parent),
        )
    )
    moved_original = False

    try:
        manifest = _safe_extract(artifact, stage)
        _validate_manifest(record, manifest)
        manifest_path = stage / MANIFEST_NAME
        if manifest_path.exists():
            manifest_path.unlink()
        _preserve_restored_owner(stage, root)
        os.replace(root, previous)
        moved_original = True
        os.replace(stage, root)

        if was_running:
            lifecycle(config, instance_id, "start")
            after = status(config, instance_id)
            if after.get("observed_state") != "running":
                raise RuntimeError(
                    "restored server did not become healthy enough to run"
                )

        # Cleanup is not part of the activation transaction. An incomplete
        # deletion must not trigger rollback using a partially removed copy.
        try:
            shutil.rmtree(previous)
        except OSError:
            # Preserve any remaining recovery files for explicit inspection.
            pass
    except Exception as original_error:
        rollback_errors = []
        if moved_original:
            try:
                if root.exists():
                    shutil.rmtree(root)
                os.replace(previous, root)
            except Exception as exc:
                rollback_errors.append(f"directory recovery failed: {exc}")
        if was_running:
            try:
                lifecycle(config, instance_id, "start")
            except Exception as exc:
                rollback_errors.append(f"restart recovery failed: {exc}")
        if rollback_errors:
            raise RuntimeError(
                f"restore failed: {original_error}; "
                + "; ".join(rollback_errors)
                + f"; recovery copy may remain at {previous}"
            ) from original_error
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    return {
        "backup_id": str(command.get("backup_id")),
        "artifact_path": str(artifact),
        "size_bytes": artifact.stat().st_size,
        "sha256": _digest(artifact),
    }


def _restore_via_privileged_helper(config, command, unit_template):
    command_id = _safe(command.get("command_id"))
    instance_id = _safe(command.get("instance_id"))
    backup_id = _safe(command.get("backup_id"))
    agent_id = _safe(config.get("agent_id"))

    # Fail before dispatching systemd: never stop a game for an empty backup.
    record, _root = _owned(config, instance_id)
    artifact = _artifact(instance_id, backup_id)
    _validate_archive_payload(artifact)
    with tarfile.open(artifact, "r:*") as archive:
        manifest_member = next((m for m in archive if m.name == MANIFEST_NAME), None)
        if manifest_member is None or not manifest_member.isfile():
            raise ValueError("backup manifest is missing")
        if manifest_member is not None:
            handle = archive.extractfile(manifest_member)
            if handle is None:
                raise ValueError("backup manifest is unreadable")
            try:
                manifest = json.loads(handle.read().decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise ValueError("backup manifest is invalid") from exc
            if not isinstance(manifest, dict) or manifest.get("kind") != "CapivaraInstanceBackup" or manifest.get("backup_format") != "capivara-instance":
                raise ValueError("unsupported backup manifest")
            _validate_manifest(record, manifest)

    request_path = PRIVILEGED_RESTORE_ROOT / f"{command_id}.request.json"
    result_path = PRIVILEGED_RESTORE_ROOT / f"{command_id}.result.json"
    try:
        result_path.unlink()
    except FileNotFoundError:
        pass

    _write(
        request_path,
        {
            "schema_version": 1,
            "kind": "CapivaraPrivilegedBackupRestoreRequest",
            "command_id": command_id,
            "action": "restore",
            "instance_id": instance_id,
            "agent_id": agent_id,
            "backup_id": backup_id,
        },
    )

    try:
        unit = unit_template.format(
            command_id=command_id,
            instance_id=instance_id,
        )
    except (KeyError, ValueError) as exc:
        raise RuntimeError("invalid privileged backup restore unit template") from exc

    completed = subprocess.run(
        ["systemctl", "start", unit, "--no-pager"],
        capture_output=True,
        text=True,
        check=False,
        timeout=3600,
    )

    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if completed.returncode != 0:
            detail = (
                completed.stderr
                or completed.stdout
                or "privileged backup restore helper failed"
            )
            raise RuntimeError(detail[:2000]) from exc
        raise RuntimeError(
            f"privileged backup restore returned no valid result: {exc}"
        ) from exc

    if completed.returncode != 0 or str(result.get("status") or "") != "completed":
        detail = str(
            result.get("error")
            or completed.stderr
            or completed.stdout
            or "privileged backup restore failed"
        )
        raise RuntimeError(detail[:2000])

    if str(result.get("command_id") or "") != command_id:
        raise RuntimeError("privileged backup restore command_id mismatch")
    if str(result.get("instance_id") or "") != instance_id:
        raise RuntimeError("privileged backup restore instance_id mismatch")
    if str(result.get("agent_id") or "") != agent_id:
        raise RuntimeError("privileged backup restore agent_id mismatch")
    if str(result.get("backup_id") or "") != backup_id:
        raise RuntimeError("privileged backup restore backup_id mismatch")

    operation = result.get("operation")
    if not isinstance(operation, dict):
        raise RuntimeError("privileged backup restore returned invalid operation")
    return operation


def _restore(config, command):
    unit_template = str(
        os.environ.get("CAPIVARA_BACKUP_RESTORE_UNIT_TEMPLATE") or ""
    ).strip()
    if unit_template:
        return _restore_via_privileged_helper(
            config,
            command,
            unit_template,
        )
    return _restore_direct(config, command)


def _delete(config, command):
    # Defense in depth for retention commands already delivered to the Agent.
    # Manual deletions are intentionally separate from automatic retention.
    if (str(command.get("reason") or "").strip().lower() not in {"manual", "customer"}
            and os.environ.get("DSM_BACKUP_ALLOW_AUTOMATIC_DELETION", "").strip() != "1"):
        raise ValueError("automatic backup deletion is disabled")
    instance_id = str(command["instance_id"])
    _owned(config, instance_id)
    backup_id = str(command.get("backup_id") or "")
    try:
        artifact = _artifact(instance_id, backup_id)
    except FileNotFoundError:
        # Desired state is already satisfied. Treat retries and retention-pruned
        # artifacts as successful deletes instead of poisoning the job history.
        return {
            "backup_id": backup_id,
            "artifact_path": None,
            "already_absent": True,
        }
    artifact.unlink()
    return {
        "backup_id": backup_id,
        "artifact_path": str(artifact),
        "already_absent": False,
    }


def apply_backup_commands(
    config: dict[str, Any],
    commands: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reports = []
    for command in commands[:20]:
        command_id = _safe(command.get("command_id"))
        path = RESULT_ROOT / f"{command_id}.json"
        try:
            previous = json.loads(path.read_text()) if path.exists() else {}
        except Exception:
            previous = {}

        if previous.get("status") in {"completed", "failed"}:
            reports.append(previous)
            continue

        started = _now()
        _write(
            path,
            {
                "command_id": command_id,
                "status": "running",
                "started_at": started,
            },
        )

        try:
            action = str(command.get("action") or "create")
            if action == "create":
                detail = _create(config, command)
            elif action == "restore":
                detail = _restore(config, command)
            elif action == "delete":
                detail = _delete(config, command)
            else:
                raise ValueError("unsupported backup action")

            report = {
                "command_id": command_id,
                "instance_id": command.get("instance_id"),
                "action": action,
                "status": "completed",
                "started_at": started,
                "completed_at": _now(),
                **detail,
            }
        except Exception as exc:
            report = {
                "command_id": command_id,
                "instance_id": command.get("instance_id"),
                "action": command.get("action"),
                "status": "failed",
                "started_at": started,
                "completed_at": _now(),
                "last_error": str(exc)[:2000],
            }

        _write(path, report)
        reports.append(report)

    return reports


def backup_state():
    output = []
    paths = sorted(RESULT_ROOT.glob("*.json")) if RESULT_ROOT.exists() else []
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(value, dict):
            output.append(value)
    return output[-500:]


__all__ = ["apply_backup_commands", "backup_state"]
