"""Fail-closed semantic validation for customer-uploaded game content."""
from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path(__file__).resolve().parent
COMMON_DIR = RUNTIME_DIR.parent.parent / "common"
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from dayz_community_missions import community_mission_manifest
from minecraft_serverpack_agent import validate_extracted_serverpack


class ContentSemanticValidationError(ValueError):
    pass


def _regular_files(root: Path) -> list[Path]:
    if not root.is_dir():
        raise ContentSemanticValidationError("external content payload is not a directory")
    files: list[Path] = []
    for current, directories, names in os.walk(root, followlinks=False):
        base = Path(current)
        for name in directories:
            if (base / name).is_symlink():
                raise ContentSemanticValidationError("external content payload contains a symbolic link")
        for name in names:
            value = base / name
            if value.is_symlink():
                raise ContentSemanticValidationError("external content payload contains a symbolic link")
            if value.is_file():
                files.append(value)
    if not files:
        raise ContentSemanticValidationError("external content payload is empty")
    return files


def _validate_dayz_mod(root: Path, files: list[Path]) -> dict[str, Any]:
    pbo = [item for item in files if item.suffix.casefold() == ".pbo"]
    if not pbo:
        raise ContentSemanticValidationError(
            "uploaded file is not a valid DayZ mod: no PBO content was found"
        )
    return {"validator": "dayz-mod-v1", "pbo_files": len(pbo)}


def _validate_dayz_map(root: Path) -> dict[str, Any]:
    try:
        manifest = community_mission_manifest(root)
    except ValueError as exc:
        raise ContentSemanticValidationError(str(exc)) from exc
    return {
        "validator": "dayz-community-map-v1",
        "missions": manifest["missions"],
        "mission_count": manifest["count"],
    }


def _jar_entries(path: Path) -> set[str]:
    try:
        with zipfile.ZipFile(path) as archive:
            return {str(name).replace("\\", "/").lstrip("/") for name in archive.namelist()}
    except (OSError, zipfile.BadZipFile) as exc:
        raise ContentSemanticValidationError(
            "uploaded Minecraft artifact is not a valid JAR"
        ) from exc


def _verified_neoforge_language_library(path: Path, artifact: dict[str, Any]) -> bool:
    """Allow NeoForge SPI language-library JARs only inside verified official packs.

    A signed-language-provider library is deliberately not a conventional mod:
    the SPI entry + FMLModType LIBRARY in its manifest are its metadata.
    Normal local mod uploads must still contain standard mod descriptors.
    The caller has already checked the official Server Pack parent, the
    individual member SHA-256 and the scanner's clean verdict.
    """
    if not (artifact.get("serverpack_child_v1") is True
            and artifact.get("serverpack_loader") == "neoforge"
            and artifact.get("ephemeral_upload") is True):
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            names={name.casefold():name for name in archive.namelist()}
            manifest=names.get("meta-inf/manifest.mf")
            service=names.get("meta-inf/services/net.neoforged.neoforgespi.language.imodlanguageloader")
            if not manifest or not service:
                return False
            if archive.getinfo(manifest).file_size>64*1024 or archive.getinfo(service).file_size>4096:
                return False
            lines=archive.read(manifest).decode("utf-8",errors="strict").splitlines()
            if not any(line.strip().casefold()=="fmlmodtype: library" for line in lines):
                return False
            providers=[line.strip() for line in archive.read(service).decode("utf-8",errors="strict").splitlines()
                       if line.strip() and not line.lstrip().startswith("#")]
            if len(providers)!=1:
                return False
            provider=providers[0]
            if (len(provider)>240 or any(not(part.isidentifier()) for part in provider.split("."))
                    or (provider.replace(".","/")+".class").casefold() not in names):
                return False
            return True
    except (OSError,ValueError,UnicodeError,zipfile.BadZipFile):
        return False


def _validate_minecraft(root: Path, files: list[Path], content_type: str,
                        artifact: dict[str, Any] | None = None) -> dict[str, Any]:
    if content_type == "datapack":
        manifests = [
            item for item in files
            if item.name.casefold() == "pack.mcmeta"
        ]
        if not manifests:
            raise ContentSemanticValidationError(
                "uploaded file is not a valid Minecraft datapack: pack.mcmeta was not found"
            )
        return {"validator": "minecraft-datapack-v1", "manifests": len(manifests)}

    jars = [item for item in files if item.suffix.casefold() == ".jar"]
    if len(jars) != 1:
        raise ContentSemanticValidationError(
            f"uploaded Minecraft {content_type} must contain exactly one JAR artifact"
        )
    entries = _jar_entries(jars[0])
    lowered = {entry.casefold() for entry in entries}

    if content_type == "plugin":
        markers = {"plugin.yml", "paper-plugin.yml"}
        if not lowered.intersection(markers):
            raise ContentSemanticValidationError(
                "uploaded JAR is not a recognized Minecraft plugin"
            )
        return {"validator": "minecraft-plugin-v1", "jar": jars[0].name}

    if content_type == "mod":
        markers = {
            "fabric.mod.json",
            "quilt.mod.json",
            "mcmod.info",
            "meta-inf/mods.toml",
            "meta-inf/neoforge.mods.toml",
        }
        if not lowered.intersection(markers):
            if artifact and _verified_neoforge_language_library(jars[0], artifact):
                return {"validator": "minecraft-neoforge-language-library-v1", "jar": jars[0].name}
            raise ContentSemanticValidationError(
                "uploaded JAR is not a recognized Minecraft mod"
            )
        return {"validator": "minecraft-mod-v1", "jar": jars[0].name}

    raise ContentSemanticValidationError(
        f"external Minecraft content type is not supported: {content_type or 'unknown'}"
    )


def validate_external_content_payload(
    root: Path | str,
    command: dict[str, Any],
) -> dict[str, Any]:
    artifact = command.get("artifact") if isinstance(command.get("artifact"), dict) else {}
    provider = str(command.get("provider") or artifact.get("provider") or "").strip().lower()
    payload = Path(root)
    game_id = str(command.get("game_id") or "").strip().lower()
    content_type = str(command.get("content_type") or "").strip().lower()

    # Community DayZ maps are always inspected after provider acquisition, not
    # only when they originate from a customer upload. This keeps GitHub/HTTP
    # mission sources behind the same fail-closed semantic boundary.
    if game_id == "dayz" and content_type == "map":
        return _validate_dayz_map(payload)

    if provider != "local" or artifact.get("ephemeral_upload") is not True:
        return {"validator": "not-required"}

    files = _regular_files(payload)
    if game_id == "dayz" and content_type == "mod":
        return _validate_dayz_mod(payload, files)
    if game_id == "minecraft":
        if content_type == "modpack" and artifact.get("serverpack_v1") is True:
            return validate_extracted_serverpack(payload, artifact)
        return _validate_minecraft(payload, files, content_type, artifact)

    raise ContentSemanticValidationError(
        "external upload validation is not available for this game/content type"
    )


__all__ = [
    "ContentSemanticValidationError",
    "validate_external_content_payload",
]
