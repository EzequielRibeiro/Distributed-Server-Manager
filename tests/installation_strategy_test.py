from __future__ import annotations

import unittest

from core.installation_strategy import (
    InstallationStrategyError,
    resolve_agent_layout,
    strategy_from_runtime_contract,
    validate_installation_strategy,
)
from core.runtime_engine_contract import canonical_from_runtime_v2


class InstallationStrategyTest(unittest.TestCase):
    def _runtime(self, *, engine="native", provider="steam", os_values=None, artifact_mode="directory"):
        return {
            "schema_version": 2,
            "kind": "RuntimeDefinition",
            "id": "dayz.stable" if engine == "native" else "minecraft.paper",
            "game": "dayz" if engine == "native" else "minecraft",
            "edition": "default" if engine == "native" else "java",
            "variant": "stable" if engine == "native" else "paper",
            "version": {"strategy": "static", "value": "current"},
            "process": {
                "engine": engine,
                "executable": "DayZServer_x64.exe" if engine == "native" else "java",
                "artifact_mode": artifact_mode,
                "args": [],
            },
            "requirements": {
                "os": os_values or (["windows"] if engine == "native" else ["linux", "windows"]),
                "architectures": ["x86_64"],
                **({"java": {"min": 21}} if engine == "java" else {}),
            },
            "artifact": {
                "provider": provider,
                "package_id": "223350" if provider == "steam" else None,
                "url": "https://example.invalid/server.zip" if provider == "http-archive" else None,
            },
            "installation": {"directory": "/legacy/linux/path"},
        }

    def test_steam_provider_selects_steamcmd_without_changing_native_engine(self):
        contract = canonical_from_runtime_v2(self._runtime())
        strategy = strategy_from_runtime_contract(contract)
        self.assertEqual(contract["engine"]["id"], "native")
        self.assertEqual(strategy["engine_id"], "native")
        self.assertEqual(strategy["acquisition"]["provider"], "steam")
        self.assertEqual(strategy["installer"]["method"], "steamcmd")
        self.assertNotIn("/legacy/linux/path", str(strategy))

    def test_java_archive_uses_download_strategy(self):
        contract = canonical_from_runtime_v2(
            self._runtime(engine="java", provider="http-archive", artifact_mode="file")
        )
        strategy = strategy_from_runtime_contract(contract)
        self.assertEqual(strategy["engine_id"], "java")
        self.assertEqual(strategy["installer"]["method"], "download")
        self.assertEqual(strategy["layout"]["artifact_target"], "server/runtime")

    def test_linux_and_windows_physical_layout_is_agent_resolved(self):
        contract = canonical_from_runtime_v2(self._runtime(engine="java", provider="http-archive"))
        strategy = strategy_from_runtime_contract(contract)
        linux = resolve_agent_layout(strategy, instance_root="/srv/capivara/instances/i-1", os_name="linux")
        windows = resolve_agent_layout(strategy, instance_root=r"C:\Capivara\instances\i-1", os_name="windows")
        self.assertEqual(linux["working_dir"], "/srv/capivara/instances/i-1/server")
        self.assertEqual(windows["working_dir"], r"C:\Capivara\instances\i-1\server")
        self.assertNotEqual(linux["working_dir"], windows["working_dir"])

    def test_semantic_layout_rejects_absolute_and_traversal_paths(self):
        contract = canonical_from_runtime_v2(self._runtime(engine="java", provider="http-archive"))
        strategy = strategy_from_runtime_contract(contract)
        for bad in ("/srv/server", "../escape", r"C:\server"):
            broken = {**strategy, "layout": {**strategy["layout"], "working_dir": bad}}
            with self.assertRaises(InstallationStrategyError):
                validate_installation_strategy(broken)

    def test_provider_and_installer_method_must_match(self):
        contract = canonical_from_runtime_v2(self._runtime())
        strategy = strategy_from_runtime_contract(contract)
        broken = {**strategy, "installer": {"method": "download", "idempotent": True}}
        with self.assertRaises(InstallationStrategyError):
            validate_installation_strategy(broken)


if __name__ == "__main__":
    unittest.main()
