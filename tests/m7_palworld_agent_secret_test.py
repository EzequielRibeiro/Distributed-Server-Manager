#!/usr/bin/env python3
from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"

if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from palworld_admin_secret import (
    PalworldAdminSecretError,
    ensure_admin_password,
    materialize_admin_password,
)


class PalworldAgentSecretTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)

        self.state = root / "instance"
        self.config = (
            self.state
            / "Pal"
            / "Saved"
            / "Config"
            / "LinuxServer"
        )

        self.config.mkdir(parents=True)

        self.settings = self.config / "PalWorldSettings.ini"
        self.settings.write_text(
            "[/Script/Pal.PalGameWorldSettings]\n"
            "OptionSettings=("
            "AdminPassword=\"\","
            "RESTAPIEnabled=True,"
            "RESTAPIPort=24012"
            ")\n",
            encoding="utf-8",
        )

        self.spec = {
            "game_id": "palworld",
            "instance_id": "pal-001",
            "instance_state_root": str(self.state),
            "configuration_root": str(self.config),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_secret_is_generated_locally_and_persisted_private(self):
        value = ensure_admin_password(self.spec)

        self.assertGreaterEqual(len(value), 32)

        path = (
            self.state
            / ".dsm"
            / "palworld-admin-password"
        )

        self.assertTrue(path.is_file())
        self.assertEqual(
            stat.S_IMODE(path.stat().st_mode),
            0o600,
        )

        self.assertEqual(
            value,
            path.read_text(encoding="utf-8").strip(),
        )

    def test_secret_is_idempotent(self):
        first = ensure_admin_password(self.spec)
        second = ensure_admin_password(self.spec)

        self.assertEqual(first, second)

    def test_secret_is_not_controller_supplied(self):
        self.spec["AdminPassword"] = "controller-secret"
        self.spec["admin_password"] = "controller-secret"

        value = ensure_admin_password(self.spec)

        self.assertNotEqual(value, "controller-secret")

    def test_materialization_writes_password_without_returning_it(self):
        password = ensure_admin_password(self.spec)

        changed = materialize_admin_password(self.spec)

        self.assertTrue(changed)

        text = self.settings.read_text(encoding="utf-8")

        self.assertIn(
            f'AdminPassword="{password}"',
            text,
        )

        self.assertNotIn(password, repr(changed))

    def test_materialization_preserves_settings_mode(self):
        os.chmod(self.settings, 0o640)
        before = self.settings.stat()

        materialize_admin_password(self.spec)

        after = self.settings.stat()

        self.assertEqual(
            stat.S_IMODE(after.st_mode),
            stat.S_IMODE(before.st_mode),
        )
        self.assertEqual(after.st_uid, before.st_uid)
        self.assertEqual(after.st_gid, before.st_gid)

    def test_existing_customer_password_is_replaced_by_agent_secret(self):
        self.settings.write_text(
            "OptionSettings=("
            'AdminPassword="customer-value",'
            "RESTAPIEnabled=True,"
            "RESTAPIPort=24012"
            ")\n",
            encoding="utf-8",
        )

        password = ensure_admin_password(self.spec)
        materialize_admin_password(self.spec)

        text = self.settings.read_text(encoding="utf-8")

        self.assertIn(
            f'AdminPassword="{password}"',
            text,
        )
        self.assertNotIn(
            "customer-value",
            text,
        )

    def test_other_games_fail_closed(self):
        spec = dict(self.spec)
        spec["game_id"] = "rust"

        with self.assertRaises(PalworldAdminSecretError):
            ensure_admin_password(spec)

    def test_symlink_secret_is_rejected(self):
        control = self.state / ".dsm"
        control.mkdir()

        target = self.state / "target"
        target.write_text("secret", encoding="utf-8")

        (
            control / "palworld-admin-password"
        ).symlink_to(target)

        with self.assertRaises(PalworldAdminSecretError):
            ensure_admin_password(self.spec)


if __name__ == "__main__":
    unittest.main()
