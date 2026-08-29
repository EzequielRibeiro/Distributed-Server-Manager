#!/usr/bin/env python3
"""Behavioral tests for canonical Linux host identity selection."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "agents/linux/runtime"
AGENT_PATH = RUNTIME_DIR / "agent.py"


def load_agent(host_identity_path: Path):
    previous_identity = os.environ.get("CAPIVARA_AGENT_HOST_IDENTITY")
    runtime_path = str(RUNTIME_DIR)
    inserted_runtime_path = runtime_path not in sys.path

    os.environ["CAPIVARA_AGENT_HOST_IDENTITY"] = str(host_identity_path)
    if inserted_runtime_path:
        sys.path.insert(0, runtime_path)

    try:
        spec = importlib.util.spec_from_file_location("capivara_agent_runtime_test", AGENT_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        if inserted_runtime_path:
            try:
                sys.path.remove(runtime_path)
            except ValueError:
                pass

        if previous_identity is None:
            os.environ.pop("CAPIVARA_AGENT_HOST_IDENTITY", None)
        else:
            os.environ["CAPIVARA_AGENT_HOST_IDENTITY"] = previous_identity


class LinuxHostIdentityMaterializationIntegrationTest(unittest.TestCase):
    def test_materialized_identity_wins_over_runtime_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity_path = Path(tmp) / "host-identity"
            identity_path.write_text("sha256:canonical\n", encoding="utf-8")
            module = load_agent(identity_path)
            with mock.patch.object(module, "_read_text", wraps=module._read_text) as reader:
                self.assertEqual(module._host_identity(), "sha256:canonical")
                reader.assert_called_once_with(identity_path)

    def test_fallback_is_deterministic_for_same_visible_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity_path = Path(tmp) / "missing-host-identity"
            module = load_agent(identity_path)

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
