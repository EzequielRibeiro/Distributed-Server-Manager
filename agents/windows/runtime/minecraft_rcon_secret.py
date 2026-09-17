#!/usr/bin/env python3
"""Agent-owned Minecraft Java RCON credential."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from runtime_secret_store import (
    RuntimeSecretError,
    credential_path,
    put_secret,
)


class MinecraftRconSecretError(RuntimeError):
    pass


_SECRET_NAME = "minecraft_rcon_password"


def secret_ref(instance_id: str) -> str:
    return f"instance/{instance_id}/{_SECRET_NAME}"


def ensure_password(spec: dict[str, Any]) -> str:
    if str(spec.get("game_id") or "").lower() != "minecraft":
        raise MinecraftRconSecretError(
            "Minecraft RCON secret cannot be used by another game"
        )

    environment_id = str(
        spec.get("environment_id") or ""
    ).lower()

    if not environment_id.startswith("minecraft.java."):
        raise MinecraftRconSecretError(
            "Minecraft RCON secret requires a Java runtime"
        )

    instance_id = str(spec.get("instance_id") or "").strip()
    ref = secret_ref(instance_id)

    try:
        path = credential_path(
            ref,
            expected_instance_id=instance_id,
            require_present=False,
        )

        if path.exists():
            value = path.read_text(
                encoding="utf-8",
            ).strip()

            if len(value) < 32:
                raise MinecraftRconSecretError(
                    "Minecraft RCON secret is invalid"
                )

            return value

        value = secrets.token_urlsafe(32)

        put_secret(
            ref,
            value,
            expected_instance_id=instance_id,
        )

        return value

    except RuntimeSecretError as exc:
        raise MinecraftRconSecretError(
            str(exc)
        ) from exc


def materialize_password(spec: dict[str, Any]) -> bool:
    password = ensure_password(spec)

    root = Path(
        str(
            spec.get("configuration_root")
            or spec.get("working_directory")
            or ""
        )
    ).resolve()

    properties = (root / "server.properties").resolve()

    try:
        properties.relative_to(root)
    except ValueError as exc:
        raise MinecraftRconSecretError(
            "server.properties escapes configuration root"
        ) from exc

    if properties.is_symlink():
        raise MinecraftRconSecretError(
            "server.properties cannot be a symlink"
        )

    text = (
        properties.read_text(
            encoding="utf-8",
            errors="replace",
        )
        if properties.exists()
        else ""
    )

    lines = text.splitlines()
    output: list[str] = []
    replaced = False

    for line in lines:
        if line.strip().startswith("rcon.password="):
            if not replaced:
                output.append(f"rcon.password={password}")
                replaced = True
            continue
        output.append(line)

    if not replaced:
        output.append(f"rcon.password={password}")

    updated = "\n".join(output) + "\n"

    if updated == text:
        return False

    properties.parent.mkdir(parents=True, exist_ok=True)

    properties.write_text(
        updated,
        encoding="utf-8",
    )

    return True


def read_password(spec: dict[str, Any]) -> str:
    instance_id = str(spec.get("instance_id") or "").strip()

    try:
        path = credential_path(
            secret_ref(instance_id),
            expected_instance_id=instance_id,
            require_present=True,
        )
        value = path.read_text(
            encoding="utf-8",
        ).strip()
    except (OSError, RuntimeSecretError) as exc:
        raise MinecraftRconSecretError(
            "Minecraft RCON secret is unavailable"
        ) from exc

    if len(value) < 32:
        raise MinecraftRconSecretError(
            "Minecraft RCON secret is invalid"
        )

    return value


__all__ = [
    "MinecraftRconSecretError",
    "ensure_password",
    "materialize_password",
    "read_password",
    "secret_ref",
]
