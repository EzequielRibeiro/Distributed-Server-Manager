"""Agent-local private runtime secret store for Windows."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
_SECRET = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_MAX_SECRET_BYTES = 64 * 1024

PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))


class RuntimeSecretError(ValueError):
    pass


def secret_root() -> Path:
    return Path(
        os.environ.get(
            "CAPIVARA_RUNTIME_SECRET_ROOT",
            PROGRAM_DATA / "CapivaraAgent" / "runtime-secrets",
        )
    )


def _instance(value: Any) -> str:
    text = str(value or "").strip()
    if not _TOKEN.fullmatch(text):
        raise RuntimeSecretError("invalid instance_id")
    return text


def parse_secret_ref(
    ref: Any,
    *,
    expected_instance_id: str | None = None,
) -> tuple[str, str]:
    text = str(ref or "").strip()
    parts = text.split("/")

    if len(parts) != 3 or parts[0] != "instance":
        raise RuntimeSecretError("invalid secret reference")

    instance_id = _instance(parts[1])
    secret_name = parts[2]

    if not _SECRET.fullmatch(secret_name):
        raise RuntimeSecretError("invalid secret name")

    if (
        expected_instance_id is not None
        and instance_id != _instance(expected_instance_id)
    ):
        raise RuntimeSecretError(
            "secret reference belongs to another instance"
        )

    return instance_id, secret_name


def _is_link(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        checker = getattr(path, "is_junction", None)
        return bool(checker and checker())
    except OSError:
        return True


def _secure_acl(path: Path) -> None:
    if os.name != "nt":
        # Unit tests on non-Windows runners cannot enforce NTFS ACLs.
        return

    commands = [
        [
            "icacls.exe",
            str(path),
            "/inheritance:r",
        ],
        [
            "icacls.exe",
            str(path),
            "/grant:r",
            "SYSTEM:(F)",
            "*S-1-5-32-544:(F)",
        ],
    ]

    for command in commands:
        cp = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
            creationflags=getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0,
            ),
        )

        if cp.returncode != 0:
            detail = (
                cp.stderr
                or cp.stdout
                or "icacls failed"
            )[:2000]

            raise RuntimeSecretError(
                f"failed to secure runtime secret ACL: {detail}"
            )


def _directory(instance_id: str) -> Path:
    root = secret_root()

    if _is_link(root):
        raise RuntimeSecretError(
            "runtime secret root must not be a link or junction"
        )

    root.mkdir(parents=True, exist_ok=True)
    _secure_acl(root)

    directory = root / _instance(instance_id)

    if _is_link(directory):
        raise RuntimeSecretError(
            "runtime secret directory must not be a link or junction"
        )

    directory.mkdir(exist_ok=True)
    _secure_acl(directory)

    return directory


def credential_path(
    ref: Any,
    *,
    expected_instance_id: str | None = None,
    require_present: bool = True,
) -> Path:
    instance_id, secret_name = parse_secret_ref(
        ref,
        expected_instance_id=expected_instance_id,
    )

    path = secret_root() / instance_id / secret_name

    if _is_link(path):
        raise RuntimeSecretError(
            "runtime secret must not be a link or junction"
        )

    if require_present and not path.is_file():
        raise RuntimeSecretError(
            "runtime secret is not materialized"
        )

    return path


def put_secret(
    ref: Any,
    value: str | bytes,
    *,
    expected_instance_id: str | None = None,
) -> dict[str, Any]:
    instance_id, secret_name = parse_secret_ref(
        ref,
        expected_instance_id=expected_instance_id,
    )

    data = (
        value.encode("utf-8")
        if isinstance(value, str)
        else bytes(value)
    )

    if not data or len(data) > _MAX_SECRET_BYTES:
        raise RuntimeSecretError(
            "runtime secret size is invalid"
        )

    directory = _directory(instance_id)
    destination = directory / secret_name

    if _is_link(destination):
        raise RuntimeSecretError(
            "runtime secret must not replace a link or junction"
        )

    fd, temporary = tempfile.mkstemp(
        prefix=f".{secret_name}.",
        dir=str(directory),
    )

    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary, destination)
        _secure_acl(destination)

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


__all__ = [
    "RuntimeSecretError",
    "credential_path",
    "parse_secret_ref",
    "put_secret",
    "secret_root",
]
