#!/usr/bin/env python3
"""Secret-safe Controller outbox for one-time Agent runtime secret delivery.

The database stores no secret value. Payload bytes live only in a private 0600
spool file until the authenticated Agent reports a final result.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
_SECRET = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_NAMESPACE = "capivara.runtime.secret"
_MAX_SECRET_BYTES = 64 * 1024


class RuntimeSecretOutboxError(ValueError):
    pass


def outbox_root() -> Path:
    configured = os.environ.get("DSM_RUNTIME_SECRET_OUTBOX")
    if configured:
        return Path(configured)
    return Path(os.environ.get("DSM_ROOT", "/opt/dsm")) / "runtime" / "secret-outbox"


def _token(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not _TOKEN.fullmatch(text):
        raise RuntimeSecretOutboxError(f"invalid {label}")
    return text


def _secret_name(value: Any) -> str:
    text = str(value or "").strip()
    if not _SECRET.fullmatch(text):
        raise RuntimeSecretOutboxError("invalid secret name")
    return text


def _private_root() -> Path:
    root = outbox_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise RuntimeSecretOutboxError("secret outbox root must not be a symlink")
    os.chmod(root, 0o700)
    return root


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, temp = tempfile.mkstemp(prefix=".runtime-secret-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        try:
            os.unlink(temp)
        except OSError:
            pass


class RuntimeSecretOutbox:
    def __init__(self, backend):
        self.backend = backend

    def _instance_agent(self, instance_id: str) -> str:
        iid = _token(instance_id, "instance_id")
        ph = "?" if self.backend.name == "sqlite" else "%s"
        with self.backend.connect() as connection:
            row = connection.execute(f"SELECT agent_id FROM instances WHERE id={ph}", (iid,)).fetchone()
        if row is None or not row["agent_id"]:
            raise KeyError(iid)
        return _token(row["agent_id"], "agent_id")

    def enqueue(self, *, instance_id: str, name: str, action: str, value: str | bytes | None = None, requested_by: str | None = None) -> dict[str, Any]:
        iid = _token(instance_id, "instance_id")
        secret_name = _secret_name(name)
        operation = str(action or "put").strip().lower()
        if operation not in {"put", "revoke"}:
            raise RuntimeSecretOutboxError("secret action must be put or revoke")
        agent_id = self._instance_agent(iid)
        data = b""
        if operation == "put":
            if value is None:
                raise RuntimeSecretOutboxError("secret value is required")
            data = value.encode("utf-8") if isinstance(value, str) else bytes(value)
            if not data or len(data) > _MAX_SECRET_BYTES:
                raise RuntimeSecretOutboxError("secret size is invalid")
        job_id = "runtime-secret-" + uuid.uuid4().hex
        root = _private_root(); metadata_path = root / f"{job_id}.json"; value_path = root / f"{job_id}.secret"
        ref = f"instance/{iid}/{secret_name}"
        metadata = {
            "schema_version": 1,
            "job_id": job_id,
            "agent_id": agent_id,
            "instance_id": iid,
            "name": secret_name,
            "ref": ref,
            "action": operation,
            "checksum": hashlib.sha256(data).hexdigest() if data else hashlib.sha256(ref.encode()).hexdigest(),
            "requested_by": str(requested_by or "")[:191] or None,
            "created_at": int(time.time()),
        }
        if operation == "put":
            _atomic(value_path, data)
        _atomic(metadata_path, (json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n").encode())
        return {k: metadata[k] for k in ("job_id", "agent_id", "instance_id", "name", "ref", "action", "created_at")}

    def _metadata(self) -> list[tuple[Path, dict[str, Any]]]:
        root = _private_root(); rows = []
        for path in root.glob("runtime-secret-*.json"):
            if path.is_symlink():
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                rows.append((path, value))
        rows.sort(key=lambda item: int(item[1].get("created_at") or 0))
        return rows

    def commands_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        aid = _token(agent_id, "agent_id"); commands = []
        for _, meta in self._metadata():
            if str(meta.get("agent_id")) != aid:
                continue
            value = {"action": meta["action"], "ref": meta["ref"]}
            if meta["action"] == "put":
                secret_path = _private_root() / f"{meta['job_id']}.secret"
                if secret_path.is_symlink() or not secret_path.is_file():
                    continue
                data = secret_path.read_bytes()
                if hashlib.sha256(data).hexdigest() != str(meta.get("checksum")):
                    continue
                value["secret_value"] = data.decode("utf-8")
            commands.append({
                "schema_version": 1,
                "kind": "CapivaraResolvedConfiguration",
                "namespace": _NAMESPACE,
                "target_type": "instance",
                "target_id": meta["instance_id"],
                "revision": meta["job_id"],
                "checksum": meta["checksum"],
                "value": value,
                "configuration_refs": [],
            })
            if len(commands) >= 10:
                break
        return commands

    def apply_reports(self, agent_id: str, reports: list[dict[str, Any]]) -> int:
        aid = _token(agent_id, "agent_id"); accepted = 0
        by_revision = {str(meta.get("job_id")): (path, meta) for path, meta in self._metadata() if str(meta.get("agent_id")) == aid}
        for report in reports[:1000]:
            if not isinstance(report, dict) or str(report.get("namespace") or "").lower() != _NAMESPACE:
                continue
            revision = str(report.get("desired_revision") or report.get("applied_revision") or "")
            item = by_revision.get(revision)
            if not item:
                continue
            path, meta = item
            if str(report.get("target_id") or "") != str(meta.get("instance_id") or ""):
                continue
            # One-time delivery: final reports always destroy the Controller copy.
            for candidate in (path, _private_root() / f"{revision}.secret"):
                try:
                    if candidate.is_symlink():
                        continue
                    candidate.unlink()
                except FileNotFoundError:
                    pass
            accepted += 1
        return accepted

    def list_pending(self, *, instance_id: str | None = None) -> list[dict[str, Any]]:
        iid = _token(instance_id, "instance_id") if instance_id is not None else None; result = []
        for _, meta in self._metadata():
            if iid is not None and str(meta.get("instance_id")) != iid:
                continue
            result.append({k: meta.get(k) for k in ("job_id", "agent_id", "instance_id", "name", "ref", "action", "created_at")})
        return result


__all__ = ["RuntimeSecretOutbox", "RuntimeSecretOutboxError", "outbox_root"]
