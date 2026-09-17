#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

for path in (
    ROOT,
    ROOT / "core",
    ROOT / "database",
    ROOT / "dashboard",
    ROOT / "agents/common",
    ROOT / "agents/linux/runtime",
):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

from runtime_workspace_catalog import runtime_workspace_capabilities
import native_maintenance
from adapters.base import AdapterError
from adapters.systemd import SystemdAdapter


class PalworldNativeMaintenanceTest(unittest.TestCase):

    def test_catalog_declares_only_implemented_capabilities(self):
        m = runtime_workspace_capabilities(
            ROOT,
            "palworld",
            "palworld.stable",
        )["maintenance"]

        self.assertTrue(m["scheduled_restart"])
        self.assertTrue(m["broadcast"])
        self.assertTrue(m["save"])
        self.assertFalse(m["graceful_shutdown"])
        self.assertFalse(m["native_countdown"])

    def test_runtime_is_linux_only(self):
        import json

        definition = json.loads(
            (
                ROOT
                / "catalog/v2/games/palworld/runtimes/stable.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(
            definition["requirements"]["os"],
            ["linux"],
        )

    def test_save_is_typed(self):
        instance = {
            "game_id": "palworld",
            "instance_id": "pal-001",
        }

        with patch.object(
            native_maintenance,
            "execute",
            return_value=["saved"],
        ) as execute:
            result = native_maintenance.save(instance)

        execute.assert_called_once_with(instance, "/Save")
        self.assertEqual(result["operation"], "save")
        self.assertEqual(result["transport"], "palworld-rest")

    def test_broadcast_is_typed(self):
        instance = {
            "game_id": "palworld",
            "instance_id": "pal-001",
        }

        with patch.object(
            native_maintenance,
            "execute",
            return_value=["sent"],
        ) as execute:
            result = native_maintenance.broadcast(
                instance,
                "Restart em 5 minutos",
                priority="high",
            )

        execute.assert_called_once_with(
            instance,
            "/Broadcast Restart em 5 minutos",
        )
        self.assertEqual(result["operation"], "broadcast")
        self.assertEqual(result["transport"], "palworld-rest")

    def test_systemd_adapter_delegates_save(self):
        instance = {
            "game_id": "palworld",
            "instance_id": "pal-001",
        }

        adapter = SystemdAdapter(
            runner=lambda command, timeout: (0, "", "")
        )

        with patch(
            "adapters.systemd.native_save",
            return_value={
                "game_id": "palworld",
                "operation": "save",
            },
        ) as save:
            result = adapter.save(instance)

        save.assert_called_once_with(instance)
        self.assertEqual(result["operation"], "save")

    def test_systemd_adapter_delegates_broadcast(self):
        instance = {
            "game_id": "palworld",
            "instance_id": "pal-001",
        }

        adapter = SystemdAdapter(
            runner=lambda command, timeout: (0, "", "")
        )

        with patch(
            "adapters.systemd.native_broadcast",
            return_value={
                "game_id": "palworld",
                "operation": "broadcast",
            },
        ) as broadcast:
            result = adapter.broadcast(
                instance,
                "Aviso",
                priority="high",
            )

        broadcast.assert_called_once_with(
            instance,
            "Aviso",
            priority="high",
        )
        self.assertEqual(result["operation"], "broadcast")

    def test_other_games_fail_closed(self):
        with self.assertRaises(
            native_maintenance.NativeMaintenanceError
        ):
            native_maintenance.save({
                "game_id": "rust",
                "instance_id": "rust-001",
            })

        with self.assertRaises(
            native_maintenance.NativeMaintenanceError
        ):
            native_maintenance.broadcast(
                {
                    "game_id": "minecraft",
                    "instance_id": "mc-001",
                },
                "test",
            )

    def test_adapter_converts_native_failure_to_adapter_error(self):
        adapter = SystemdAdapter(
            runner=lambda command, timeout: (0, "", "")
        )

        with patch(
            "adapters.systemd.native_save",
            side_effect=native_maintenance.NativeMaintenanceError(
                "unsupported"
            ),
        ):
            with self.assertRaises(AdapterError):
                adapter.save({
                    "game_id": "rust",
                    "instance_id": "rust-001",
                })


if __name__ == "__main__":
    unittest.main()
