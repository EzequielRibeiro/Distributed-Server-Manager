#!/usr/bin/env python3
"""Create Factorio's private initial save and safe server settings once."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def _absolute(value: str, label: str) -> Path:
    path = Path(str(value or ""))
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    return path


def _write_settings(path: Path, name: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": name[:128],
        "description": "Managed by Capivara DSM",
        "tags": ["capivara"],
        "max_players": 0,
        "visibility": {"public": True, "lan": True},
        "username": "",
        "password": "",
        "token": "",
        "game_password": "",
        "require_user_verification": False,
        "max_upload_in_kilobytes_per_second": 0,
        "max_upload_slots": 5,
        "minimum_latency_in_ticks": 0,
        "ignore_player_limit_for_returning_players": False,
        "allow_commands": "admins-only",
        "autosave_interval": 10,
        "autosave_slots": 5,
        "afk_autokick_interval": 0,
        "auto_pause": True,
        "only_admins_can_pause_the_game": True,
        "autosave_only_on_server": True,
        "non_blocking_saving": False
    }
    fd, temporary = tempfile.mkstemp(prefix=".server-settings.", suffix=".json", dir=str(path.parent))
    os.close(fd)
    temp = Path(temporary)
    try:
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def prepare(executable: str, save: str, settings: str, name: str) -> None:
    binary = _absolute(executable, "Factorio executable")
    save_path = _absolute(save, "Factorio save")
    settings_path = _absolute(settings, "Factorio settings")
    if not binary.is_file():
        raise RuntimeError("Factorio executable is unavailable")
    _write_settings(settings_path, name)
    if save_path.exists():
        return
    save_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [str(binary), "--create", str(save_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=600,
        env=dict(os.environ),
    )
    if completed.returncode != 0 or not save_path.is_file():
        raise RuntimeError(f"Factorio initial save creation failed with exit code {completed.returncode}")
    os.chmod(save_path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", required=True)
    parser.add_argument("--save", required=True)
    parser.add_argument("--settings", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    prepare(args.executable, args.save, args.settings, args.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
