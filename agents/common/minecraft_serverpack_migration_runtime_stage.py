"""Build an isolated candidate Minecraft runtime for a Server Pack migration.

The active instance tree is copied to a caller-owned staging directory. Only
provider-owned NeoForge runtime files and the managed mods directory are
replaced. Existing worlds, server.properties, configs, KubeJS data and all
other instance-private files remain byte-identical. The result is never made
active by this module.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from minecraft_serverpack_agent import verify_installed_neoforge

_LOADER_PATHS = (
    "libraries",
    "capivara-launch.args",
    "user_jvm_args.txt",
    "eula.txt",
    "run.sh",
    "run.bat",
)
_REPLACED_TOP_LEVEL = frozenset((*_LOADER_PATHS, "mods"))


class MinecraftServerPackRuntimeStageError(RuntimeError):
    pass


def _reject_unsafe_tree(root: Path, label: str) -> None:
    if not root.is_dir() or root.is_symlink():
        raise MinecraftServerPackRuntimeStageError(f"{label} must be a regular directory")
    for item in root.rglob("*"):
        if item.is_symlink() or (not item.is_file() and not item.is_dir()):
            raise MinecraftServerPackRuntimeStageError(
                f"{label} contains a symbolic link or special filesystem entry"
            )


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(root.rglob("*")):
        if item.is_dir():
            continue
        relative = item.relative_to(root)
        if relative.parts and relative.parts[0] in _REPLACED_TOP_LEVEL:
            continue
        encoded = relative.as_posix().encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(bytes.fromhex(_file_hash(item)))
    return digest.hexdigest()


def _copy_entry(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, copy_function=shutil.copy2)
    elif source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    else:
        raise MinecraftServerPackRuntimeStageError(
            f"required NeoForge seed entry is missing: {source.name}"
        )


def build_staged_runtime(
    *,
    active_runtime: Path,
    target_loader_seed: Path,
    serverpack_stage: Path,
    destination: Path,
    target_loader_version: str,
) -> dict[str, Any]:
    active_runtime = Path(active_runtime)
    target_loader_seed = Path(target_loader_seed)
    serverpack_stage = Path(serverpack_stage)
    destination = Path(destination)

    for root, label in (
        (active_runtime, "active runtime"),
        (target_loader_seed, "target NeoForge seed"),
        (serverpack_stage, "staged Server Pack"),
    ):
        _reject_unsafe_tree(root, label)
    if destination.exists() or destination.is_symlink():
        raise MinecraftServerPackRuntimeStageError(
            "candidate runtime destination must not already exist"
        )

    try:
        verify_installed_neoforge(target_loader_seed, target_loader_version)
    except Exception as exc:
        raise MinecraftServerPackRuntimeStageError(
            "target NeoForge seed does not prove the requested build"
        ) from exc

    mods = serverpack_stage / "mods"
    if not mods.is_dir() or mods.is_symlink():
        raise MinecraftServerPackRuntimeStageError("staged Server Pack has no safe mods directory")
    mod_files = sorted(mods.iterdir())
    if not mod_files or any(
        item.is_symlink() or not item.is_file() or item.suffix.lower() != ".jar"
        for item in mod_files
    ):
        raise MinecraftServerPackRuntimeStageError("staged Server Pack mods are invalid")

    protected_before = _protected_tree_hash(active_runtime)
    try:
        shutil.copytree(active_runtime, destination, copy_function=shutil.copy2)
        for name in _REPLACED_TOP_LEVEL:
            target = destination / name
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        for name in _LOADER_PATHS:
            source = target_loader_seed / name
            if name in {"run.sh", "run.bat"} and not source.exists():
                continue
            _copy_entry(source, destination / name)
        shutil.copytree(mods, destination / "mods", copy_function=shutil.copy2)
        _reject_unsafe_tree(destination, "candidate runtime")
        proof = verify_installed_neoforge(destination, target_loader_version)
        protected_after = _protected_tree_hash(destination)
        if protected_after != protected_before:
            raise MinecraftServerPackRuntimeStageError(
                "candidate runtime changed protected instance-private files"
            )
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise

    return {
        "kind": "MinecraftServerPackCandidateRuntime",
        "target_loader_version": target_loader_version,
        "loader_proof": proof,
        "mods": len(mod_files),
        "protected_tree_sha256": protected_after,
        "candidate_path": str(destination),
        "existing_config_preserved": True,
        "world_preserved": True,
        "activated": False,
    }


__all__ = [
    "MinecraftServerPackRuntimeStageError",
    "build_staged_runtime",
]
