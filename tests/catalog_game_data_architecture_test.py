#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
if str(DASHBOARD) not in sys.path:
    sys.path.insert(0, str(DASHBOARD))

from catalog_resource_profiles_http import catalog_resource_profiles


class CatalogGameDataArchitectureTest(unittest.TestCase):
    def test_catalog_page_does_not_manage_instances(self):
        html = (ROOT / "dashboard/web/catalog.html").read_text(encoding="utf-8")
        self.assertNotIn('id="catalog-v2-instance"', html)
        self.assertNotIn("Reinstalar instância", html)
        for label in ("Game Data", "Parâmetros", "Configuração", "Recursos", "Agents", "Versões"):
            self.assertIn(label, html)

    def test_game_installation_has_live_progress_and_error_details(self):
        html = (ROOT / "dashboard/web/catalog.html").read_text(encoding="utf-8")
        script = (ROOT / "dashboard/web/catalog-page.js").read_text(encoding="utf-8")
        self.assertIn('id="catalog-operation-progress"', html)
        self.assertIn('id="catalog-error-details"', html)
        self.assertIn('id="catalog-steam-auth-help"', html)
        self.assertIn('id="catalog-copy-steam-auth"', html)
        self.assertIn("followJob", script)
        self.assertIn("resumeAgentJob", script)
        self.assertIn("Carregando arquivos do Agent", script)
        self.assertIn("if(byId('catalog-agent').value)loadFiles()", script)
        self.assertIn("Nenhuma nova instalação foi iniciada", script)
        self.assertIn("Object.hasOwn(operationLabels", script)
        self.assertIn("Consultando arquivos", script)
        self.assertIn("Ver detalhes técnicos do erro", html)
        self.assertIn("DSM_STEAM_USER", script)
        self.assertIn("Steam Guard", script)
        self.assertIn("navigator.clipboard.writeText", script)
        self.assertIn("document.execCommand('copy')", script)
        self.assertIn("window.isSecureContext", script)
        self.assertIn("STEAM_ACCOUNT < /dev/tty", script)
        self.assertIn("+quit < /dev/tty", script)
        self.assertNotIn("DSM_STEAM_PASSWORD", script)

    def test_resource_profile_sample_uses_explicit_units(self):
        payload = json.loads((ROOT / "catalog/v2/games/minecraft/resource-profiles.json").read_text(encoding="utf-8"))
        profiles = {item["id"]: item for item in payload["profiles"]}
        self.assertEqual(profiles["standard"]["memory_mb"], 8192)
        self.assertEqual(profiles["standard"]["storage_mb"], 25600)
        self.assertEqual(profiles["large"]["memory_mb"], 16384)
        self.assertEqual(profiles["large"]["storage_mb"], 30720)

    def test_resource_profile_reader_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                catalog_resource_profiles(Path(tmp), "../etc")

    def test_resource_profile_reader_returns_empty_for_undefined_game_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "catalog/v2/games/example").mkdir(parents=True)
            payload = catalog_resource_profiles(root, "example")
            self.assertEqual(payload["profiles"], [])

    def test_dashboard_uses_latest_composition_layer(self):
        service = (ROOT / "systemd/dsm-dashboard.service").read_text(encoding="utf-8")
        self.assertIn("server_part17.py", service)


if __name__ == "__main__":
    unittest.main()
