from __future__ import annotations

import importlib.util
import os
import stat
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "agents/linux/privileged/materialize_instance.py"


def load_module():
    catalog = types.ModuleType("catalog_runtime_policy")
    catalog.materialize_network_properties = lambda spec: []
    catalog.materialize_templates = lambda spec: []
    materializers = types.ModuleType("materializers")
    materializers.resolve_materializer = lambda spec: None
    runtime_spec = types.ModuleType("runtime_spec")
    runtime_spec.validate_runtime_spec = lambda spec, expected_agent_id=None: spec
    with mock.patch.dict(sys.modules, {
        "catalog_runtime_policy": catalog,
        "materializers": materializers,
        "runtime_spec": runtime_spec,
    }):
        spec = importlib.util.spec_from_file_location("capivara_materialize_instance_test", SOURCE)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module


class RuntimeUserReconciliationTest(unittest.TestCase):
    def test_missing_default_runtime_user_is_created_as_system_nologin(self):
        module = load_module()
        group = types.SimpleNamespace(gr_gid=983, gr_name="capivara-agent")
        account = types.SimpleNamespace(pw_gid=983)
        with mock.patch.object(module.grp, "getgrnam", return_value=group), \
             mock.patch.object(module.pwd, "getpwnam", side_effect=[KeyError("missing"), account]), \
             mock.patch.object(module.subprocess, "run", return_value=types.SimpleNamespace(returncode=0, stdout="", stderr="")) as run:
            module._ensure_runtime_user("capivara-instance")
        run.assert_called_once_with([
            "useradd", "--system", "--gid", "capivara-agent",
            "--home-dir", "/nonexistent", "--no-create-home",
            "--shell", "/usr/sbin/nologin", "capivara-instance",
        ], capture_output=True, text=True, check=False, timeout=30)

    def test_unknown_custom_runtime_user_is_not_created(self):
        module = load_module()
        group = types.SimpleNamespace(gr_gid=983, gr_name="capivara-agent")
        with mock.patch.object(module.grp, "getgrnam", return_value=group), \
             mock.patch.object(module.pwd, "getpwnam", side_effect=KeyError("missing")), \
             mock.patch.object(module.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "runtime user does not exist"):
                module._ensure_runtime_user("customer-selected-user")
        run.assert_not_called()

    def test_runtime_gets_only_traverse_to_state_and_read_execute_to_game_data(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "capivara-agent"
            game_data = state / "game-data"
            working = game_data / "dayz" / "serverfiles"
            working.mkdir(parents=True)
            for path in (state, game_data, game_data / "dayz", working):
                os.chmod(path, 0o700)
            module.STATE_DIR = state
            group = types.SimpleNamespace(gr_gid=os.getgid(), gr_name="capivara-agent")
            with mock.patch.object(module.grp, "getgrnam", return_value=group), \
                 mock.patch.object(module.os, "chown"):
                module._grant_runtime_access(str(working), "capivara-instance")
            self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o710)
            self.assertEqual(stat.S_IMODE(game_data.stat().st_mode), 0o750)
            self.assertEqual(stat.S_IMODE((game_data / "dayz").stat().st_mode), 0o750)
            self.assertEqual(stat.S_IMODE(working.stat().st_mode), 0o750)

    def test_non_game_data_path_permissions_are_not_relaxed(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "capivara-agent"
            state.mkdir()
            outside = Path(temporary) / "outside"
            outside.mkdir()
            os.chmod(state, 0o700)
            os.chmod(outside, 0o700)
            module.STATE_DIR = state
            group = types.SimpleNamespace(gr_gid=os.getgid(), gr_name="capivara-agent")
            with mock.patch.object(module.grp, "getgrnam", return_value=group), \
                 mock.patch.object(module.os, "chown"):
                module._grant_runtime_access(str(outside), "capivara-instance")
            self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o700)


if __name__ == "__main__":
    unittest.main()
