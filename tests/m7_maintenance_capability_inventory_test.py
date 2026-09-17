#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "core", ROOT / "database", ROOT / "dashboard"):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

from runtime_workspace_catalog import (
    maintenance_capability_inventory,
    runtime_maintenance_capabilities,
    runtime_workspace_capabilities,
)


CAPABILITIES = (
    "scheduled_restart",
    "broadcast",
    "save",
    "graceful_shutdown",
    "native_countdown",
)

GENERIC_SAFE = {
    "scheduled_restart": True,
    "broadcast": False,
    "save": False,
    "graceful_shutdown": False,
    "native_countdown": False,
}


def runtime_definition_inventory() -> dict[str, Path]:
    """Return the canonical key/path for every shipped RuntimeDefinition."""
    games_root = ROOT / "catalog" / "v2" / "games"
    result: dict[str, Path] = {}

    for game_dir in sorted(games_root.iterdir()):
        if not game_dir.is_dir():
            continue
        runtime_root = game_dir / "runtimes"
        if not runtime_root.is_dir():
            continue

        for path in sorted(runtime_root.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("kind") != "RuntimeDefinition":
                continue
            runtime_id = str(payload.get("id") or "").strip().lower()
            if not runtime_id:
                raise AssertionError(f"RuntimeDefinition without id: {path}")
            key = f"{game_dir.name}/{runtime_id}"
            if key in result:
                raise AssertionError(f"duplicate RuntimeDefinition: {key}")
            result[key] = path

    return result


class M7MaintenanceCapabilityInventoryTest(unittest.TestCase):

    def test_inventory_is_exactly_one_to_one_with_runtime_definitions(self):
        definitions = runtime_definition_inventory()
        inventory = maintenance_capability_inventory(ROOT)

        self.assertGreater(len(definitions), 0)
        self.assertEqual(
            set(inventory),
            set(definitions),
            "every RuntimeDefinition must have exactly one explicit M7 maintenance classification",
        )

        for key, maintenance in inventory.items():
            self.assertEqual(set(maintenance), set(CAPABILITIES), key)
            for capability in CAPABILITIES:
                self.assertIsInstance(maintenance[capability], bool, f"{key}: {capability}")

    def test_every_catalog_runtime_projects_canonical_contract(self):
        inventory = maintenance_capability_inventory(ROOT)

        for key in sorted(runtime_definition_inventory()):
            game, runtime_id = key.split("/", 1)
            effective = runtime_workspace_capabilities(ROOT, game, runtime_id)["maintenance"]
            self.assertEqual(effective, inventory[key], key)

    def test_missing_inventory_fails_closed_at_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            maintenance = runtime_maintenance_capabilities(
                root,
                "unknown-game",
                "unknown.runtime",
            )
        self.assertEqual(maintenance, GENERIC_SAFE)

    def test_minecraft_java_native_contract_is_enabled(self):
        java_runtimes = (
            "minecraft.java.vanilla",
            "minecraft.java.paper",
            "minecraft.java.fabric",
            "minecraft.java.purpur",
            "minecraft.java.folia",
            "minecraft.java.forge",
            "minecraft.java.neoforge",
            "minecraft.java.quilt",
            "minecraft.java.spongevanilla",
            "minecraft.java.youer",
            "minecraft.java.arclight",
        )

        expected = {
            "scheduled_restart": True,
            "broadcast": True,
            "save": True,
            "graceful_shutdown": False,
            "native_countdown": False,
        }

        for runtime_id in java_runtimes:
            maintenance = runtime_workspace_capabilities(
                ROOT,
                "minecraft",
                runtime_id,
            )["maintenance"]
            self.assertEqual(maintenance, expected, runtime_id)

        bedrock = runtime_workspace_capabilities(
            ROOT,
            "minecraft",
            "minecraft.bedrock.vanilla",
        )["maintenance"]
        self.assertEqual(bedrock, GENERIC_SAFE)

    def test_dayz_and_palworld_native_contracts_remain_enabled(self):
        dayz = runtime_workspace_capabilities(
            ROOT,
            "dayz",
            "dayz.stable",
        )["maintenance"]
        self.assertEqual(
            dayz,
            {
                "scheduled_restart": True,
                "broadcast": False,
                "save": False,
                "graceful_shutdown": True,
                "native_countdown": True,
            },
        )

        palworld = runtime_workspace_capabilities(
            ROOT,
            "palworld",
            "palworld.stable",
        )["maintenance"]
        self.assertEqual(
            palworld,
            {
                "scheduled_restart": True,
                "broadcast": True,
                "save": True,
                "graceful_shutdown": False,
                "native_countdown": False,
            },
        )

    def test_source_family_remains_explicitly_fail_closed(self):
        for game in (
            "counterstrike2",
            "garrysmod",
            "left4dead2",
            "teamfortress2",
        ):
            runtime_id = f"{game}.stable"
            maintenance = runtime_workspace_capabilities(
                ROOT,
                game,
                runtime_id,
            )["maintenance"]
            self.assertEqual(maintenance, GENERIC_SAFE, f"{game}/{runtime_id}")


if __name__ == "__main__":
    unittest.main()
