#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "core", ROOT / "database", ROOT / "dashboard"):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

from runtime_workspace_catalog import (
    game_workspace_catalog,
    runtime_definition,
    runtime_workspace_capabilities,
)


CAPABILITIES = (
    "scheduled_restart",
    "broadcast",
    "save",
    "graceful_shutdown",
    "native_countdown",
)


def runtime_ids(game: str) -> list[str]:
    """Return every runtime known by either UX policy or canonical catalog.

    M7 must not accidentally skip games that have a RuntimeDefinition but no
    workspace-policy.json.  Workspace policy is a presentation/entitlement
    surface; the canonical runtime inventory lives under catalog/v2/games/*/runtimes.
    """
    identifiers = {
        str(value)
        for value in (game_workspace_catalog(ROOT, game).get("runtimes") or {})
        if str(value)
    }

    runtime_root = ROOT / "catalog" / "v2" / "games" / game / "runtimes"
    if runtime_root.is_dir():
        for path in sorted(runtime_root.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            runtime_id = str(payload.get("id") or "").strip()
            if runtime_id:
                identifiers.add(runtime_id)

    return sorted(identifiers)


class M7MaintenanceCapabilityInventoryTest(unittest.TestCase):

    def test_every_catalog_runtime_has_effective_maintenance_contract(self):
        games_root = ROOT / "catalog" / "v2" / "games"

        discovered = 0

        for game_dir in sorted(games_root.iterdir()):
            if not game_dir.is_dir():
                continue

            game = game_dir.name

            for runtime_id in runtime_ids(game):
                discovered += 1

                capabilities = runtime_workspace_capabilities(
                    ROOT,
                    game,
                    runtime_id,
                )

                maintenance = capabilities.get("maintenance")

                self.assertIsInstance(
                    maintenance,
                    dict,
                    f"{game}/{runtime_id}",
                )

                for capability in CAPABILITIES:
                    self.assertIn(
                        capability,
                        maintenance,
                        f"{game}/{runtime_id}: missing {capability}",
                    )
                    self.assertIsInstance(
                        maintenance[capability],
                        bool,
                        f"{game}/{runtime_id}: {capability}",
                    )

        self.assertGreater(discovered, 0)

    def test_missing_maintenance_is_fail_closed(self):
        games_root = ROOT / "catalog" / "v2" / "games"

        for game_dir in sorted(games_root.iterdir()):
            if not game_dir.is_dir():
                continue

            game = game_dir.name

            for runtime_id in runtime_ids(game):
                definition = runtime_definition(
                    ROOT,
                    game,
                    runtime_id,
                )

                policy = game_workspace_catalog(ROOT, game)
                workspace = (
                    (policy.get("runtimes") or {}).get(runtime_id) or {}
                )

                runtime_has = isinstance(
                    definition.get("maintenance"),
                    dict,
                )

                workspace_has = isinstance(
                    workspace.get("maintenance"),
                    dict,
                )

                if runtime_has or workspace_has:
                    continue

                maintenance = runtime_workspace_capabilities(
                    ROOT,
                    game,
                    runtime_id,
                )["maintenance"]

                self.assertFalse(maintenance["broadcast"])
                self.assertFalse(maintenance["save"])
                self.assertFalse(maintenance["graceful_shutdown"])
                self.assertFalse(maintenance["native_countdown"])

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

            self.assertEqual(
                maintenance,
                expected,
                runtime_id,
            )

        bedrock = runtime_workspace_capabilities(
            ROOT,
            "minecraft",
            "minecraft.bedrock.vanilla",
        )["maintenance"]

        self.assertTrue(bedrock["scheduled_restart"])
        self.assertFalse(bedrock["broadcast"])
        self.assertFalse(bedrock["save"])
        self.assertFalse(bedrock["graceful_shutdown"])
        self.assertFalse(bedrock["native_countdown"])

    def test_dayz_native_contract_remains_enabled(self):
        maintenance = runtime_workspace_capabilities(
            ROOT,
            "dayz",
            "dayz.stable",
        )["maintenance"]

        self.assertTrue(maintenance["scheduled_restart"])
        self.assertTrue(maintenance["graceful_shutdown"])
        self.assertTrue(maintenance["native_countdown"])

        self.assertFalse(maintenance["broadcast"])
        self.assertFalse(maintenance["save"])


if __name__ == "__main__":
    unittest.main()
