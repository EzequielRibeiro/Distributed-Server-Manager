#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "core", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from core.minecraft_content_resolver import _secret_file
from dashboard.provider_credentials_http import (
    dispatch_curseforge_provider_get,
    dispatch_curseforge_provider_post,
)


class CurseForgeControllerSettingsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.admin = {"username": "admin", "role": "admin"}
        self.controller = {"username": "controller", "role": "controller"}
        self.customer = {"username": "customer", "role": "customer"}

    def tearDown(self):
        self.temp.cleanup()

    def test_admin_can_save_without_secret_echo_and_resolver_uses_managed_file(self):
        status, payload = dispatch_curseforge_provider_post(
            {"action": "save", "api_key": "example-curseforge-key-123"},
            user=self.admin,
            root=self.root,
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["configured"])
        self.assertFalse(payload["secret_exposed"])
        self.assertNotIn("example-curseforge-key-123", str(payload))
        key_path = self.root / "config" / "providers" / "curseforge.key"
        self.assertEqual(0o600, key_path.stat().st_mode & 0o777)
        with patch.dict(os.environ, {"DSM_ROOT": str(self.root)}, clear=False):
            self.assertEqual("example-curseforge-key-123", _secret_file(None))

    def test_controller_can_test_stored_key(self):
        dispatch_curseforge_provider_post(
            {"action": "save", "api_key": "example-curseforge-key-123"},
            user=self.controller,
            root=self.root,
        )
        status, payload = dispatch_curseforge_provider_post(
            {"action": "test"},
            user=self.controller,
            root=self.root,
            requester=lambda key: {"data": {"id": 432, "name": "Minecraft"}} if key else {},
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        self.assertEqual("Conexão com CurseForge validada.", payload["message"])

    def test_customer_cannot_read_or_change_provider_secret(self):
        status, _ = dispatch_curseforge_provider_get(user=self.customer, root=self.root)
        self.assertEqual(403, status)
        status, _ = dispatch_curseforge_provider_post(
            {"action": "save", "api_key": "should-not-save"},
            user=self.customer,
            root=self.root,
        )
        self.assertEqual(403, status)
        self.assertFalse((self.root / "config" / "providers" / "curseforge.key").exists())

    def test_remove_erases_secret(self):
        dispatch_curseforge_provider_post(
            {"action": "save", "api_key": "example-curseforge-key-123"},
            user=self.admin,
            root=self.root,
        )
        status, payload = dispatch_curseforge_provider_post(
            {"action": "remove"},
            user=self.admin,
            root=self.root,
        )
        self.assertEqual(200, status)
        self.assertFalse(payload["configured"])
        self.assertFalse((self.root / "config" / "providers" / "curseforge.key").exists())

    def test_system_page_exposes_provider_controls_without_secret_value(self):
        html = (ROOT / "dashboard" / "web" / "system.html").read_text(encoding="utf-8")
        script = (ROOT / "dashboard" / "web" / "system.js").read_text(encoding="utf-8")
        for marker in ("Providers de conteúdo", "curseforge-key", "curseforge-save", "curseforge-test", "curseforge-remove"):
            self.assertIn(marker, html)
        self.assertIn("/api/admin/providers/curseforge", script)
        self.assertIn('type="password"', html)


if __name__ == "__main__":
    unittest.main()
