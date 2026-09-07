#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {relative}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LINUX = _load("capivara_linux_runtime_spec_files_root_test", "agents/linux/runtime/runtime_spec.py")
WINDOWS = _load("capivara_windows_runtime_spec_files_root_test", "agents/windows/runtime/runtime_spec.py")


class RuntimeFilesRootContractTest(unittest.TestCase):
    def _linux(self, **extra):
        raw = {
            "instance_id": "instance-one",
            "agent_id": "agent-one",
            "runtime_id": "game.stable",
            "adapter": "systemd",
            "working_directory": "/srv/shared/game",
            "executable": "/srv/shared/game/server",
            "arguments": [],
            "environment": {},
            "desired_state": "stopped",
            **extra,
        }
        return LINUX.validate_runtime_spec(raw, expected_agent_id="agent-one")

    def _windows(self, **extra):
        raw = {
            "instance_id": "instance-one",
            "agent_id": "agent-one",
            "runtime_id": "game.stable",
            "adapter": "windows-process",
            "working_directory": "/srv/shared/game",
            "executable": "/srv/shared/game/server.exe",
            "arguments": [],
            "environment": {},
            "desired_state": "stopped",
            **extra,
        }
        return WINDOWS.validate_runtime_spec(raw, expected_agent_id="agent-one")

    def test_linux_explicit_files_root_has_highest_precedence(self):
        spec = self._linux(
            files_root="/srv/customer-visible",
            instance_state_root="/srv/private-state",
            configuration_root="/srv/private-state/config",
        )
        self.assertEqual(spec["files_root"], "/srv/customer-visible")

    def test_linux_private_state_precedes_configuration_and_shared_working_directory(self):
        spec = self._linux(
            instance_state_root="/srv/private-state",
            configuration_root="/srv/private-state/config",
        )
        self.assertEqual(spec["files_root"], "/srv/private-state")
        self.assertNotEqual(spec["files_root"], spec["working_directory"])

    def test_linux_legacy_fallbacks_remain_available(self):
        configured = self._linux(configuration_root="/srv/private-config")
        shared_only = self._linux()
        self.assertEqual(configured["files_root"], "/srv/private-config")
        self.assertEqual(shared_only["files_root"], "/srv/shared/game")

    def test_windows_explicit_files_root_has_highest_precedence(self):
        spec = self._windows(
            files_root="/srv/customer-visible",
            instance_state_root="/srv/private-state",
            configuration_root="/srv/private-state/config",
        )
        self.assertEqual(spec["files_root"], "/srv/customer-visible")

    def test_windows_private_state_precedes_configuration_and_shared_working_directory(self):
        spec = self._windows(
            instance_state_root="/srv/private-state",
            configuration_root="/srv/private-state/config",
        )
        self.assertEqual(spec["files_root"], "/srv/private-state")
        self.assertNotEqual(spec["files_root"], spec["working_directory"])

    def test_windows_legacy_fallbacks_remain_available(self):
        configured = self._windows(configuration_root="/srv/private-config")
        shared_only = self._windows()
        self.assertEqual(configured["files_root"], "/srv/private-config")
        self.assertEqual(shared_only["files_root"], "/srv/shared/game")


if __name__ == "__main__":
    unittest.main()
