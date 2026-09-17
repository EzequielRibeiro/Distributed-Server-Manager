#!/usr/bin/env python3
"""Agent-owned Palworld REST administrator credential.

The credential is generated locally, persisted only inside private instance
control state, and materialized into PalWorldSettings.ini. It is never sourced
from Controller/browser payloads and is never returned to the Controller.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any


class PalworldAdminSecretError(RuntimeError):
    pass


def _state_root(spec: dict[str, Any]) -> Path:
    raw = str(spec.get("instance_state_root") or "").strip()
    path = Path(raw)

    if not raw or not path.is_absolute():
        raise PalworldAdminSecretError(
            "Palworld instance has no trusted instance_state_root"
        )

    return path.resolve()


def _secret_path(spec: dict[str, Any]) -> Path:
    root = _state_root(spec)
    control = (root / ".dsm").resolve()

    try:
        control.relative_to(root)
    except ValueError as exc:
        raise PalworldAdminSecretError(
            "Palworld control state escapes instance storage"
        ) from exc

    return control / "palworld-admin-password"


def ensure_admin_password(spec: dict[str, Any]) -> str:
    if str(spec.get("game_id") or "").strip().lower() != "palworld":
        raise PalworldAdminSecretError(
            "Palworld admin secret cannot be used by another game"
        )

    path = _secret_path(spec)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.is_symlink():
        raise PalworldAdminSecretError(
            "Palworld admin secret path cannot be a symlink"
        )

    if path.exists():
        if not path.is_file():
            raise PalworldAdminSecretError(
                "Palworld admin secret path is not a regular file"
            )

        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise PalworldAdminSecretError(
                "Palworld admin secret cannot be read"
            ) from exc

        if len(value) < 32:
            raise PalworldAdminSecretError(
                "Palworld admin secret is invalid"
            )

        try:
            os.chmod(path, 0o600)
        except OSError as exc:
            raise PalworldAdminSecretError(
                "Palworld admin secret permissions cannot be secured"
            ) from exc

        return value

    value = secrets.token_urlsafe(32)

    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.tmp"
    )

    try:
        temporary.write_text(value + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass

        raise PalworldAdminSecretError(
            "Palworld admin secret cannot be persisted"
        ) from exc

    return value


__all__ = [
    "PalworldAdminSecretError",
    "ensure_admin_password",
]


def materialize_admin_password(spec: dict[str, Any]) -> bool:
    password = ensure_admin_password(spec)

    configuration_root = Path(
        str(spec.get("configuration_root") or "")
    ).resolve()

    state_root = _state_root(spec)

    try:
        configuration_root.relative_to(state_root)
    except ValueError as exc:
        raise PalworldAdminSecretError(
            "Palworld configuration root escapes instance storage"
        ) from exc

    settings = (
        configuration_root / "PalWorldSettings.ini"
    ).resolve()

    try:
        settings.relative_to(configuration_root)
    except ValueError as exc:
        raise PalworldAdminSecretError(
            "Palworld settings path escapes configuration root"
        ) from exc

    if settings.is_symlink():
        raise PalworldAdminSecretError(
            "Palworld settings cannot be a symlink"
        )

    if not settings.is_file():
        raise PalworldAdminSecretError(
            "PalWorldSettings.ini is unavailable"
        )

    try:
        text = settings.read_text(
            encoding="utf-8",
            errors="strict",
        )
    except OSError as exc:
        raise PalworldAdminSecretError(
            "PalWorldSettings.ini cannot be read"
        ) from exc

    import re

    escaped = password.replace("\\", "\\\\").replace('"', '\\"')

    pattern = re.compile(
        r'(?<![A-Za-z0-9_])AdminPassword\s*=\s*'
        r'(?:"(?:\\.|[^"])*"|[^,)]*)'
    )

    replacement = f'AdminPassword="{escaped}"'

    if pattern.search(text):
        updated = pattern.sub(
            lambda _match: replacement,
            text,
            count=1,
        )
    else:
        marker = "OptionSettings=("

        position = text.find(marker)
        if position < 0:
            raise PalworldAdminSecretError(
                "PalWorldSettings.ini has no OptionSettings block"
            )

        position += len(marker)
        updated = (
            text[:position]
            + replacement
            + ","
            + text[position:]
        )

    if updated == text:
        return False

    original = settings.stat()
    original_mode = original.st_mode & 0o777

    temporary = settings.with_name(
        f".{settings.name}.{os.getpid()}.tmp"
    )

    try:
        temporary.write_text(updated, encoding="utf-8")
        os.chown(
            temporary,
            original.st_uid,
            original.st_gid,
        )
        os.chmod(
            temporary,
            original_mode or 0o600,
        )
        os.replace(temporary, settings)
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass

        raise PalworldAdminSecretError(
            "Palworld AdminPassword cannot be materialized"
        ) from exc

    return True


__all__.append("materialize_admin_password")
