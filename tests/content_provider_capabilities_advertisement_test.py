#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_capabilities(relative_path: str, module_name: str):
    profiles = types.ModuleType("profiles")
    registry = types.ModuleType("profiles.registry")
    registry.supported_profiles = lambda: ()
    profiles.registry = registry
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    with patch.dict(sys.modules, {"profiles": profiles, "profiles.registry": registry}):
        spec.loader.exec_module(module)
    return module


class ContentProviderCapabilitiesAdvertisementTest(unittest.TestCase):
    def test_linux_workshop_is_advertised_only_when_steamcmd_is_functional(self):
        module = load_capabilities(
            "agents/linux/runtime/capabilities.py", "linux_content_capabilities_test"
        )
        missing = {
            "installed": False,
            "functional": False,
            "state": "missing",
            "runtime_32bit": True,
        }
        ready = {
            "installed": True,
            "functional": True,
            "state": "ready",
            "runtime_32bit": True,
        }
        with patch.object(module, "_steamcmd_status", return_value=missing), patch.object(
            module, "_java_status", return_value={"functional": False}
        ), patch.object(module.shutil, "which", return_value=None):
            capabilities = module.detect_capabilities()
        self.assertNotIn("steam", capabilities["content_providers"])
        self.assertNotIn("steam-workshop", capabilities["content_providers"])

        with patch.object(module, "_steamcmd_status", return_value=ready), patch.object(
            module, "_java_status", return_value={"functional": False}
        ), patch.object(module.shutil, "which", return_value=None):
            capabilities = module.detect_capabilities()
        self.assertIn("steam", capabilities["content_providers"])
        self.assertIn("steam-workshop", capabilities["content_providers"])

    def test_windows_workshop_is_advertised_only_when_steamcmd_exists(self):
        module = load_capabilities(
            "agents/windows/runtime/capabilities.py", "windows_content_capabilities_test"
        )
        with patch.object(module, "_java_status", return_value={"functional": False}), patch.object(
            module, "_managed_steamcmd"
        ) as managed, patch.object(module.shutil, "which", return_value=None):
            managed.return_value = Path("Z:/definitely-missing/steamcmd.exe")
            capabilities = module.detect_capabilities()
        self.assertNotIn("steam", capabilities["content_providers"])
        self.assertNotIn("steam-workshop", capabilities["content_providers"])

        with patch.object(module, "_java_status", return_value={"functional": False}), patch.object(
            module, "_managed_steamcmd"
        ) as managed, patch.object(module.shutil, "which", side_effect=lambda name: "C:/steamcmd.exe" if name == "steamcmd.exe" else None):
            managed.return_value = Path("Z:/definitely-missing/steamcmd.exe")
            capabilities = module.detect_capabilities()
        self.assertIn("steam", capabilities["content_providers"])
        self.assertIn("steam-workshop", capabilities["content_providers"])


if __name__ == "__main__":
    unittest.main()
