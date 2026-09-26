"""Agent-side serverpack projection: data only; no shell/script execution."""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Mapping

_CONFIG_DIRS = frozenset({
    "config", "defaultconfigs", "kubejs", "global_packs", "openloader",
    "crafttweaker", "scripts", "ftbquests", "resources",
})
_FORBIDDEN = frozenset({".jar", ".exe", ".dll", ".so", ".dylib", ".bat", ".cmd", ".ps1", ".sh"})


def verify_installed_neoforge(instance_root: Path, expected: str) -> dict[str, str]:
    """Read authoritative instance-local NeoForge library and launcher metadata.

    Refuse imports when the installed loader cannot be determined. Neither ZIP
    filenames nor customer metadata substitute for local runtime evidence.
    """
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}(?:[-+][A-Za-z0-9.-]+)?", str(expected or "")):
        raise ValueError("Server Pack requires an exact NeoForge build")
    root=Path(instance_root)
    roots=[root,root/"game-data"]
    proofs=[]
    found=False
    for runtime in roots:
        libs=runtime/"libraries"/"net"/"neoforged"/"neoforge"
        if libs.is_symlink():
            raise ValueError("NeoForge library directory must not be a symbolic link")
        if not libs.is_dir():continue
        versions=sorted(d.name for d in libs.iterdir() if d.is_dir() and not d.is_symlink())
        if not versions:continue
        found=True
        if expected not in versions:
            raise ValueError(f"Installed NeoForge build differs from Server Pack: expected {expected}.")
        args=runtime/"capivara-launch.args"
        if not args.is_file() or args.is_symlink():
            raise ValueError("Instance-local NeoForge launcher metadata is missing.")
        if args.stat().st_size>32768:
            raise ValueError("NeoForge launcher metadata is unexpectedly large")
        raw=args.read_text(encoding="utf-8")
        used=set(re.findall(r"neoforge[/\\]([0-9A-Za-z.+-]+)[/\\](?:unix_args|win_args)\.txt",raw))
        if used!={expected}:
            raise ValueError("Active launcher does not prove the exact NeoForge build.")
        candidate=libs/expected
        if not (candidate/"unix_args.txt").is_file() and not (candidate/"win_args.txt").is_file():
            raise ValueError("NeoForge launcher arguments for the exact build are missing")
        proofs.append(str(candidate))
    if not found or not proofs:
        raise ValueError("Unable to verify the installed NeoForge build in the instance; Server Pack import blocked.")
    return {"loader":"neoforge","loader_version":expected,"evidence":"instance-local-launcher"}


def prepare_serverpack_payload(payload: Path, artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Restructure only approved content into existing safe Agent projections.

    Unselected launcher scripts remain inert in managed content; they are never
    executed or projected into the instance root. The ordinary Agent scanner
    still inspects the source ZIP and extracted payload before activation.
    """
    if artifact.get("serverpack_v1") is not True:
        raise ValueError("serverpack attestation is missing")
    raw_prefix = str(artifact.get("serverpack_prefix") or "")
    if raw_prefix:
        prefix = raw_prefix.rstrip("/")
        if ("/" in prefix or "\\" in prefix or prefix in {"", ".", ".."}
                or not all(c.isalnum() or c in "-_." for c in prefix)):
            raise ValueError("invalid serverpack wrapper")
        source = payload / prefix
        if source.is_symlink() or not source.is_dir():
            raise ValueError("Server Pack wrapper is missing")
        for item in sorted(source.iterdir()):
            target = payload / item.name
            if target.exists():
                raise ValueError("Server Pack wrapper conflicts with an existing file")
            shutil.move(str(item), str(target))
        source.rmdir()
    mods = payload / "mods"
    if not mods.is_dir() or mods.is_symlink():
        raise ValueError("Server Pack is missing a regular mods directory")
    jars = sorted(mods.iterdir())
    if (not jars or len(jars) > 1500 or
            any(item.is_symlink() or not item.is_file() or item.suffix.lower() != ".jar" for item in jars)):
        raise ValueError("Server Pack contains an invalid mods directory")
    expected_count = int(artifact.get("serverpack_mod_count") or 0)
    if expected_count != len(jars):
        raise ValueError("Server Pack mod count does not match the Controller inspection")
    roots = artifact.get("serverpack_override_dirs")
    if not isinstance(roots, list) or len(roots) > 8 or len(roots) != len(set(roots)):
        raise ValueError("invalid Server Pack override contract")
    if any(name not in _CONFIG_DIRS for name in roots):
        raise ValueError("Server Pack requests an unknown override directory")
    for name in roots:
        directory = payload / name
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("Server Pack override directory is missing")
        for file in directory.rglob("*"):
            if file.is_symlink():
                raise ValueError("Server Pack configuration contains symbolic links")
            if file.is_file() and file.suffix.lower() in _FORBIDDEN:
                raise ValueError("Server Pack configuration contains a protected executable")
    override = payload / "server-overrides"
    if override.exists() or override.is_symlink():
        raise ValueError("Server Pack contains a reserved directory")
    if roots:
        override.mkdir()
        for root in roots:
            shutil.move(str(payload / root), str(override / root))
    return {"mods": len(jars), "override_dirs": list(roots)}


def validate_extracted_serverpack(root: Path, artifact: Mapping[str, Any]) -> dict[str, Any]:
    if artifact.get("serverpack_v1") is not True:
        raise ValueError("Server Pack validation contract missing")
    mods = root / "mods"
    if mods.is_symlink() or not mods.is_dir():
        raise ValueError("Server Pack managed mods are missing")
    files = list(mods.iterdir())
    if len(files) != int(artifact.get("serverpack_mod_count") or 0):
        raise ValueError("Server Pack managed mod count mismatch")
    if any(file.is_symlink() or not file.is_file() or file.suffix.lower() != ".jar" for file in files):
        raise ValueError("Server Pack contains invalid managed mods")
    expected = artifact.get("serverpack_override_dirs")
    override = root / "server-overrides"
    if expected and (override.is_symlink() or not override.is_dir()):
        raise ValueError("Server Pack overrides are missing")
    for name in expected or []:
        directory = override / name
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Server Pack declared overrides are missing")
    return {"validator": "minecraft-serverpack-v1", "mods": len(files)}


__all__ = ["prepare_serverpack_payload", "validate_extracted_serverpack", "verify_installed_neoforge"]
