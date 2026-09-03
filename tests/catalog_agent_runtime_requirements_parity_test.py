#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CATALOG_RUNTIMES = ROOT / "catalog/v2/games"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LINUX = _load(ROOT / "agents/linux/runtime/capabilities.py", "capivara_linux_capabilities_p0c")
WINDOWS = _load(ROOT / "agents/windows/runtime/capabilities.py", "capivara_windows_capabilities_p0c")


class CatalogAgentRuntimeRequirementsParityTest(unittest.TestCase):
    def test_agents_normalize_catalog_architecture_vocabulary(self):
        aliases = {
            "x86_64": "x86_64",
            "AMD64": "x86_64",
            "aarch64": "aarch64",
            "ARM64": "aarch64",
            "i686": "x86_32",
            "x86": "x86_32",
        }
        for raw, expected in aliases.items():
            self.assertEqual(LINUX._normalize_architecture(raw), expected)
            self.assertEqual(WINDOWS._normalize_architecture(raw), expected)

    def test_agents_parse_java_major_versions_equally(self):
        versions = {"1.8.0_402": 8, "17.0.12": 17, "21.0.8": 21, "25": 25}
        for version, expected in versions.items():
            self.assertEqual(LINUX._java_major(version), expected)
            self.assertEqual(WINDOWS._java_major(version), expected)

    def test_java_status_exposes_major_version_on_both_agents(self):
        completed = mock.Mock(returncode=0, stdout='openjdk version "21.0.8" 2026-07-15\n')
        with (
            mock.patch.object(LINUX.shutil, "which", return_value="/usr/bin/java"),
            mock.patch.object(LINUX.subprocess, "run", return_value=completed),
        ):
            linux = LINUX._java_status()
        with (
            mock.patch.object(WINDOWS.shutil, "which", side_effect=lambda name: r"C:\Java\bin\java.exe" if name == "java.exe" else None),
            mock.patch.object(WINDOWS.subprocess, "run", return_value=completed),
        ):
            windows = WINDOWS._java_status()
        for status in (linux, windows):
            self.assertTrue(status["installed"])
            self.assertTrue(status["functional"])
            self.assertEqual(status["state"], "ready")
            self.assertEqual(status["major"], 21)

    def test_published_runtime_requirements_are_agent_expressible(self):
        supported_os = {"linux", "windows"}
        supported_architectures = {"x86_64", "aarch64", "x86_32"}
        supported_engines = {"native", "java"}
        seen = 0
        for path in sorted(CATALOG_RUNTIMES.glob("*/runtimes/*.json")):
            runtime = json.loads(path.read_text(encoding="utf-8"))
            if runtime.get("kind") != "RuntimeDefinition":
                continue
            seen += 1
            engine = str((runtime.get("process") or {}).get("engine") or "")
            requirements = runtime.get("requirements") or {}
            os_values = set(requirements.get("os") or [])
            architectures = set(requirements.get("architectures") or [])
            self.assertIn(engine, supported_engines, path.as_posix())
            self.assertTrue(os_values, path.as_posix())
            self.assertTrue(os_values <= supported_os, path.as_posix())
            self.assertTrue(architectures, path.as_posix())
            self.assertTrue(architectures <= supported_architectures, path.as_posix())
            java = requirements.get("java")
            if engine == "java":
                self.assertIsInstance(java, dict, path.as_posix())
                self.assertIsInstance(java.get("min"), int, path.as_posix())
                if java.get("max") is not None:
                    self.assertIsInstance(java.get("max"), int, path.as_posix())
                    self.assertGreaterEqual(java["max"], java["min"], path.as_posix())
            else:
                self.assertIn(java, (None, {}), path.as_posix())
        self.assertGreaterEqual(seen, 1)

    def test_capability_contract_has_platform_and_java_status_on_both_agents(self):
        linux_source = (ROOT / "agents/linux/runtime/capabilities.py").read_text(encoding="utf-8")
        windows_source = (ROOT / "agents/windows/runtime/capabilities.py").read_text(encoding="utf-8")
        for source, os_name in ((linux_source, "linux"), (windows_source, "windows")):
            self.assertIn('"platform"', source)
            self.assertIn(f'"os": "{os_name}"' if os_name == "linux" else f'"os":"{os_name}"', source)
            self.assertIn('"architecture"', source)
            self.assertIn('"java_status"', source)
            self.assertIn('"major"', source)


if __name__ == "__main__":
    unittest.main()
