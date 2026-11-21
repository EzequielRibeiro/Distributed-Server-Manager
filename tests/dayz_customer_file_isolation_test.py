#!/usr/bin/env python3
"""Regression for the files_root == instance_state_root permission escalation.

Runs only in disposable tmp_path fixtures; no game host or root privileges.
"""
from __future__ import annotations

import os
import pwd
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "agents/linux/runtime", ROOT / "agents/linux/privileged"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import instance_files_client
import materialize_instance
import prepare_customer_files


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _fixture(tmp_path: Path):
    pool = tmp_path / "hybrid-instance-storage"
    root = pool / "cli-test-dayz-001"
    root.mkdir(parents=True)
    control = root / ".dsm"
    control.mkdir()
    secret = control / "content-activation-files.json"
    secret.write_text("private", encoding="utf-8")
    control.chmod(0o700)
    secret.chmod(0o600)

    config = root / "config"
    config.mkdir()
    settings = config / "serverDZ.cfg"
    settings.write_text("hostname=DayZ;", encoding="utf-8")
    settings.chmod(0o600)

    workshop = root / "content" / "workshop"
    workshop.mkdir(parents=True)
    package = workshop / "cf.pbo"
    package.write_bytes(b"managed-content")
    for directory in (workshop.parent, workshop):
        directory.chmod(0o750)
    package.chmod(0o640)

    battleye = root / "battleye"
    battleye.mkdir()
    (battleye / "rcon_password.txt").write_text("secret", encoding="utf-8")
    battleye.chmod(0o700)

    unknown = root / "unknown-private"
    unknown.mkdir()
    unknown.chmod(0o700)
    root.chmod(0o770)  # Exactly the observed, over-permissive pre-fix mode.
    return root, control, secret, config, settings, workshop, package, battleye, unknown


def _spec(root: Path):
    return {
        "instance_id": root.name,
        "instance_state_root": str(root),
        "files_root": str(root),
        "game_id": "dayz",
        "user": pwd.getpwuid(os.geteuid()).pw_name,
    }


def test_materializer_repairs_root_without_reopening_control_or_managed_content(tmp_path):
    root, control, secret, config, settings, workshop, package, battleye, unknown = _fixture(tmp_path)
    account = pwd.getpwuid(os.geteuid())
    group = SimpleNamespace(gr_gid=os.getegid())
    with mock.patch.object(materialize_instance, "_validate_runtime_user", return_value=account), \
         mock.patch.object(materialize_instance.grp, "getgrnam", return_value=group):
        materialize_instance._grant_customer_files_access(_spec(root))
        assert mode(root) == 0o710
        assert mode(control) == 0o700
        assert mode(secret) == 0o600
        assert mode(config) == 0o770
        assert mode(settings) == 0o660
        assert mode(workshop.parent) == 0o750
        assert mode(workshop) == 0o750
        assert mode(package) == 0o640
        assert mode(battleye) == 0o700
        assert mode(unknown) == 0o700
        materialize_instance._grant_customer_files_access(_spec(root))
        assert mode(root) == 0o710
        assert mode(control) == 0o700


def test_virtual_root_lists_only_explicit_directories_and_blocks_private_paths(tmp_path):
    root, control, secret, config, settings, workshop, package, battleye, unknown = _fixture(tmp_path)
    record = {**_spec(root), "agent_id": "agent-test"}
    root.chmod(0o710)  # Group may traverse, but cannot list the physical root.
    with mock.patch.object(instance_files_client, "_owned", return_value=record):
        listing = instance_files_client.execute(
            {"agent_id": "agent-test"},
            {"instance_id": root.name, "action": "list", "path": "."},
        )
        names = {entry["name"] for entry in listing["entries"]}
        assert names == {"config", "content"}
        assert listing["usage_bytes"] >= len(settings.read_bytes()) + len(package.read_bytes())
        assert "battleye" not in names
        assert ".dsm" not in names

        child_list = instance_files_client.execute(
            {"agent_id": "agent-test"},
            {"instance_id": root.name, "action": "list", "path": "config"},
        )
        assert [item["name"] for item in child_list["entries"]] == ["serverDZ.cfg"]
        original = instance_files_client.execute(
            {"agent_id": "agent-test"},
            {"instance_id": root.name, "action": "read_text", "path": "config/serverDZ.cfg"},
        )
        assert original["content"] == "hostname=DayZ;"
        saved = instance_files_client.execute(
            {"agent_id": "agent-test"},
            {"instance_id": root.name, "action": "write_text", "path": "config/serverDZ.cfg",
             "payload": {"content": "hostname=Approved;"}},
        )
        assert saved["saved"] is True
        assert settings.read_text(encoding="utf-8") == "hostname=Approved;"

        for action, path in (
            ("list", ".dsm"),
            ("read_text", ".dsm/content-activation-files.json"),
            ("read_text", "battleye/rcon_password.txt"),
            ("list", "unknown-private"),
            ("write_text", "new.txt"),
            ("delete", "config"),
            ("rename", "config"),
            ("delete", "content/workshop/cf.pbo"),
        ):
            with pytest.raises(PermissionError):
                instance_files_client.execute(
                    {"agent_id": "agent-test"},
                    {"instance_id": root.name, "action": action, "path": path},
                )


def test_symlink_in_allowlisted_subtree_fails_closed(tmp_path):
    root, *rest = _fixture(tmp_path)
    external = tmp_path / "outside"
    external.mkdir()
    (root / "profiles").symlink_to(external, target_is_directory=True)
    account = pwd.getpwuid(os.geteuid())
    group = SimpleNamespace(gr_gid=os.getegid())
    with mock.patch.object(materialize_instance, "_validate_runtime_user", return_value=account), \
         mock.patch.object(materialize_instance.grp, "getgrnam", return_value=group):
        with pytest.raises(RuntimeError, match="cannot be a symlink"):
            materialize_instance._grant_customer_files_access(_spec(root))
    assert mode(external) == 0o755


def test_foreign_owner_rejected_for_customer_writable_tree(tmp_path):
    root, *rest = _fixture(tmp_path)
    account = pwd.getpwuid(os.geteuid())
    group = SimpleNamespace(gr_gid=os.getegid())
    foreign = SimpleNamespace(pw_uid=account.pw_uid + 1)
    with mock.patch.object(materialize_instance, "_validate_runtime_user", return_value=foreign), \
         mock.patch.object(materialize_instance.grp, "getgrnam", return_value=group):
        with pytest.raises(RuntimeError, match="identity mismatch"):
            materialize_instance._grant_customer_files_access(_spec(root))
    assert mode(root) == 0o770


def test_alternate_customer_files_root_cannot_target_private_control(tmp_path):
    root, control, secret, *rest = _fixture(tmp_path)
    spec = {**_spec(root), "files_root": str(control)}
    account = pwd.getpwuid(os.geteuid())
    group = SimpleNamespace(gr_gid=os.getegid())
    with mock.patch.object(materialize_instance, "_validate_runtime_user", return_value=account), \
         mock.patch.object(materialize_instance.grp, "getgrnam", return_value=group):
        with pytest.raises(RuntimeError, match="must match instance state root"):
            materialize_instance._grant_customer_files_access(spec)
    assert mode(root) == 0o770
    assert mode(control) == 0o700
    assert mode(secret) == 0o600

    record = {**spec, "agent_id": "agent-test"}
    with mock.patch.object(instance_files_client, "_owned", return_value=record):
        with pytest.raises(PermissionError, match="differs from private instance state"):
            instance_files_client.execute(
                {"agent_id": "agent-test"},
                {"instance_id": root.name, "action": "list", "path": "."},
            )


def test_privileged_customer_files_helper_repairs_only_dayz_visible_tree(tmp_path):
    """Production-facing helper cannot chmod the private DayZ root to 0770."""
    root, control, secret, config, settings, workshop, package, battleye, unknown = _fixture(tmp_path)
    missions = root / "mpmissions"
    hardcore = missions / "hardcore.namalsk"
    hardcore.mkdir(parents=True)
    xml = hardcore / "cfgeconomycore.xml"
    xml.write_text("<root/>", encoding="utf-8")
    missions.chmod(0o755)
    hardcore.chmod(0o755)
    xml.chmod(0o644)

    record = {**_spec(root), "agent_id": "agent-test"}
    agent_config = tmp_path / "agent.json"
    agent_config.write_text('{"agent_id": "agent-test"}', encoding="utf-8")
    account = pwd.getpwuid(os.geteuid())
    group = SimpleNamespace(gr_gid=os.getegid())

    with mock.patch.object(prepare_customer_files, "CONFIG_PATH", agent_config), \
         mock.patch.object(prepare_customer_files, "_owned_record", return_value=record), \
         mock.patch.object(prepare_customer_files.os, "geteuid", return_value=0), \
         mock.patch.object(materialize_instance, "_validate_runtime_user", return_value=account), \
         mock.patch.object(materialize_instance.grp, "getgrnam", return_value=group):
        result = prepare_customer_files.run(root.name)

    assert result["scope"] == "dayz-customer-visible-only"
    assert result["root_mode"] == "0710"
    assert mode(root) == 0o710
    assert mode(missions) == 0o770
    assert mode(hardcore) == 0o770
    assert mode(xml) == 0o660
    assert mode(control) == 0o700
    assert mode(secret) == 0o600
    assert mode(workshop) == 0o750
    assert mode(package) == 0o640
    assert mode(battleye) == 0o700
    assert mode(unknown) == 0o700


def test_privileged_customer_files_helper_rejects_dayz_alternate_root(tmp_path):
    root, control, secret, *_ = _fixture(tmp_path)
    record = {**_spec(root), "agent_id": "agent-test", "files_root": str(control)}
    agent_config = tmp_path / "agent.json"
    agent_config.write_text('{"agent_id": "agent-test"}', encoding="utf-8")
    with mock.patch.object(prepare_customer_files, "CONFIG_PATH", agent_config), \
         mock.patch.object(prepare_customer_files, "_owned_record", return_value=record), \
         mock.patch.object(prepare_customer_files.os, "geteuid", return_value=0):
        with pytest.raises(RuntimeError, match="must match private state"):
            prepare_customer_files.run(root.name)
    assert mode(root) == 0o770
    assert mode(control) == 0o700
    assert mode(secret) == 0o600
