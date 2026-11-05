"""DayZ DLC ownership policy: staging preflight and privileged materialization."""
import importlib.util
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents/linux/runtime"))
from dayz_dlc_ownership import discover_dayz_dlc_paths
from server_update_agent import _validate_dayz_staged_dlc, ServerUpdateError

PRIVILEGED = ROOT / "agents/linux/privileged/materialize_instance.py"


@pytest.fixture
def install(tmp_path):
    root = tmp_path / "state" / "game-data" / "dayz" / "serverfiles"
    root.mkdir(parents=True)
    for name in ("nasdara", "sakhal", "future_dlc"):
        addons = root / name / "addons"
        addons.mkdir(parents=True)
        (addons / (name + ".pbo")).write_bytes(b"PBO")
    mod = root / "@mod" / "addons"
    mod.mkdir(parents=True)
    (mod / "custom.pbo").write_bytes(b"PBO")
    custom = root / "custom" / "addons"
    custom.mkdir(parents=True)
    (root / "custom" / "mod.cpp").write_text("custom")
    (custom / "custom.pbo").write_bytes(b"PBO")
    base = root / "addons"
    base.mkdir()
    (base / "game.pbo").write_bytes(b"PBO")
    return root


def load_materializer():
    spec = importlib.util.spec_from_file_location("dayz_dlc_materializer_test", PRIVILEGED)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generic_future_dlc_detected(install):
    paths = set(discover_dayz_dlc_paths(install))
    for name in ("nasdara", "sakhal", "future_dlc"):
        assert install / name / "addons" / (name + ".pbo") in paths
    assert not any("@mod" in path.parts or "custom" in path.parts for path in paths)
    assert install / "addons" not in paths


def test_preflight_never_calls_chown(install):
    with mock.patch("os.chown") as chown:
        _validate_dayz_staged_dlc(install, "dayz")
        _validate_dayz_staged_dlc(install, "minecraft")
        chown.assert_not_called()


def test_symlink_rejected_prior_to_changes(install, tmp_path):
    (install / "future_dlc" / "addons" / "escape").symlink_to(tmp_path)
    with pytest.raises(ServerUpdateError, match="unsafe"):
        _validate_dayz_staged_dlc(install, "dayz")


def test_privileged_normalizer_corrects_existing_and_new(install):
    materializer = load_materializer()
    materializer.STATE_DIR = install.parents[2]
    spec = {"game_id": "dayz", "working_directory": str(install), "user": "capivara-instance"}
    owner = types.SimpleNamespace(pw_uid=995)
    group = types.SimpleNamespace(gr_gid=987)
    calls = []
    with mock.patch.object(materializer, "_validate_runtime_user", return_value=owner), \
         mock.patch.object(materializer.grp, "getgrnam", return_value=group), \
         mock.patch.object(materializer.os, "chown", side_effect=lambda path, uid, gid, **kw: calls.append((Path(path), uid, gid, kw))):
        changed = materializer._normalize_dayz_dlc_ownership(spec)
    assert changed >= 3
    assert len(calls) == changed
    assert all((uid, gid, kw["follow_symlinks"]) == (995, 987, False) for _,uid,gid,kw in calls)
    assert not any("@mod" in path.parts or "custom" in path.parts for path,_,_,_ in calls)


def test_privileged_normalizer_ignores_non_dayz(install):
    materializer = load_materializer()
    assert materializer._normalize_dayz_dlc_ownership({"game_id": "minecraft", "working_directory": str(install)}) == 0


def test_privileged_normalizer_skips_unmanaged_paths(install, tmp_path):
    materializer = load_materializer()
    materializer.STATE_DIR = tmp_path / "different-state"
    spec = {"game_id": "dayz", "working_directory": str(install)}
    with mock.patch.object(materializer.os, "chown") as chown:
        assert materializer._normalize_dayz_dlc_ownership(spec) == 0
        chown.assert_not_called()


def test_dayz_start_invokes_privileged_repair_before_adapter_start():
    from contextlib import nullcontext
    import instance_runtime
    events = []
    record = {"instance_id": "dayz-001", "agent_id": "test-agent", "game_id": "dayz"}
    adapter = types.SimpleNamespace(
        name="mock-dayz",
        start=lambda spec: (events.append("adapter-start") or {"state": {"running": True}}),
    )
    with mock.patch("runtime_operations.runtime_operation", return_value=nullcontext()), \
         mock.patch("runtime_limits.runtime_limits", return_value=types.SimpleNamespace(lock_timeout_seconds=1)), \
         mock.patch.object(instance_runtime, "_owned", return_value=record), \
         mock.patch.object(instance_runtime, "resolve_adapter", return_value=adapter), \
         mock.patch.object(instance_runtime, "register_instance"), \
         mock.patch("runtime_metrics.increment"), \
         mock.patch("privileged_materialization.repair_dayz_dlc_ownership", side_effect=lambda config, spec: events.append("owner-repair")):
        instance_runtime.lifecycle({"agent_id": "test-agent"}, "dayz-001", "start")
    assert events == ["owner-repair", "adapter-start"]


def test_privileged_materializer_exposes_dayz_repair_action():
    materializer = PRIVILEGED.read_text()
    assert 'elif action == "repair-dayz-dlc-ownership":' in materializer
    assert 'updated = _normalize_dayz_dlc_ownership(spec)' in materializer
    bridge = (ROOT / "agents/linux/runtime/privileged_materialization.py").read_text()
    assert '_invoke("repair-dayz-dlc-ownership", normalized)' in bridge
