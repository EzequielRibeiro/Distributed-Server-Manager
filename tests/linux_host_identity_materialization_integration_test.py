#!/usr/bin/env python3
"""Behavioral tests for canonical Linux host identity selection."""
from __future__ import annotations

import ast
import hashlib
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = ROOT / "agents/linux/runtime/agent.py"


def load_identity_runtime(host_identity_path: Path):
    """Load only the identity functions from agent.py, avoiding unrelated clients."""
    source = AGENT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(AGENT_PATH))
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"_read_text", "_host_identity"}
    ]
    if {node.name for node in selected} != {"_read_text", "_host_identity"}:
        raise AssertionError("identity functions not found in agent.py")

    module = types.ModuleType("capivara_agent_identity_test")
    module.__dict__.update(
        {
            "Path": Path,
            "hashlib": hashlib,
            "HOST_IDENTITY_PATH": host_identity_path,
        }
    )
    code = compile(
        ast.Module(body=selected, type_ignores=[]),
        filename=str(AGENT_PATH),
        mode="exec",
    )
    exec(code, module.__dict__)
    return module


class LinuxHostIdentityMaterializationIntegrationTest(unittest.TestCase):
    def test_materialized_identity_wins_over_runtime_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity_path = Path(tmp) / "host-identity"
            identity_path.write_text("sha256:canonical\n", encoding="utf-8")
            module = load_identity_runtime(identity_path)
            with mock.patch.object(module, "_read_text", wraps=module._read_text) as reader:
                self.assertEqual(module._host_identity(), "sha256:canonical")
                reader.assert_called_once_with(identity_path)

    def test_fallback_is_deterministic_for_same_visible_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity_path = Path(tmp) / "missing-host-identity"
            module = load_identity_runtime(identity_path)

            values = {
                str(identity_path): "",
                "/etc/machine-id": "machine",
                "/sys/class/dmi/id/product_uuid": "uuid",
            }

            def fake_read(path):
                return values.get(str(path), "")

            with mock.patch.object(module, "_read_text", side_effect=fake_read), \
                 mock.patch.object(Path, "iterdir", return_value=iter(())):
                expected = "sha256:" + hashlib.sha256(
                    b"capivara-host-v1\nmachine\nuuid"
                ).hexdigest()
                self.assertEqual(module._host_identity(), expected)


if __name__ == "__main__":
    unittest.main()
