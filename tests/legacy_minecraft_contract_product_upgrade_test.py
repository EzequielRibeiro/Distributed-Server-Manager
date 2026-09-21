#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
if str(DATABASE) not in sys.path:
    sys.path.insert(0, str(DATABASE))

from baseline_upgrade_engine import (
    _upgrade_legacy_minecraft_contract_products,
    latest_upgrade_version,
)


class SQLiteBackend:
    name = "sqlite"


class LegacyMinecraftContractProductUpgradeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = SQLiteBackend()
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE service_contracts (
                id TEXT PRIMARY KEY,
                game_id TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE instances (
                id TEXT PRIMARY KEY,
                game_id TEXT NOT NULL,
                runtime_id TEXT NOT NULL
            );
            CREATE TABLE instance_contracts (
                instance_id TEXT PRIMARY KEY,
                contract_id TEXT NOT NULL
            );
            """
        )

    def tearDown(self) -> None:
        self.connection.close()

    def add_contract(
        self,
        contract_id: str,
        runtime_id: str,
        metadata: dict | None = None,
    ) -> None:
        self.connection.execute(
            "INSERT INTO service_contracts(id,game_id,metadata_json) VALUES (?,?,?)",
            (contract_id, "minecraft", json.dumps(metadata or {})),
        )
        instance_id = f"instance-{contract_id}"
        self.connection.execute(
            "INSERT INTO instances(id,game_id,runtime_id) VALUES (?,?,?)",
            (instance_id, "minecraft", runtime_id),
        )
        self.connection.execute(
            "INSERT INTO instance_contracts(instance_id,contract_id) VALUES (?,?)",
            (instance_id, contract_id),
        )

    def metadata(self, contract_id: str) -> dict:
        row = self.connection.execute(
            "SELECT metadata_json FROM service_contracts WHERE id=?",
            (contract_id,),
        ).fetchone()
        return json.loads(row["metadata_json"])

    def test_upgrade_20_is_registered(self) -> None:
        self.assertEqual(latest_upgrade_version(), 20)

    def test_legacy_neoforge_contract_is_backfilled_as_modified(self) -> None:
        self.add_contract(
            "legacy-neoforge",
            "minecraft.java.neoforge",
            {"resource_profile_id": "low"},
        )
        _upgrade_legacy_minecraft_contract_products(self.backend, self.connection)
        metadata = self.metadata("legacy-neoforge")
        self.assertEqual(metadata["product_variant"], "modified")
        self.assertEqual(metadata["content_mode"], "modified")
        self.assertTrue(metadata["entitlements"]["mods"])
        self.assertTrue(metadata["entitlements"]["plugins"])
        self.assertTrue(metadata["entitlements"]["workshop"])
        self.assertFalse(metadata["entitlements"]["custom_runtime"])
        self.assertEqual(metadata["resource_profile_id"], "low")

    def test_explicit_standard_contract_is_never_promoted(self) -> None:
        original = {
            "product_variant": "standard",
            "content_mode": "standard",
            "entitlements": {"mods": False},
        }
        self.add_contract(
            "explicit-standard",
            "minecraft.java.neoforge",
            original,
        )
        _upgrade_legacy_minecraft_contract_products(self.backend, self.connection)
        self.assertEqual(self.metadata("explicit-standard"), original)

    def test_legacy_vanilla_contract_remains_implicit(self) -> None:
        self.add_contract(
            "legacy-vanilla",
            "minecraft.java.vanilla",
            {"resource_profile_id": "standard"},
        )
        _upgrade_legacy_minecraft_contract_products(self.backend, self.connection)
        metadata = self.metadata("legacy-vanilla")
        self.assertNotIn("product_variant", metadata)
        self.assertNotIn("content_mode", metadata)

    def test_all_known_modified_only_runtimes_are_repaired(self) -> None:
        runtime_ids = (
            "minecraft.java.paper",
            "minecraft.java.purpur",
            "minecraft.java.folia",
            "minecraft.java.fabric",
            "minecraft.java.forge",
            "minecraft.java.neoforge",
            "minecraft.java.quilt",
            "minecraft.java.spongevanilla",
            "minecraft.java.arclight",
            "minecraft.java.youer",
        )
        for index, runtime_id in enumerate(runtime_ids):
            self.add_contract(f"legacy-{index}", runtime_id)
        _upgrade_legacy_minecraft_contract_products(self.backend, self.connection)
        for index, runtime_id in enumerate(runtime_ids):
            with self.subTest(runtime_id=runtime_id):
                self.assertEqual(
                    self.metadata(f"legacy-{index}")["product_variant"],
                    "modified",
                )


if __name__ == "__main__":
    unittest.main()
