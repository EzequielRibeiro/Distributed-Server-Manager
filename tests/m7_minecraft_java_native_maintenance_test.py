#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
COMMON = ROOT / "agents" / "common"

for item in (ROOT, RUNTIME, COMMON):
    value = str(item)
    if value not in sys.path:
        sys.path.insert(0, value)

import minecraft_rcon_secret
import native_maintenance


class MinecraftJavaNativeMaintenanceTest(unittest.TestCase):

    def instance(self):
        return {
            "instance_id": "mc-001",
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

    def test_broadcast_builds_typed_say_command_locally(self):
        instance = self.instance()

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
                instance,
                "Maintenance in 5 minutes",
            )

        execute.assert_called_once_with(
            "127.0.0.1",
            25566,
            "secret-value",
            "say Maintenance in 5 minutes",
        )

        self.assertEqual(
            result["transport"],
            "minecraft-rcon",
        )
        self.assertEqual(
            result["operation"],
            "broadcast",
        )

    def test_save_builds_fixed_save_command_locally(self):
        instance = self.instance()

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
            result = native_maintenance.save(instance)

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

    def test_non_java_minecraft_fails_closed(self):
        instance = self.instance()
        instance["environment_id"] = "minecraft.bedrock.vanilla"

        with self.assertRaisesRegex(
            native_maintenance.NativeMaintenanceError,
            "does not support",
        ):
            native_maintenance.save(instance)

    def test_missing_rcon_fails_closed(self):
        instance = self.instance()
        instance["ports"].pop("rcon")

        with patch.object(
            native_maintenance,
            "read_password",
            return_value="secret-value",
        ):
            with self.assertRaises(
                native_maintenance.NativeMaintenanceError
            ):
                native_maintenance.save(instance)

    def test_secret_store_is_instance_scoped_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get(
                "CAPIVARA_RUNTIME_SECRET_ROOT"
            )
            os.environ["CAPIVARA_RUNTIME_SECRET_ROOT"] = tmp

            try:
                instance = self.instance()

                first = minecraft_rcon_secret.ensure_password(
                    instance
                )
                second = minecraft_rcon_secret.ensure_password(
                    instance
                )

                self.assertEqual(first, second)
                self.assertGreaterEqual(len(first), 32)

                path = (
                    Path(tmp)
                    / "mc-001"
                    / "minecraft_rcon_password"
                )

                self.assertTrue(path.is_file())
                self.assertEqual(
                    path.stat().st_mode & 0o777,
                    0o600,
                )
            finally:
                if old is None:
                    os.environ.pop(
                        "CAPIVARA_RUNTIME_SECRET_ROOT",
                        None,
                    )
                else:
                    os.environ[
                        "CAPIVARA_RUNTIME_SECRET_ROOT"
                    ] = old

    def test_secret_materializes_into_server_properties(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secrets = root / "secrets"
            runtime = root / "instance" / "runtime"
            runtime.mkdir(parents=True)

            properties = runtime / "server.properties"
            properties.write_text(
                "enable-rcon=true\n"
                "rcon.port=25566\n",
                encoding="utf-8",
            )

            old = os.environ.get(
                "CAPIVARA_RUNTIME_SECRET_ROOT"
            )
            os.environ[
                "CAPIVARA_RUNTIME_SECRET_ROOT"
            ] = str(secrets)

            try:
                instance = {
                    **self.instance(),
                    "configuration_root": str(runtime),
                    "working_directory": str(runtime),
                }

                password = (
                    minecraft_rcon_secret.ensure_password(
                        instance
                    )
                )

                changed = (
                    minecraft_rcon_secret.materialize_password(
                        instance
                    )
                )

                text = properties.read_text(
                    encoding="utf-8"
                )

                self.assertTrue(changed)
                self.assertIn(
                    f"rcon.password={password}",
                    text,
                )
            finally:
                if old is None:
                    os.environ.pop(
                        "CAPIVARA_RUNTIME_SECRET_ROOT",
                        None,
                    )
                else:
                    os.environ[
                        "CAPIVARA_RUNTIME_SECRET_ROOT"
                    ] = old


if __name__ == "__main__":
    unittest.main()
