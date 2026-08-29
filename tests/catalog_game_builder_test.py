#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "dashboard"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from catalog_game_builder_http import publish_catalog_game, rollback_catalog_game, verify_catalog_game


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
        self.assertEqual(result["runtime"]["artifact"]["provider"], "steam")
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
        self.assertEqual(result["runtime"]["artifact"]["provider"], "http-archive")

    def test_minecraft_uses_supported_runtime_as_template(self):
        temporary, root = self._root(); self.addCleanup(temporary.cleanup)
        target = root / "catalog" / "v2" / "games" / "minecraft" / "runtimes"
        target.mkdir(parents=True)
        (target / "java-paper.json").write_text(json.dumps({
            "schema_version": 2, "kind": "RuntimeDefinition", "id": "minecraft.java.paper",
            "name": "Paper", "game": "minecraft", "edition": "java", "variant": "paper",
            "process": {"engine": "java", "executable": "paper.jar"},
            "artifact": {"provider": "http", "auth": "anonymous"},
            "installation": {"directory": "/tmp/minecraft"},
        }), encoding="utf-8")
        result = verify_catalog_game({
            "provider": "minecraft", "game_id": "minecraft", "runtime_id": "minecraft.custom-paper",
            "name": "Minecraft Custom", "minecraft_edition": "java", "server_type": "paper",
        }, root=root)
        self.assertTrue(result["ok"])
        check = next(item for item in result["checks"] if item["id"] == "minecraft_template")
        self.assertTrue(check["ok"])
        self.assertEqual(result["runtime"]["id"], "minecraft.custom-paper")

    def test_publish_is_atomic_and_rollback_is_checksum_guarded(self):
        temporary, root = self._root(); self.addCleanup(temporary.cleanup)
        payload = {
            "provider": "steam", "game_id": "sample", "runtime_id": "sample.stable",
            "name": "Sample", "package_id": "90", "auth": "anonymous",
            "executable": "sample-server", "default_port": "27015", "protocol": "udp",
        }
        published = publish_catalog_game(payload, root=root)
        self.assertTrue(published["ok"])
        publication = published["publication"]
        runtime_path = root / publication["target"]
        self.assertTrue(runtime_path.is_file())
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        self.assertEqual(runtime["kind"], "RuntimeDefinition")
        self.assertEqual(runtime["id"], "sample.stable")
        rolled_back = rollback_catalog_game(publication["publication_id"], root=root)
        self.assertTrue(rolled_back["ok"])
        self.assertFalse(runtime_path.exists())

    def test_rollback_refuses_runtime_modified_after_publication(self):
        temporary, root = self._root(); self.addCleanup(temporary.cleanup)
        payload = {"provider": "steam", "game_id": "sample", "runtime_id": "sample.stable", "name": "Sample", "package_id": "90"}
        published = publish_catalog_game(payload, root=root)
        runtime_path = root / published["publication"]["target"]
        runtime_path.write_text(runtime_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            rollback_catalog_game(published["publication"]["publication_id"], root=root)

    def test_builder_page_exposes_expected_cards_publish_and_rollback(self):
        html = (ROOT / "dashboard" / "web" / "catalog-game-create.html").read_text(encoding="utf-8")
        script = (ROOT / "dashboard" / "web" / "catalog-game-create.js").read_text(encoding="utf-8")
        for marker in ('data-provider="steam"', 'data-provider="http"', 'data-provider="github"', 'data-provider="local"', 'data-provider="minecraft"'):
            self.assertIn(marker, html)
        self.assertIn('id="builder-verify"', html)
        self.assertIn('id="builder-save"', html)
        self.assertIn('id="builder-rollback"', html)
        self.assertIn("/api/catalog/game-builder/publish", script)
        self.assertIn("/api/catalog/game-builder/rollback", script)


if __name__ == "__main__":
    unittest.main()
