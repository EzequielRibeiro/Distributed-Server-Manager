from __future__ import annotations

import os
import pwd
import stat
from pathlib import Path

import pytest

import sys

RUNTIME = Path(__file__).resolve().parents[1] / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from materializers.base import MaterializerError
from materializers.instance_state_access import reconcile_instance_root_traversal


INSTANCE_ID = "cli-test-dayz-002"


def _fixture(tmp_path):
    parent = tmp_path / "capivara-instances"
    parent.mkdir()
    instance = parent / INSTANCE_ID
    instance.mkdir(mode=0o700)
    workshop = instance / "content" / "workshop"
    workshop.mkdir(parents=True)
    workshop.chmod(0o770)
    spec = {"instance_id": INSTANCE_ID, "user": pwd.getpwuid(os.geteuid()).pw_name}
    return parent, instance, workshop, spec


def _reconcile(parent, spec, *, apply=False):
    return reconcile_instance_root_traversal(
        spec, apply=apply, _parent=parent,
        _agent_user=pwd.getpwuid(os.geteuid()).pw_name,
    )


def test_repair_only_root_mode_and_is_idempotent(tmp_path):
    parent, root, workshop, spec = _fixture(tmp_path)
    assert _reconcile(parent, spec) == "needs_group_traverse"
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert _reconcile(parent, spec, apply=True) == "repaired"
    assert stat.S_IMODE(root.stat().st_mode) == 0o710
    assert stat.S_IMODE(workshop.stat().st_mode) == 0o770
    assert _reconcile(parent, spec, apply=True) == "already_accessible"


def test_mismatched_agent_group_refuses_repair(tmp_path, monkeypatch):
    parent, root, _, spec = _fixture(tmp_path)
    monkeypatch.setattr(os, "getgrouplist", lambda *_args: [])
    with pytest.raises(MaterializerError, match="not accessible to Agent"):
        _reconcile(parent, spec, apply=True)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700


def test_unexpected_permissions_are_not_rewritten(tmp_path):
    parent, root, _, spec = _fixture(tmp_path)
    root.chmod(0o750)
    with pytest.raises(MaterializerError, match="unexpected instance root mode"):
        _reconcile(parent, spec, apply=True)
    assert stat.S_IMODE(root.stat().st_mode) == 0o750


def test_symlink_instance_directory_is_rejected(tmp_path):
    parent = tmp_path / "capivara-instances"
    parent.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    (parent / INSTANCE_ID).symlink_to(target, target_is_directory=True)
    spec = {"instance_id": INSTANCE_ID, "user": pwd.getpwuid(os.geteuid()).pw_name}
    with pytest.raises(MaterializerError, match="safely inspect"):
        _reconcile(parent, spec, apply=True)
    assert stat.S_IMODE(target.stat().st_mode) != 0o710


def test_custom_roots_are_not_changed(tmp_path):
    parent, root, _, spec = _fixture(tmp_path)
    spec["instance_state_root"] = "/srv/other/instance"
    assert _reconcile(parent, spec, apply=True) == "custom_root_not_modified"
    assert stat.S_IMODE(root.stat().st_mode) == 0o700


def test_nonexistent_root_is_not_created(tmp_path):
    parent = tmp_path / "capivara-instances"
    parent.mkdir()
    spec = {"instance_id": INSTANCE_ID, "user": pwd.getpwuid(os.geteuid()).pw_name}
    assert _reconcile(parent, spec, apply=True) == "not_created"
    assert not (parent / INSTANCE_ID).exists()


def test_invalid_instance_id_fails_closed(tmp_path):
    with pytest.raises(MaterializerError, match="invalid instance id"):
        _reconcile(tmp_path, {"instance_id": "../escape", "user": "root"}, apply=True)
