#!/usr/bin/env python3

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.catalog_resource_profile_policy import (
    load_game_resource_profiles,
    resolve_catalog_resource_profile,
)


class CatalogResourceProfilePolicyTest(unittest.TestCase):
    def _root(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / "catalog" / "v2" / "games").mkdir(parents=True)
        return root

    def _write(self, root: Path, game: str, payload: dict) -> None:
        path = root / "catalog" / "v2" / "games" / game / "resource-profiles.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_contract_rejects_game_without_profiles(self):
        root = self._root()
        with self.assertRaisesRegex(ValueError, "has no resource profiles configured"):
            resolve_catalog_resource_profile(
                root=root,
                game_id="dayz",
                require_catalog=True,
            )

    def test_requested_profile_missing_is_rejected(self):
        root = self._root()
        self._write(
            root,
            "dayz",
            {
                "schema_version": 2,
                "kind": "GameResourceProfiles",
                "game": "dayz",
                "default_profile_id": "standard",
                "profiles": [
                    {"id": "standard", "name": "Standard", "memory_mb": 8192, "storage_mb": 40960}
                ],
            },
        )
        with self.assertRaisesRegex(ValueError, "not found for game"):
            resolve_catalog_resource_profile(
                root=root,
                game_id="dayz",
                requested_profile_id="low",
                require_catalog=True,
            )

    def test_game_default_profile_is_used(self):
        root = self._root()
        self._write(
            root,
            "dayz",
            {
                "schema_version": 2,
                "kind": "GameResourceProfiles",
                "game": "dayz",
                "default_profile_id": "standard",
                "profiles": [
                    {"id": "standard", "name": "Standard", "memory_mb": 8192, "storage_mb": 40960}
                ],
            },
        )
        profile_id, profile, _catalog = resolve_catalog_resource_profile(
            root=root,
            game_id="dayz",
            require_catalog=True,
        )
        self.assertEqual("standard", profile_id)
        self.assertEqual("standard", profile["id"])

    def test_duplicate_profile_ids_are_rejected(self):
        root = self._root()
        self._write(
            root,
            "dayz",
            {
                "schema_version": 2,
                "kind": "GameResourceProfiles",
                "game": "dayz",
                "default_profile_id": "standard",
                "profiles": [
                    {"id": "standard", "name": "A", "memory_mb": 8192, "storage_mb": 40960},
                    {"id": "standard", "name": "B", "memory_mb": 8192, "storage_mb": 40960},
                ],
            },
        )
        with self.assertRaisesRegex(ValueError, "duplicate resource profile"):
            load_game_resource_profiles(root, "dayz")

    def test_repository_dayz_low_profile_exists(self):
        root = Path(__file__).resolve().parents[1]
        profile_id, profile, _catalog = resolve_catalog_resource_profile(
            root=root,
            game_id="dayz",
            requested_profile_id="low",
            require_catalog=True,
        )
        self.assertEqual("low", profile_id)
        self.assertEqual(6144, profile["memory_mb"])


class CatalogResourceProfileOverrideIntegrationTest(unittest.TestCase):
    def _root(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / "catalog" / "v2" / "games" / "dayz").mkdir(parents=True)
        return root

    def _payload(self, memory_mb: int) -> dict:
        return {
            "schema_version": 2,
            "kind": "GameResourceProfiles",
            "game": "dayz",
            "default_profile_id": "standard",
            "profiles": [
                {
                    "id": "standard",
                    "name": "Standard",
                    "memory_mb": memory_mb,
                    "storage_mb": 40960,
                    "cpu_cores": 4,
                    "swap_mb": 2048,
                    "pids_limit": 768,
                }
            ],
        }

    def test_override_has_precedence_over_static_catalog(self):
        root = self._root()

        static_path = (
            root / "catalog" / "v2" / "games" / "dayz"
            / "resource-profiles.json"
        )
        static_path.write_text(
            json.dumps(self._payload(8192)),
            encoding="utf-8",
        )

        override_path = (
            root / "config" / "catalog-resource-profiles" / "dayz.json"
        )
        override_path.parent.mkdir(parents=True)
        override_path.write_text(
            json.dumps(self._payload(12288)),
            encoding="utf-8",
        )

        profile_id, profile, _catalog = resolve_catalog_resource_profile(
            root=root,
            game_id="dayz",
            requested_profile_id="standard",
            require_catalog=True,
        )

        self.assertEqual("standard", profile_id)
        self.assertEqual(12288, profile["memory_mb"])

    def test_invalid_profile_values_are_rejected(self):
        root = self._root()
        payload = self._payload(8192)
        payload["profiles"][0]["cpu_cores"] = 0

        path = (
            root / "catalog" / "v2" / "games" / "dayz"
            / "resource-profiles.json"
        )
        path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "outside the allowed range"):
            load_game_resource_profiles(root, "dayz")

if __name__ == "__main__":
    unittest.main()
