#!/usr/bin/env python3
"""P0-F gate for canonical runtime parameters and Linux/Windows parity."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from core.canonical_parameter_policy import (
    ParameterPolicyError,
    canonicalize_parameter_payload,
    normalize_arguments,
    normalize_environment,
)

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class CanonicalParameterPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.linux = _load("linux_catalog_runtime_policy_p0f", ROOT / "agents/linux/runtime/catalog_runtime_policy.py")
        cls.windows = _load("windows_catalog_runtime_policy_p0f", ROOT / "agents/windows/runtime/catalog_runtime_policy.py")
        cls.controller = _load("controller_catalog_runtime_policy_p0f", ROOT / "dashboard/catalog_controller_runtime_policy.py")

    def test_legacy_scalar_args_become_one_opaque_argv_element(self):
        self.assertEqual(normalize_arguments("--name=Server One"), ["--name=Server One"])

    def test_controller_default_policy_preserves_scalar_catalog_args(self):
        runtime = {
            "id": "example.stable",
            "process": {"executable": "server", "args": "--name=Server One"},
            "network": {"apply": []},
        }
        policy = self.controller.default_policy(runtime)
        self.assertEqual(policy["arguments"], ["--name=Server One"])

    def test_aliases_are_ingress_only(self):
        result = canonicalize_parameter_payload({"args": ["--port=2302"], "env": {"JAVA_HOME": "/java"}})
        self.assertEqual(result["arguments"], ["--port=2302"])
        self.assertEqual(result["environment"], {"JAVA_HOME": "/java"})
        self.assertNotIn("args", result)
        self.assertNotIn("env", result)

    def test_invalid_argument_and_environment_controls_are_rejected(self):
        with self.assertRaises(ParameterPolicyError):
            normalize_arguments(["ok\nsecond-command"])
        with self.assertRaises(ParameterPolicyError):
            normalize_environment({"BAD-NAME": "value"})
        with self.assertRaises(ParameterPolicyError):
            normalize_environment({"GOOD_NAME": "value\rnext"})

    def test_linux_and_windows_apply_identical_argument_environment_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = str(Path(tmp) / "server")
            spec = {
                "executable": executable,
                "working_directory": tmp,
                "arguments": ["--required", "-port=2302"],
                "environment": {"BASE": "1"},
            }
            instance = {"instance_id": "instance-1", "game_id": "game"}
            context = {
                "content_root": tmp,
                "variables": {"NAME": "Capivara"},
                "runtime_variables": {"EXTRA": "value"},
                "ports": {"game": {"port": 2302}},
                "catalog_runtime_policy": {
                    "runtime_id": "game.stable",
                    "arguments": ["-port={{PORT_GAME}}", "--name={{NAME}}", "--extra=${EXTRA}"],
                    "environment": {"SERVER_NAME": "{{NAME}}", "EXTRA_VALUE": "${EXTRA}"},
                    "variables": [],
                },
            }
            linux = self.linux.apply_policy(spec, instance, context)
            windows = self.windows.apply_policy(spec, instance, context)
            self.assertEqual(linux["arguments"], windows["arguments"])
            self.assertEqual(linux["environment"], windows["environment"])
            self.assertEqual(linux["arguments"], ["--required", "-port=2302", "--name=Capivara", "--extra=value"])
            self.assertEqual(linux["environment"], {"BASE": "1", "SERVER_NAME": "Capivara", "EXTRA_VALUE": "value"})

    def test_published_catalog_runtime_args_are_canonicalizable(self):
        runtime_root = ROOT / "catalog/v2/games"
        found = 0
        for path in runtime_root.glob("*/runtimes/*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            process = payload.get("process") if isinstance(payload.get("process"), dict) else {}
            canonical = normalize_arguments(process.get("args"))
            self.assertIsInstance(canonical, list, path.as_posix())
            self.assertTrue(all(isinstance(item, str) for item in canonical), path.as_posix())
            found += 1
        self.assertGreater(found, 0)

    def test_controller_provisioning_canonicalizes_before_agent_transport(self):
        source = (ROOT / "dashboard/catalog_provisioning_resolver.py").read_text(encoding="utf-8")
        self.assertIn("canonicalize_parameter_payload(load_policy(root, runtime))", source)
        self.assertIn('config["canonical_parameter_policy"]', source)
        self.assertIn('config["catalog_runtime_policy"] = policy', source)


if __name__ == "__main__":
    unittest.main()
