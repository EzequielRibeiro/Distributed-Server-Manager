"""Safe local staging for a re-attested Minecraft Server Pack migration.

This module only verifies and extracts an already quarantined ZIP into a caller-
owned empty staging directory. It does not start/stop instances, install a
loader, project content into a live runtime, or publish Controller state.
"""
from __future__ import annotations

import hashlib
import os
import stat
import zipfile
from pathlib import Path
from typing import Any, Mapping

from minecraft_serverpack_agent import (
    prepare_serverpack_payload,
    validate_extracted_serverpack,
)

_MAX_ENTRIES = 12000
_MAX_EXPANDED = 8 * 1024 * 1024 * 1024


class MinecraftServerPackMigrationStagingError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise MinecraftServerPackMigrationStagingError(
                "staged Server Pack contains an unsafe filesystem entry"
            )
        if path.is_dir():
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(_sha256(path)))
    return digest.hexdigest()


def _safe_zip_member(name: str) -> None:
    text = str(name or "").replace("\\", "/")
    relative = Path(text)
    if (
        not text
        or text.startswith("/")
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise MinecraftServerPackMigrationStagingError(
            "Server Pack ZIP contains an unsafe path"
        )


def stage_serverpack_archive(
    archive: Path,
    stage_root: Path,
    migration: Mapping[str, Any],
) -> dict[str, Any]:
    archive = Path(archive)
    stage_root = Path(stage_root)
    if (
        not archive.is_file()
        or archive.is_symlink()
        or archive.stat().st_size != int(migration.get("archive_size_bytes") or 0)
        or _sha256(archive) != str(migration.get("archive_sha256") or "").lower()
    ):
        raise MinecraftServerPackMigrationStagingError(
            "quarantined Server Pack does not match migration evidence"
        )
    if stage_root.is_symlink():
        raise MinecraftServerPackMigrationStagingError(
            "Server Pack staging root cannot be a symlink"
        )
    stage_root.mkdir(parents=True, exist_ok=True)
    if any(stage_root.iterdir()):
        raise MinecraftServerPackMigrationStagingError(
            "Server Pack staging root must be empty"
        )
    if not zipfile.is_zipfile(archive):
        raise MinecraftServerPackMigrationStagingError(
            "Server Pack migration requires a ZIP archive"
        )

    artifact = {
        "serverpack_v1": True,
        "serverpack_prefix": str(migration.get("serverpack_prefix") or ""),
        "serverpack_mod_count": int(migration.get("serverpack_mod_count") or 0),
        "serverpack_override_dirs": list(
            migration.get("serverpack_override_dirs") or []
        ),
    }
    expanded = 0
    try:
        with zipfile.ZipFile(archive) as package:
            entries = package.infolist()
            if not entries or len(entries) > _MAX_ENTRIES:
                raise MinecraftServerPackMigrationStagingError(
                    "Server Pack ZIP has an invalid number of entries"
                )
            for info in entries:
                _safe_zip_member(info.filename)
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise MinecraftServerPackMigrationStagingError(
                        "Server Pack ZIP contains a symbolic link"
                    )
                expanded += max(0, int(info.file_size or 0))
                if expanded > _MAX_EXPANDED:
                    raise MinecraftServerPackMigrationStagingError(
                        "Server Pack ZIP exceeds expanded safety limit"
                    )
            package.extractall(stage_root)
        prepared = prepare_serverpack_payload(stage_root, artifact)
        validated = validate_extracted_serverpack(stage_root, artifact)
    except MinecraftServerPackMigrationStagingError:
        raise
    except Exception as exc:
        raise MinecraftServerPackMigrationStagingError(str(exc)) from exc

    return {
        "kind": "MinecraftServerPackMigrationStaging",
        "archive_sha256": str(migration.get("archive_sha256") or "").lower(),
        "archive_size_bytes": archive.stat().st_size,
        "expanded_bytes": expanded,
        "mods": int(validated["mods"]),
        "override_dirs": list(prepared.get("override_dirs") or []),
        "tree_sha256": _tree_sha256(stage_root),
        "stage_root": str(stage_root),
        "executable_projection": False,
    }


__all__ = [
    "MinecraftServerPackMigrationStagingError",
    "stage_serverpack_archive",
]
