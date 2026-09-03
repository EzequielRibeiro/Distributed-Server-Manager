#!/usr/bin/env python3
"""Agent-local private runtime secret store.

Secret values never belong to RuntimeSpec, systemd Environment=, argv, logs or
Controller API responses. Runtime specs carry only instance-scoped references.
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
_SECRET = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_MAX_SECRET_BYTES = 64 * 1024


class RuntimeSecretError(ValueError):
    pass


def secret_root() -> Path:
    return Path(os.environ.get("CAPIVARA_RUNTIME_SECRET_ROOT", "/var/lib/capivara-agent/runtime-secrets"))


def _instance(value: Any) -> str:
    text = str(value or "").strip()
    if not _TOKEN.fullmatch(text):
        raise RuntimeSecretError("invalid instance_id")
    return text


def parse_secret_ref(ref: Any, *, expected_instance_id: str | None = None) -> tuple[str, str]:
    text = str(ref or "").strip()
    parts = text.split("/")
    if len(parts) != 3 or parts[0] != "instance":
        raise RuntimeSecretError("invalid secret reference")
    instance_id = _instance(parts[1])
    secret_name = parts[2]
    if not _SECRET.fullmatch(secret_name):
        raise RuntimeSecretError("invalid secret name")
    if expected_instance_id is not None and instance_id != _instance(expected_instance_id):
        raise RuntimeSecretError("secret reference belongs to another instance")
    return instance_id, secret_name


def _directory(instance_id: str) -> Path:
    root = secret_root()
    directory = root / _instance(instance_id)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    if root.is_symlink():
        raise RuntimeSecretError("runtime secret root must not be a symlink")
    directory.mkdir(mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    if directory.is_symlink():
        raise RuntimeSecretError("runtime secret directory must not be a symlink")
    return directory


def credential_path(ref: Any, *, expected_instance_id: str | None = None, require_present: bool = True) -> Path:
    instance_id, secret_name = parse_secret_ref(ref, expected_instance_id=expected_instance_id)
    path = secret_root() / instance_id / secret_name
    if path.is_symlink():
        raise RuntimeSecretError("runtime secret must not be a symlink")
    if require_present and not path.is_file():
        raise RuntimeSecretError("runtime secret is not materialized")
    return path


def put_secret(ref: Any, value: str | bytes, *, expected_instance_id: str | None = None) -> dict[str, Any]:
    instance_id, secret_name = parse_secret_ref(ref, expected_instance_id=expected_instance_id)
    data = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    if not data or len(data) > _MAX_SECRET_BYTES:
        raise RuntimeSecretError("runtime secret size is invalid")
    directory = _directory(instance_id)
    destination = directory / secret_name
    if destination.is_symlink():
        raise RuntimeSecretError("runtime secret must not replace a symlink")
    fd, temporary = tempfile.mkstemp(prefix=f".{secret_name}.", dir=str(directory))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return {
        "ref": f"instance/{instance_id}/{secret_name}",
        "instance_id": instance_id,
        "name": secret_name,
        "present": True,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def revoke_secret(ref: Any, *, expected_instance_id: str | None = None) -> dict[str, Any]:
    instance_id, secret_name = parse_secret_ref(ref, expected_instance_id=expected_instance_id)
    path = credential_path(ref, expected_instance_id=instance_id, require_present=False)
    existed = False
    try:
        if path.is_symlink():
            raise RuntimeSecretError("runtime secret must not be a symlink")
        path.unlink()
        existed = True
    except FileNotFoundError:
        pass
    return {"ref": f"instance/{instance_id}/{secret_name}", "instance_id": instance_id, "name": secret_name, "present": False, "revoked": existed}


def inspect_secret(ref: Any, *, expected_instance_id: str | None = None) -> dict[str, Any]:
    instance_id, secret_name = parse_secret_ref(ref, expected_instance_id=expected_instance_id)
    path = credential_path(ref, expected_instance_id=instance_id, require_present=False)
    if not path.exists():
        return {"ref": f"instance/{instance_id}/{secret_name}", "instance_id": instance_id, "name": secret_name, "present": False}
    if path.is_symlink() or not path.is_file():
        raise RuntimeSecretError("runtime secret path is unsafe")
    stat = path.stat()
    if stat.st_mode & 0o077:
        raise RuntimeSecretError("runtime secret permissions are too broad")
    return {"ref": f"instance/{instance_id}/{secret_name}", "instance_id": instance_id, "name": secret_name, "present": True, "size_bytes": stat.st_size}


__all__ = ["RuntimeSecretError", "credential_path", "inspect_secret", "parse_secret_ref", "put_secret", "revoke_secret", "secret_root"]
