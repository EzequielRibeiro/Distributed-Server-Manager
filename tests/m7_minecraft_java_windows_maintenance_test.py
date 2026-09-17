#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_RUNTIME = ROOT / "agents" / "windows" / "runtime"
COMMON = ROOT / "agents" / "common"

for path in (
    WINDOWS_RUNTIME,
    COMMON,
    ROOT,
):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

import native_maintenance
from adapters.windows_process import WindowsProcessAdapter
from adapters.base import AdapterError


def instance():
    return {
        "instance_id": "mc-win-001",
        "game_id": "minecraft",
        "environment_id": "minecraft.java.vanilla",
        "ports": {
            "game": {
                "port": 25565,
                "protocol": "tcp",
            },
            "rcon": {
                "port": 25566,
                "protocol": "tcp",
            },
        },
    }


class MinecraftJavaWindowsMaintenanceTest(unittest.TestCase):

    def test_broadcast_is_typed(self):
        spec = instance()

        with (
            patch.object(
                native_maintenance,
                "read_password",
                return_value="secret-value",
            ),
            patch.object(
                native_maintenance,
                "execute_source_rcon",
                return_value="OK",
            ) as execute,
        ):
            result = native_maintenance.broadcast(
                spec,
                "Restart soon",
            )

        execute.assert_called_once_with(
            "127.0.0.1",
            25566,
            "secret-value",
            "say Restart soon",
        )

        self.assertEqual(
            result["transport"],
            "minecraft-rcon",
        )

    def test_save_is_fixed_command(self):
        spec = instance()

        with (
            patch.object(
                native_maintenance,
                "read_password",
                return_value="secret-value",
            ),
            patch.object(
                native_maintenance,
                "execute_source_rcon",
                return_value="Saved",
            ) as execute,
        ):
            result = native_maintenance.save(spec)

        execute.assert_called_once_with(
            "127.0.0.1",
            25566,
            "secret-value",
            "save-all flush",
        )

        self.assertEqual(
            result["operation"],
            "save",
        )

    def test_bedrock_fails_closed(self):
        spec = instance()
        spec["environment_id"] = "minecraft.bedrock.vanilla"

        with self.assertRaises(
            native_maintenance.NativeMaintenanceError
        ):
            native_maintenance.save(spec)

    def test_adapter_delegates_broadcast(self):
        adapter = WindowsProcessAdapter()
        spec = instance()

        with patch(
            "adapters.windows_process.native_broadcast",
            return_value={"operation": "broadcast"},
        ) as operation:
            result = adapter.broadcast(
                spec,
                "hello",
                priority="high",
            )

        operation.assert_called_once_with(
            spec,
            "hello",
            priority="high",
        )

        self.assertEqual(
            result["operation"],
            "broadcast",
        )

    def test_adapter_delegates_save(self):
        adapter = WindowsProcessAdapter()
        spec = instance()

        with patch(
            "adapters.windows_process.native_save",
            return_value={"operation": "save"},
        ) as operation:
            result = adapter.save(spec)

        operation.assert_called_once_with(spec)
        self.assertEqual(result["operation"], "save")

    def test_adapter_converts_native_error(self):
        adapter = WindowsProcessAdapter()

        with patch(
            "adapters.windows_process.native_save",
            side_effect=native_maintenance.NativeMaintenanceError(
                "native failed"
            ),
        ):
            with self.assertRaisesRegex(
                AdapterError,
                "native failed",
            ):
                adapter.save(instance())


if __name__ == "__main__":
    unittest.main()
