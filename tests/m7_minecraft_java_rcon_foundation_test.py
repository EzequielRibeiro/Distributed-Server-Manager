#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LINUX_RUNTIME = ROOT / "agents" / "linux" / "runtime"
WINDOWS_RUNTIME = ROOT / "agents" / "windows" / "runtime"

for value in (ROOT, LINUX_RUNTIME):
    item = str(value)
    if item not in sys.path:
        sys.path.insert(0, item)

from profiles.minecraft_java import MinecraftJavaRuntimeProfile as LinuxMinecraftJava
from catalog_runtime_policy import materialize_network_properties


class MinecraftJavaRconFoundationTest(unittest.TestCase):

    def test_all_java_catalog_runtimes_reserve_private_rcon(self):
        root = ROOT / "catalog/v2/games/minecraft/runtimes"

        runtimes = list(sorted(root.glob("java-*.json")))
        self.assertEqual(len(runtimes), 11)

        for path in runtimes:
            data = json.loads(path.read_text(encoding="utf-8"))
            network = data["network"]

            self.assertEqual(
                network["block_size"],
                4,
                data["id"],
            )

            ports = {
                item["name"]: item
                for item in network["ports"]
            }

            self.assertEqual(
                ports["game"],
                {
                    "name": "game",
                    "protocol": "tcp",
                    "offset": 0,
                    "exposure": "public",
                },
                data["id"],
            )

            self.assertEqual(
                ports["rcon"],
                {
                    "name": "rcon",
                    "protocol": "tcp",
                    "offset": 1,
                    "exposure": "none",
                },
                data["id"],
            )
            self.assertEqual(
                ports["query"],
                {
                    "name": "query",
                    "protocol": "udp",
                    "offset": 2,
                    "exposure": "public",
                },
                data["id"],
            )
            if data["id"] == "minecraft.java.vanilla":
                self.assertNotIn("votifier", ports)
                self.assertEqual(
                    network["legacy_reservations"],
                    [{"name": "votifier", "protocol": "tcp", "offset": 3}],
                )
            else:
                self.assertEqual(
                    ports["votifier"],
                    {
                        "name": "votifier",
                        "protocol": "tcp",
                        "offset": 3,
                        "exposure": "public",
                    },
                    data["id"],
                )

    def test_linux_profile_requires_rcon_and_materializes_non_secret_properties(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = root / "content"
            state = root / "state"
            runtime = state / "runtime"

            content.mkdir()
            runtime.mkdir(parents=True)

            (runtime / "server.properties").write_text(
                "server-port=25565\n",
                encoding="utf-8",
            )

            instance = {
                "instance_id": "mc-001",
                "agent_id": "agent-1",
                "environment_id": "minecraft.java.vanilla",
            }

            context = {
                "content_root": str(content),
                "instance_state_root": str(state),
                "ports": {
                    "game": {
                        "port": 25565,
                        "protocol": "tcp",
                    },
                    "rcon": {
                        "port": 25566,
                        "protocol": "tcp",
                    },
                    "query": {
                        "port": 25567,
                        "protocol": "udp",
                    },
                    "votifier": {
                        "port": 25568,
                        "protocol": "tcp",
                    },
                },
                "catalog_runtime_policy": {
                    "runtime_id": "minecraft.java.vanilla",
                    "engine": "java",
                },
                "catalog_content_policy": {
                    "managed": {},
                },
            }

            spec = LinuxMinecraftJava().build_runtime_spec(
                instance,
                context,
            )

            self.assertEqual(
                spec.get("console"),
                {
                    "supported": True,
                    "transport": "minecraft-rcon",
                    "timeout_seconds": 5,
                },
            )

            spec["catalog_variables"] = {
                "PORT_GAME": "25565",
                "PORT_RCON": "25566",
                "PORT_QUERY": "25567",
            }

            materialize_network_properties(spec)

            text = (
                runtime / "server.properties"
            ).read_text(encoding="utf-8")

            self.assertIn(
                "enable-rcon=true",
                text,
            )
            self.assertIn(
                "rcon.port=25566",
                text,
            )
            self.assertIn(
                "broadcast-rcon-to-ops=false",
                text,
            )
            self.assertIn(
                "query.port=25567",
                text,
            )
            self.assertNotIn(
                "rcon.password=",
                text,
            )

    def test_linux_profile_fails_closed_without_rcon(self):
        instance = {
            "instance_id": "mc-001",
            "agent_id": "agent-1",
            "environment_id": "minecraft.java.vanilla",
        }

        context = {
            "content_root": "/tmp/minecraft",
            "instance_state_root": "/tmp/minecraft-state",
            "ports": {
                "game": {
                    "port": 25565,
                    "protocol": "tcp",
                },
            },
            "catalog_runtime_policy": {
                "runtime_id": "minecraft.java.vanilla",
                "engine": "java",
            },
            "catalog_content_policy": {
                "managed": {},
            },
        }

        with self.assertRaisesRegex(
            Exception,
            "RCON reservation",
        ):
            LinuxMinecraftJava().build_runtime_spec(
                instance,
                context,
            )


if __name__ == "__main__":
    unittest.main()
