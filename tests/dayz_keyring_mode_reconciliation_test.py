#!/usr/bin/env python3
"""Regression: a reused DayZ keyring must stay readable by the game account."""
from __future__ import annotations

import hashlib
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents/linux/runtime"))

from content_activation_dayz import materialize_dayz_keyring


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_reuse_repairs_private_legacy_modes_without_replacing_live_mount(tmp_path):
    state = tmp_path / "instance"
    state.mkdir()
    working = tmp_path / "serverfiles"
    keys = working / "keys"
    keys.mkdir(parents=True)
    vanilla = keys / "dayz.bikey"
    vanilla.write_bytes(b"vanilla public test key")
    mod_key = state / "content" / "VPP.bikey"
    mod_key.parent.mkdir(parents=True)
    mod_key.write_bytes(b"VPP public test key")
    keyring = state / ".dsm" / "dayz-keys"
    spec = {
        "game_id": "dayz",
        "instance_state_root": str(state),
        "working_directory": str(working),
        "content_dayz_key_sources": [{
            "source": str(mod_key),
            "name": "VPP.bikey",
            "sha256": hashlib.sha256(mod_key.read_bytes()).hexdigest(),
        }],
    }

    original_umask = os.umask(0o077)
    try:
        materialize_dayz_keyring(spec)
    finally:
        os.umask(original_umask)

    assert _mode(keyring) == 0o755
    assert {_mode(keyring / name) for name in ("dayz.bikey", "VPP.bikey")} == {0o644}

    before_dir_ino = keyring.stat().st_ino
    before_file_inos = [(keyring / name).stat().st_ino for name in ("dayz.bikey", "VPP.bikey")]
    os.chmod(keyring, 0o700)
    os.chmod(keyring / "dayz.bikey", 0o600)
    os.chmod(keyring / "VPP.bikey", 0o600)

    materialize_dayz_keyring(spec)

    assert _mode(keyring) == 0o755
    assert {_mode(keyring / name) for name in ("dayz.bikey", "VPP.bikey")} == {0o644}
    assert keyring.stat().st_ino == before_dir_ino
    assert [(keyring / name).stat().st_ino for name in ("dayz.bikey", "VPP.bikey")] == before_file_inos
    assert (keyring / "dayz.bikey").read_bytes() == vanilla.read_bytes()
    assert (keyring / "VPP.bikey").read_bytes() == mod_key.read_bytes()
