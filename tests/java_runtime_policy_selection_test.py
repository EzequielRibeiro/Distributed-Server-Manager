#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LINUX_RUNTIME = ROOT / "agents" / "linux" / "runtime"
DASHBOARD = ROOT / "dashboard"
for item in (str(ROOT), str(LINUX_RUNTIME), str(DASHBOARD)):
    if item not in sys.path:
        sys.path.insert(0, item)

catalog_policy = importlib.import_module("catalog_runtime_policy")
controller_policy = importlib.import_module("catalog_controller_runtime_policy")


class JavaRuntimePolicySelectionTest(unittest.TestCase):
    def test_jar_runtime_uses_selected_java_and_private_jar(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            provider = root / "provider"
            runtime = root / "instance" / "runtime"
            provider.mkdir(parents=True)
            runtime.mkdir(parents=True)
            spec = {
                "executable": "/usr/bin/java",
                "arguments": [],
                "working_directory": str(runtime),
                "environment": {},
            }
            context = {
                "content_root": str(provider),
                "catalog_runtime_policy": {
                    "runtime_id": "minecraft.java.youer",
                    "engine": "java",
                    "requirements": {"java": {"min": 21, "max": 21}},
                    "executable": "server.jar",
                    "arguments": ["nogui"],
                    "environment": {},
                },
            }
            with mock.patch.object(catalog_policy, "select_java_executable", return_value="/opt/jdk-21/bin/java") as select:
                result = catalog_policy.apply_policy(spec, {"instance_id": "mc-1"}, context)

            select.assert_called_once_with({"java": {"min": 21, "max": 21}})
            self.assertEqual(result["executable"], "/opt/jdk-21/bin/java")
            self.assertEqual(result["arguments"], ["-jar", str(runtime / "server.jar"), "nogui"])
            self.assertEqual(result["environment"]["JAVA_HOME"], "/opt/jdk-21")
            self.assertEqual(result["catalog_runtime_policy"]["requirements"]["java"]["max"], 21)

    def test_at_java_runtime_uses_selected_java_without_implicit_jar(self):
        spec = {
            "executable": "/usr/bin/java",
            "arguments": [],
            "working_directory": "/srv/instance/runtime",
            "environment": {},
        }
        context = {
            "content_root": "/srv/provider",
            "catalog_runtime_policy": {
                "runtime_id": "minecraft.java.neoforge",
                "engine": "java",
                "requirements": {"java": {"min": 17, "max": 25}},
                "executable": "@java",
                "arguments": ["@user_jvm_args.txt", "@capivara-launch.args", "nogui"],
                "environment": {},
            },
        }
        with mock.patch.object(catalog_policy, "select_java_executable", return_value="/opt/jdk-25/bin/java"):
            result = catalog_policy.apply_policy(spec, {"instance_id": "mc-2"}, context)
        self.assertEqual(result["executable"], "/opt/jdk-25/bin/java")
        self.assertEqual(result["arguments"][0], "@user_jvm_args.txt")
        self.assertEqual(result["environment"]["JAVA_HOME"], "/opt/jdk-25")

    def test_controller_policy_preserves_catalog_owned_java_requirements(self):
        runtime_path = ROOT / "catalog" / "v2" / "games" / "minecraft" / "runtimes" / "java-youer.json"
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td, mock.patch.dict("os.environ", {"CAPIVARA_CATALOG_POLICY_ROOT": td}):
            stored = Path(td) / "minecraft.java.youer.json"
            stored.write_text(json.dumps({
                "runtime_id": "minecraft.java.youer",
                "engine": "native",
                "requirements": {"java": {"min": 25, "max": 25}},
            }), encoding="utf-8")
            policy = controller_policy.load_policy(ROOT, runtime)
        self.assertEqual(policy["engine"], "java")
        self.assertEqual(policy["requirements"]["java"], {"min": 21, "max": 21})


if __name__ == "__main__":
    unittest.main()
