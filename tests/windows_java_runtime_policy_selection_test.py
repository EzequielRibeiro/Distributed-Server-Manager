#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "agents" / "windows" / "runtime" / "catalog_runtime_policy.py"
spec = importlib.util.spec_from_file_location("windows_java_runtime_policy_selection", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class WindowsJavaRuntimePolicySelectionTest(unittest.TestCase):
    def test_youer_jar_uses_compatible_java(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td).resolve() / "runtime"
            runtime.mkdir()
            spec_value = {
                "working_directory": str(runtime),
                "executable": "java.exe",
                "arguments": [],
                "environment": {},
            }
            context = {
                "content_root": str(Path(td).resolve() / "provider"),
                "catalog_runtime_policy": {
                    "runtime_id": "minecraft.java.youer",
                    "engine": "java",
                    "requirements": {"java": {"min": 21, "max": 21}},
                    "executable": "server.jar",
                    "arguments": ["nogui"],
                    "environment": {},
                },
            }
            with mock.patch.object(module, "select_java_executable", return_value=r"C:\Java\jdk-21\bin\java.exe"):
                result = module.apply_policy(spec_value, {"instance_id": "mc-win"}, context)
            self.assertEqual(result["executable"], r"C:\Java\jdk-21\bin\java.exe")
            self.assertEqual(result["arguments"][0], "-jar")
            self.assertTrue(result["arguments"][1].endswith("server.jar"))
            self.assertEqual(result["arguments"][-1], "nogui")
            self.assertIn("JAVA_HOME", result["environment"])


if __name__ == "__main__":
    unittest.main()
