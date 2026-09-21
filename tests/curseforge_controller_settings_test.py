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
    dispatch_github_provider_post,
    dispatch_modrinth_provider_post,
    dispatch_provider_overview_get,
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

    def test_provider_overview_reports_credential_models_without_secrets(self):
        steam = self.root / "config" / "providers" / "steam.conf"
        steam.parent.mkdir(parents=True, exist_ok=True)
        steam.write_text('DSM_STEAM_USER="alice"\n', encoding="utf-8")
        status, payload = dispatch_provider_overview_get(user=self.admin, root=self.root)
        self.assertEqual(200, status)
        providers = {item["provider"]: item for item in payload["providers"]}
        self.assertFalse(providers["curseforge"]["configured"])
        self.assertFalse(providers["github"]["configured"])
        self.assertEqual("none", providers["modrinth"]["credential_kind"])
        self.assertEqual("alice", providers["steam"]["steam_user"])
        self.assertNotIn("github-token-example-123", str(payload))
        self.assertNotIn("api_key", str(payload).lower())
        self.assertNotIn("secret_value", str(payload).lower())

    def test_github_optional_token_can_be_saved_tested_and_removed_without_echo(self):
        status, payload = dispatch_github_provider_post(
            {"action": "save", "token": "github-token-example-123"},
            user=self.admin,
            root=self.root,
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["configured"])
        self.assertNotIn("github-token-example-123", str(payload))
        token_path = self.root / "config" / "providers" / "github.token"
        self.assertEqual(0o600, token_path.stat().st_mode & 0o777)
        status, payload = dispatch_github_provider_post(
            {"action": "test"},
            user=self.admin,
            root=self.root,
            requester=lambda token: {"resources": {"core": {"remaining": 5000}}} if token else {},
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        status, payload = dispatch_github_provider_post(
            {"action": "remove"},
            user=self.admin,
            root=self.root,
        )
        self.assertEqual(200, status)
        self.assertFalse(payload["configured"])
        self.assertFalse(token_path.exists())

    def test_modrinth_connectivity_needs_no_credential(self):
        status, payload = dispatch_modrinth_provider_post(
            {"action": "test"},
            user=self.controller,
            root=self.root,
            requester=lambda: {"hits": []},
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        self.assertEqual("none", payload["credential_kind"])

    def test_system_page_exposes_provider_controls_without_secret_value(self):
        html = (ROOT / "dashboard" / "web" / "system.html").read_text(encoding="utf-8")
        script = (ROOT / "dashboard" / "web" / "system.js").read_text(encoding="utf-8")
        for marker in (
            "Providers de conteúdo", "curseforge-key", "curseforge-save", "curseforge-test", "curseforge-remove",
            "github-token", "github-save", "github-test", "github-remove", "modrinth-test", "steam-status",
        ):
            self.assertIn(marker, html)
        for endpoint in ("/api/admin/providers/curseforge", "/api/admin/providers/github", "/api/admin/providers/modrinth"):
            self.assertIn(endpoint, script)
        self.assertIn('type="password"', html)


if __name__ == "__main__":
    unittest.main()
