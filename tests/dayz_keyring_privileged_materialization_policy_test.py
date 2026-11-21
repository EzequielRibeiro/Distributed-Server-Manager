#!/usr/bin/env python3
"""Regression: privileged DayZ materialization must not undo live key/mod access."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
for part in ("agents/linux/runtime", "agents/linux/privileged"):
    path = str(ROOT / part)
    if path not in sys.path:
        sys.path.insert(0, path)

import materialize_instance


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_privileged_apply_preserves_agent_keyring_owner_modes_and_inode(tmp_path):
    storage = tmp_path / "pool"
    state = storage / "cli-000001-dayz-002"
    keyring = state / ".dsm" / "dayz-keys"
    keyring.mkdir(parents=True)
    key = keyring / "dayz.bikey"
    key.write_bytes(b"public test key")
    private = state / ".dsm" / "private.json"
    private.write_bytes(b"private")
    keyring.chmod(0o700)
    key.chmod(0o600)
    private.chmod(0o644)
    working = tmp_path / "serverfiles"
    working.mkdir()
    spec = {
        "instance_id": state.name,
        "game_id": "dayz",
        "instance_state_root": str(state),
        "working_directory": str(working),
        "seed_files": [],
        "seed_directories": [],
        "writable_directories": [],
        "bind_paths": [
            {"source": str(keyring), "target": str(working / "keys")},
        ],
    }
    runtime_account = SimpleNamespace(pw_uid=os.getuid() + 1111, pw_gid=os.getgid() + 1111)
    agent_account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
    agent_group = SimpleNamespace(gr_gid=os.getgid())
    directory_inode = keyring.stat().st_ino
    file_inode = key.stat().st_ino

    with mock.patch.object(materialize_instance.os, "chown") as chown, \
         mock.patch.object(materialize_instance.os, "fchown"), \
         mock.patch.object(materialize_instance.pwd, "getpwnam", return_value=agent_account), \
         mock.patch.object(materialize_instance.grp, "getgrnam", return_value=agent_group):
        for _ in range(2):
            materialize_instance._prepare_private_state(spec, runtime_account, storage)

    assert _mode(keyring) == 0o755
    assert _mode(key) == 0o644
    assert _mode(state / ".dsm") == 0o700
    assert _mode(private) == 0o600
    assert keyring.stat().st_ino == directory_inode
    assert key.stat().st_ino == file_inode
    assert key.read_bytes() == b"public test key"
    chown.assert_any_call(keyring, agent_account.pw_uid, agent_group.gr_gid)
    assert not any(
        call.args[0] == keyring and call.args[1] == runtime_account.pw_uid
        for call in chown.call_args_list
    )


def _mod_spec(tmp_path: Path) -> tuple[dict, Path, Path]:
    working = tmp_path / "serverfiles"
    working.mkdir()
    state = tmp_path / "instances" / "cli-000001-dayz-002"
    source = state / "content" / "workshop" / "steam-workshop:2289456201"
    source.mkdir(parents=True)
    alias = f"@dsm-{state.name}-2289456201"
    spec = {
        "instance_id": state.name,
        "game_id": "dayz",
        "instance_state_root": str(state),
        "working_directory": str(working),
        "content_dayz_mod_aliases": [{
            "alias": alias,
            "source": str(source),
            "target": str(working / alias),
        }],
    }
    return spec, source, working / alias


def test_dayz_workshop_addons_case_alias_is_safe_and_idempotent(tmp_path):
    spec, source, runtime_alias = _mod_spec(tmp_path)
    addons = source / "Addons"
    addons.mkdir()
    pbo = addons / "ns.pbo"
    pbo.write_bytes(b"original mod PBO")
    original_inode = pbo.stat().st_ino

    first = materialize_instance._sync_dayz_mod_aliases(spec)
    second = materialize_instance._sync_dayz_mod_aliases(spec)

    assert (source / "addons").is_symlink()
    assert os.readlink(source / "addons") == "Addons"
    assert runtime_alias.is_symlink()
    assert (runtime_alias / "addons" / "ns.pbo").read_bytes() == b"original mod PBO"
    assert pbo.stat().st_ino == original_inode
    assert first[0]["changed"] is True
    assert second[0]["changed"] is False


def test_dayz_workshop_rejects_unsafe_preexisting_addons_link(tmp_path):
    spec, source, runtime_alias = _mod_spec(tmp_path)
    (source / "Addons").mkdir()
    (source / "addons").symlink_to(tmp_path, target_is_directory=True)

    with pytest.raises(RuntimeError, match="unsafe DayZ addons case alias"):
        materialize_instance._sync_dayz_mod_aliases(spec)
    assert not runtime_alias.exists()


def test_dayz_workshop_keeps_existing_lowercase_addons(tmp_path):
    spec, source, runtime_alias = _mod_spec(tmp_path)
    addons = source / "addons"
    addons.mkdir()
    pbo = addons / "test.pbo"
    pbo.write_bytes(b"unchanged")
    materialize_instance._sync_dayz_mod_aliases(spec)

    assert addons.is_dir() and not addons.is_symlink()
    assert pbo.read_bytes() == b"unchanged"
    assert runtime_alias.is_symlink()
