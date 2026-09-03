#!/usr/bin/env python3
from __future__ import annotations

import unittest

from core.runtime_engine_contract import (
    RuntimeEngineContractError,
    canonical_from_runtime_v2,
    supports_agent,
    validate_runtime_engine_contract,
)


class RuntimeEngineContractTest(unittest.TestCase):
    def test_java_runtime_normalizes_without_linux_install_path(self):
        legacy = {
            "schema_version": 2,
            "kind": "RuntimeDefinition",
            "id": "minecraft.paper",
            "game": "minecraft",
            "edition": "java",
            "variant": "paper",
            "version": {"strategy": "dynamic", "resolver": "paper"},
            "process": {
                "engine": "java",
                "executable": "server.jar",
                "artifact_mode": "file",
                "args": ["-jar", "server.jar", "nogui"],
            },
            "requirements": {
                "os": ["linux", "windows"],
                "architectures": ["x86_64"],
                "java": {"min": 21},
            },
            "artifact": {"provider": "http"},
            "installation": {"directory": "/srv/capivara/minecraft"},
        }

        contract = canonical_from_runtime_v2(legacy)
        self.assertEqual(contract["runtime"]["id"], "minecraft.paper")
        self.assertEqual(contract["engine"]["id"], "java")
        self.assertEqual(contract["engine"]["kind"], "java")
        self.assertEqual(contract["engine"]["requirements"]["java"]["min"], 21)
        self.assertNotIn("installation", contract)
        self.assertNotIn("directory", contract)
        self.assertTrue(supports_agent(contract, os_name="linux", architecture="x86_64"))
        self.assertTrue(supports_agent(contract, os_name="windows", architecture="x86_64"))

    def test_native_windows_runtime_is_platform_portable(self):
        legacy = {
            "schema_version": 2,
            "kind": "RuntimeDefinition",
            "id": "example.native",
            "game": "example",
            "edition": "default",
            "variant": "stable",
            "version": {"strategy": "static", "value": "1"},
            "process": {
                "engine": "native",
                "executable": "server.exe",
                "artifact_mode": "executable",
                "args": ["--server"],
            },
            "requirements": {
                "os": ["windows"],
                "architectures": ["x86_64"],
            },
            "artifact": {"provider": "steam", "package_id": "123"},
            "installation": {"directory": "/legacy/linux/path-is-not-semantic"},
        }

        contract = canonical_from_runtime_v2(legacy)
        self.assertEqual(contract["engine"]["id"], "native")
        self.assertEqual(contract["engine"]["kind"], "native")
        self.assertEqual(contract["artifact"]["provider"], "steam")
        self.assertEqual(contract["launch"]["executable"], "server.exe")
        self.assertTrue(supports_agent(contract, os_name="windows", architecture="x86_64"))
        self.assertFalse(supports_agent(contract, os_name="linux", architecture="x86_64"))

    def test_artifact_provider_is_not_promoted_to_engine(self):
        legacy = {
            "schema_version": 2,
            "kind": "RuntimeDefinition",
            "id": "dayz.stable",
            "game": "dayz",
            "edition": "default",
            "variant": "stable",
            "version": {"strategy": "static", "value": "current"},
            "process": {"engine": "native", "executable": "DayZServer_x64"},
            "requirements": {"os": ["linux"], "architectures": ["x86_64"]},
            "artifact": {"provider": "steam", "package_id": "223350"},
            "installation": {"directory": "/opt/dayz"},
        }
        contract = canonical_from_runtime_v2(legacy)
        self.assertEqual(contract["artifact"]["provider"], "steam")
        self.assertEqual(contract["engine"]["id"], "native")
        self.assertNotEqual(contract["engine"]["id"], "steam")
        self.assertNotEqual(contract["engine"]["id"], "steamcmd")

    def test_canonical_contract_rejects_installation_layout(self):
        contract = {
            "contract_version": 1,
            "kind": "RuntimeEngineContract",
            "runtime": {
                "id": "minecraft.paper",
                "game": "minecraft",
                "edition": "java",
                "variant": "paper",
                "version": {"strategy": "dynamic"},
            },
            "engine": {
                "id": "java",
                "kind": "java",
                "requirements": {"os": ["linux"], "architectures": ["x86_64"]},
            },
            "launch": {"executable": "server.jar"},
            "installation": {"directory": "/opt/server"},
        }
        with self.assertRaises(RuntimeEngineContractError):
            validate_runtime_engine_contract(contract)


if __name__ == "__main__":
    unittest.main()
