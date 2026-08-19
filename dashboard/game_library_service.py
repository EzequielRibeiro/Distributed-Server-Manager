"""Agent-local game-data library inventory and provisioning helpers.

`game-data` is the Agent's reusable server-base library. Instances never execute
from this directory: provisioning/reinstall copies a validated base into the
instance's own `serverfiles` directory.
"""
from __future__ import annotations

import shutil
from pathlib import Path


def library_entry(root: Path, definition: dict, game_data: Path) -> dict:
    artifact = definition.get("artifact", {}) if isinstance(definition, dict) else {}
    process = definition.get("process", {}) if isinstance(definition, dict) else {}
    executable = str(process.get("executable") or "")
    ready = bool(game_data.is_dir() and executable and (game_data / executable).is_file())
    size = 0
    if game_data.is_dir():
        for item in game_data.rglob("*"):
            try:
                if item.is_file() and not item.is_symlink():
                    size += item.stat().st_size
            except OSError:
                pass
    return {
        "runtime_id": definition.get("id"),
        "game": definition.get("game"),
        "provider": artifact.get("provider", "configured"),
        "version": definition.get("version"),
        "path": str(game_data),
        "ready": ready,
        "size_bytes": size,
        "role": "agent_server_base_library",
    }


def provision_from_library(game_data: Path, target: Path, *, executable: str) -> dict:
    """Copy a validated Agent library base into an isolated instance directory."""
    if not game_data.is_dir():
        raise ValueError("game-data server base is not installed")
    if not executable or not (game_data / executable).is_file():
        raise ValueError("game-data server base is incomplete")
    if target.exists():
        raise ValueError("instance serverfiles already exist")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(game_data, target, symlinks=False, ignore=shutil.ignore_patterns(".dsm", "runtime"))
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    if not (target / executable).is_file():
        shutil.rmtree(target, ignore_errors=True)
        raise ValueError("provisioned instance is missing its executable")
    return {"source": str(game_data), "destination": str(target), "isolated": True}
