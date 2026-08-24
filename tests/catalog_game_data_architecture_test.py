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
