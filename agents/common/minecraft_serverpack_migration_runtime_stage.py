"""Build an isolated candidate Minecraft runtime for a Server Pack migration.

The active instance tree is copied to a caller-owned staging directory. Only
provider-owned NeoForge runtime files and the managed mods directory are
replaced. Existing worlds, server.properties, configs, KubeJS data and all
other instance-private files remain byte-identical. The result is never made
active by this module.
"""
from __future__ import annotations

import errno
import hashlib
import os
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
_REPLACED_TOP_LEVEL = frozenset((*_LOADER_PATHS, "mods", "config", "kubejs"))


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


def _copy_preserving_identity(source: str, destination: str) -> str:
    """Copy private runtime file metadata including its owning UID/GID.

    shutil.copy2 retains contents, modes and xattrs, but not ownership.
    The destination is always a new, already symlink-validated candidate.
    """
    copied = shutil.copy2(source, destination)
    st = os.stat(source, follow_symlinks=False)
    os.chown(destination, st.st_uid, st.st_gid, follow_symlinks=False)
    return copied


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



def _inherit_runtime_access(source: Path, target: Path) -> None:
    """Carry instance owner and POSIX ACL to new pack-owned files.

    Never grant global write access. Failure to apply the existing ACL fails
    staging closed rather than deploying an unreadable/unwritable candidate.
    """
    st = source.stat()
    os.chown(target, st.st_uid, st.st_gid)
    try:
        acl = os.getxattr(source, "system.posix_acl_access")
    except OSError as exc:
        if exc.errno not in (errno.ENODATA,):
            raise
    else:
        os.setxattr(target, "system.posix_acl_access", acl)
    # For a newly created file inherited from a directory, remove execute
    # bits without removing the service-user ACL write grant.
    if target.is_file() and source.is_dir():
        # Remove execute permission while retaining the named-user ACL mask.
        # The ACL is inherited from a directory that may allow execution.
        current = target.stat().st_mode
        os.chmod(target, current & ~0o111)
        if "system.posix_acl_access" in os.listxattr(target):
            os.setxattr(target, "system.posix_acl_access", acl)


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
        shutil.copytree(active_runtime, destination, copy_function=_copy_preserving_identity)
        # copytree/copy2 do not preserve directory ownership either. Restore
        # it only on the isolated candidate, never on the active instance.
        for source_dir in (active_runtime, *(p for p in active_runtime.rglob("*") if p.is_dir())):
            relative = source_dir.relative_to(active_runtime)
            target_dir = destination / relative
            st = source_dir.stat()
            os.chown(target_dir, st.st_uid, st.st_gid)
        for name in (*_LOADER_PATHS, "mods"):
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
        # Keep the instance's existing mods-directory access policy. The ZIP
        # staging tree is not authoritative for customer runtime permissions.
        shutil.copystat(active_runtime / "mods", destination / "mods")
        # Approved Server Pack overrides replace incompatible modpack-owned
        # scripts/configurations, while world and instance settings stay intact.
        override_root = serverpack_stage / "server-overrides"
        for name in ("config", "kubejs"):
            source = override_root / name
            if not source.exists():
                continue
            if source.is_symlink() or not source.is_dir():
                raise MinecraftServerPackRuntimeStageError("invalid Server Pack override directory")
            target = destination / name
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                raise MinecraftServerPackRuntimeStageError("invalid existing override destination")
            shutil.copytree(source, target, copy_function=shutil.copy2)
            if (active_runtime / name).is_dir():
                shutil.copystat(active_runtime / name, target)
                original = active_runtime / name
                for item in sorted(target.rglob("*")):
                    relative = item.relative_to(target)
                    counterpart = original / relative
                    if counterpart.exists() and counterpart.is_dir() == item.is_dir():
                        policy = counterpart
                    else:
                        parent = original / relative.parent
                        while not parent.is_dir() and parent != original:
                            parent = parent.parent
                        policy = parent
                    _inherit_runtime_access(policy, item)
                _inherit_runtime_access(original, target)
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
        "existing_config_preserved": not any((serverpack_stage / "server-overrides" / name).is_dir() for name in ("config", "kubejs")),
        "world_preserved": True,
        "activated": False,
    }


__all__ = [
    "MinecraftServerPackRuntimeStageError",
    "build_staged_runtime",
]
