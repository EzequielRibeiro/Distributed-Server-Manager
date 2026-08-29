#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "dashboard"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from catalog_game_builder_http import verify_catalog_game


class CatalogGameBuilderTest(unittest.TestCase):
    def _root(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "catalog" / "v2" / "games").mkdir(parents=True)
        return temporary, root

    def test_steam_definition_is_dry_run_only(self):
        temporary, root = self._root(); self.addCleanup(temporary.cleanup)
        result = verify_catalog_game({
            "provider": "steam", "game_id": "dayz2", "runtime_id": "dayz2.stable",
            "name": "DayZ 2", "package_id": "223350", "auth": "required",
        }, root=root)
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "dry-run")
        self.assertTrue(any(item.get("warning") for item in result["checks"]))

    def test_http_provider_probes_without_full_download(self):
        temporary, root = self._root(); self.addCleanup(temporary.cleanup)
        with patch("catalog_game_builder_http._public_http_url", return_value="https://example.invalid/game.zip"), patch("catalog_game_builder_http._probe_remote", return_value={"ok": True, "status": 200, "mode": "HEAD"}):
            result = verify_catalog_game({
                "provider": "http", "game_id": "sample", "runtime_id": "sample.stable",
                "name": "Sample", "url": "https://example.invalid/game.zip",
            }, root=root)
        self.assertTrue(result["ok"])
        remote = next(item for item in result["checks"] if item["id"] == "remote")
        self.assertEqual(remote["details"]["mode"], "HEAD")

    def test_minecraft_is_assistant_not_artifact_provider(self):
        temporary, root = self._root(); self.addCleanup(temporary.cleanup)
        result = verify_catalog_game({
            "provider": "minecraft", "game_id": "minecraft2", "runtime_id": "minecraft2.paper",
            "name": "Minecraft Custom", "minecraft_edition": "java", "server_type": "paper",
        }, root=root)
        check = next(item for item in result["checks"] if item["id"] == "minecraft_provider")
        self.assertIn("assistente", check["message"].lower())
        self.assertIn("http/github", check["message"].lower())

    def test_builder_page_exposes_expected_cards_and_verify_button(self):
        html = (ROOT / "dashboard" / "web" / "catalog-game-create.html").read_text(encoding="utf-8")
        for marker in ('data-provider="steam"', 'data-provider="http"', 'data-provider="github"', 'data-provider="local"', 'data-provider="minecraft"'):
            self.assertIn(marker, html)
        self.assertIn('id="builder-verify"', html)
        self.assertIn('id="builder-save"', html)


if __name__ == "__main__":
    unittest.main()
