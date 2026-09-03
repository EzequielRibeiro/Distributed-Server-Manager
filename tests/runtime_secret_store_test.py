#!/usr/bin/env python3
from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "agents/linux/runtime", ROOT / "agents/linux/runtime/materializers"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from runtime_secret_store import RuntimeSecretError, inspect_secret, put_secret, revoke_secret
from runtime_spec import RuntimeSpecError, validate_runtime_spec
from materializers.systemd import render_unit


class RuntimeSecretStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_root = os.environ.get("CAPIVARA_RUNTIME_SECRET_ROOT")
        os.environ["CAPIVARA_RUNTIME_SECRET_ROOT"] = str(Path(self.temp.name) / "secrets")

    def tearDown(self):
        if self.old_root is None:
            os.environ.pop("CAPIVARA_RUNTIME_SECRET_ROOT", None)
        else:
            os.environ["CAPIVARA_RUNTIME_SECRET_ROOT"] = self.old_root
        self.temp.cleanup()

    @staticmethod
    def spec():
        return {
            "instance_id": "instance-1",
            "agent_id": "agent-1",
            "runtime_id": "valheim.stable",
            "adapter": "systemd",
            "working_directory": "/srv/game",
            "executable": "/srv/game/server",
            "arguments": ["-port", "2456"],
            "environment": {},
            "user": "capivara-instance",
            "desired_state": "stopped",
            "secret_refs": [
                {"name": "SERVER_PASSWORD", "ref": "instance/instance-1/server_password", "target": "file"}
            ],
        }

    def test_runtime_spec_contains_reference_only(self):
        spec = validate_runtime_spec(self.spec(), expected_agent_id="agent-1")
        self.assertEqual(spec["secret_refs"][0]["ref"], "instance/instance-1/server_password")
        self.assertNotIn("value", spec["secret_refs"][0])
        with self.assertRaises(RuntimeSpecError):
            value = self.spec(); value["secret_refs"][0]["target"] = "environment"; validate_runtime_spec(value)
        with self.assertRaises(RuntimeSpecError):
            value = self.spec(); value["secret_refs"][0]["ref"] = "instance/other/server_password"; validate_runtime_spec(value)

    def test_put_rotate_inspect_and_revoke_do_not_return_plaintext(self):
        first = put_secret("instance/instance-1/server_password", "first-secret", expected_instance_id="instance-1")
        self.assertNotIn("first-secret", repr(first))
        path = Path(os.environ["CAPIVARA_RUNTIME_SECRET_ROOT"]) / "instance-1" / "server_password"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(path.read_text(), "first-secret")
        second = put_secret("instance/instance-1/server_password", "rotated-secret", expected_instance_id="instance-1")
        self.assertNotIn("rotated-secret", repr(second))
        self.assertEqual(path.read_text(), "rotated-secret")
        inspected = inspect_secret("instance/instance-1/server_password", expected_instance_id="instance-1")
        self.assertTrue(inspected["present"]); self.assertNotIn("rotated-secret", repr(inspected))
        revoked = revoke_secret("instance/instance-1/server_password", expected_instance_id="instance-1")
        self.assertTrue(revoked["revoked"]); self.assertFalse(path.exists())

    def test_systemd_uses_loadcredential_without_secret_value(self):
        secret = "do-not-put-this-in-unit"
        put_secret("instance/instance-1/server_password", secret, expected_instance_id="instance-1")
        unit = render_unit(validate_runtime_spec(self.spec()))
        self.assertIn("LoadCredential=SERVER_PASSWORD:", unit)
        self.assertIn("runtime-secrets/instance-1/server_password", unit)
        self.assertNotIn(secret, unit)
        self.assertNotIn("Environment=\"SERVER_PASSWORD=", unit)
        self.assertNotIn(secret, " ".join(self.spec()["arguments"]))

    def test_missing_or_cross_instance_secret_fails_closed(self):
        with self.assertRaises(Exception):
            render_unit(validate_runtime_spec(self.spec()))
        with self.assertRaises(RuntimeSecretError):
            put_secret("instance/other/server_password", "secret", expected_instance_id="instance-1")


if __name__ == "__main__":
    unittest.main()
