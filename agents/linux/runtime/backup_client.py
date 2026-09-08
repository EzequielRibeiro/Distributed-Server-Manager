#!/usr/bin/env python3
"""Safe local executor for Universal Smart Backup commands."""

from __future__ import annotations

import fnmatch
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

    return [path for path in candidates if not excluded(path)]


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

    if manifest is not None and (
        manifest.get("kind") != "CapivaraInstanceBackup"
        or manifest.get("backup_format") != "capivara-instance"
    ):
        raise ValueError("unsupported backup manifest")
    return manifest


def _retention(instance_dir, keep):
    archives = sorted(
        [path for path in instance_dir.glob("*.tar*") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for old in archives[max(1, int(keep)) :]:
        old.unlink(missing_ok=True)


def _create(config, command):
    instance_id = str(command["instance_id"])
    record, root = _owned(config, instance_id)
    policy = dict(command.get("policy") or {})
    consistency = str(policy.get("consistency") or "live")
    was_running = False

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
        instance_dir = BACKUP_ROOT / _safe(instance_id)
        suffix = (
            ".tar.gz"
            if str(policy.get("compression") or "gzip") == "gzip"
            else ".tar"
        )
        path = instance_dir / f"{backup_id}{suffix}"
        manifest = _manifest(record, backup_id)
        _create_archive(
            root,
            _selected(root, policy),
            path,
            str(policy.get("compression") or "gzip"),
            manifest,
        )
        size = path.stat().st_size
        sha256 = _digest(path)
        manifest["files_checksum"] = sha256
        _retention(instance_dir, int(policy.get("retention_count") or 7))
        return {
            "backup_id": backup_id,
            "artifact_path": str(path),
            "size_bytes": size,
            "sha256": sha256,
            "manifest": manifest,
        }
    finally:
        if consistency == "stopped" and was_running:
            lifecycle(config, instance_id, "start")


def _artifact(instance_id, backup_id):
    instance_dir = (BACKUP_ROOT / _safe(instance_id)).resolve()
    instance_dir.relative_to(BACKUP_ROOT)
    matches = list(instance_dir.glob(f"{_safe(backup_id)}.tar*"))
    if len(matches) != 1:
        raise FileNotFoundError("backup artifact not found")
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


def _restore_direct(config, command):
    """Restore locally when the Agent process owns the storage boundary."""
    instance_id = str(command["instance_id"])
    record, root = _owned(config, instance_id)
    artifact = _artifact(instance_id, str(command.get("backup_id") or ""))
    was_running = status(config, instance_id).get("observed_state") == "running"

    if was_running:
        lifecycle(config, instance_id, "stop")

    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{root.name}.restore-",
            dir=str(root.parent),
        )
    )
    previous = root.with_name(root.name + ".c5-previous")
    swapped = False

    try:
        manifest = _safe_extract(artifact, stage)
        _validate_manifest(record, manifest)
        manifest_path = stage / MANIFEST_NAME
        if manifest_path.exists():
            manifest_path.unlink()
        if previous.exists():
            shutil.rmtree(previous)
        os.replace(root, previous)
        os.replace(stage, root)
        swapped = True

        if was_running:
            lifecycle(config, instance_id, "start")
            after = status(config, instance_id)
            if after.get("observed_state") != "running":
                raise RuntimeError(
                    "restored server did not become healthy enough to run"
                )

        shutil.rmtree(previous, ignore_errors=True)
    except Exception:
        if swapped:
            try:
                if root.exists():
                    shutil.rmtree(root, ignore_errors=True)
                if previous.exists():
                    os.replace(previous, root)
                if was_running:
                    try:
                        lifecycle(config, instance_id, "start")
                    except Exception:
                        pass
            except Exception:
                pass
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
    instance_id = str(command["instance_id"])
    _owned(config, instance_id)
    artifact = _artifact(instance_id, str(command.get("backup_id") or ""))
    artifact.unlink()
    return {
        "backup_id": str(command.get("backup_id")),
        "artifact_path": str(artifact),
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
