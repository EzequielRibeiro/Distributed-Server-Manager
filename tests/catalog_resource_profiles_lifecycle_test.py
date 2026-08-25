#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from catalog_resource_profiles_http import (
    create_catalog_resource_profile,
    delete_catalog_resource_profile,
    catalog_resource_profiles,
    set_catalog_default_profile,
    update_catalog_resource_profile,
)


class CatalogResourceProfilesLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        game_dir = self.root / "catalog" / "v2" / "games" / "minecraft"
        game_dir.mkdir(parents=True)
        (game_dir / "resource-profiles.json").write_text(
            json.dumps({
                "schema_version": 2,
                "kind": "GameResourceProfiles",
                "game": "minecraft",
                "default_profile_id": "standard",
                "profiles": [
                    self.profile("standard", "Standard", cpu=2, memory=4096),
                    self.profile("large", "Large", cpu=4, memory=8192),
                ],
            }),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def profile(identifier, name, *, cpu=2, memory=4096):
        return {
            "id": identifier,
            "name": name,
            "description": name,
            "cpu_cores": cpu,
            "memory_mb": memory,
            "storage_mb": 20480,
            "swap_mb": 1024,
            "pids_limit": 512,
        }

    def test_create_appends_without_replacing_existing_profiles(self):
        result = create_catalog_resource_profile(
            self.root, "minecraft", self.profile("small", "Small", cpu=1, memory=2048)
        )
        self.assertEqual([p["id"] for p in result["profiles"]], ["standard", "large", "small"])
        self.assertEqual(result["default_profile_id"], "standard")

    def test_duplicate_create_is_rejected_without_mutating_catalog(self):
        with self.assertRaisesRegex(ValueError, "already exists"):
            create_catalog_resource_profile(
                self.root, "minecraft", self.profile("large", "Duplicate")
            )
        current = catalog_resource_profiles(self.root, "minecraft")
        self.assertEqual([p["id"] for p in current["profiles"]], ["standard", "large"])

    def test_update_changes_only_selected_profile(self):
        result = update_catalog_resource_profile(
            self.root, "minecraft", "large", self.profile("large", "Large Plus", cpu=6, memory=12288)
        )
        standard, large = result["profiles"]
        self.assertEqual(standard["name"], "Standard")
        self.assertEqual(standard["cpu_cores"], 2.0)
        self.assertEqual(large["name"], "Large Plus")
        self.assertEqual(large["cpu_cores"], 6.0)

    def test_default_change_does_not_modify_profile_collection(self):
        before = catalog_resource_profiles(self.root, "minecraft")["profiles"]
        result = set_catalog_default_profile(self.root, "minecraft", "large")
        self.assertEqual(result["default_profile_id"], "large")
        self.assertEqual(result["profiles"], before)

    def test_default_profile_must_be_changed_before_delete(self):
        with self.assertRaisesRegex(ValueError, "another default"):
            delete_catalog_resource_profile(self.root, "minecraft", "standard")
        self.assertEqual(len(catalog_resource_profiles(self.root, "minecraft")["profiles"]), 2)

    def test_delete_removes_only_selected_non_default_profile(self):
        result = delete_catalog_resource_profile(self.root, "minecraft", "large")
        self.assertEqual([p["id"] for p in result["profiles"]], ["standard"])
        self.assertEqual(result["default_profile_id"], "standard")

    def test_dashboard_does_not_use_whole_collection_put(self):
        script = (ROOT / "dashboard" / "web" / "game-profiles.js").read_text(encoding="utf-8")
        self.assertNotIn('method:"PUT"', script)
        self.assertIn('method:"POST"', script)
        self.assertIn('method:"PATCH"', script)
        self.assertIn('method:"DELETE"', script)
        html = (ROOT / "dashboard" / "web" / "game-profiles.html").read_text(encoding="utf-8")
        self.assertNotIn("Salvar perfis e padrão", html)


if __name__ == "__main__":
    unittest.main()
