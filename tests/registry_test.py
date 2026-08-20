#!/usr/bin/env python3
import importlib.util
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))
SPEC = importlib.util.spec_from_file_location("registry", ROOT / "database" / "registry.py")
REGISTRY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REGISTRY)
SERVER_SPEC = importlib.util.spec_from_file_location("dashboard_server_registry_test", ROOT / "dashboard" / "server.py")
SERVER = importlib.util.module_from_spec(SERVER_SPEC)
SERVER_SPEC.loader.exec_module(SERVER)


def seed_dayz_agent_runtime(connection):
    connection.execute(
        "INSERT INTO agent_runtime_inventory("
        "agent_id,hostname,os_name,architecture,capivara_version,"
        "capabilities_json,cpu_json,ram_total_bytes,storage_json,network_json,"
        "health_status,last_seen"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now')) "
        "ON CONFLICT(agent_id) DO UPDATE SET "
        "capabilities_json=excluded.capabilities_json,cpu_json=excluded.cpu_json,"
        "ram_total_bytes=excluded.ram_total_bytes,storage_json=excluded.storage_json,"
        "network_json=excluded.network_json,health_status='online',"
        "last_seen=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
        (
            "agent-demo", "DemoNode", "linux", "x86_64", "test",
            '{"native-linux":true,"steamcmd":true,"dayz":true,"backup":true,"mod-management":true}',
            '{"logical_cores":8}', 16 * 1024**3,
            '{"root_free_bytes":107374182400}',
            '{"tcp_listen":[],"udp_listen":[]}',
            "online",
        ),
    )


class RegistryTest(unittest.TestCase):
    def test_create_aurora_is_complete_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "data" / "capivara.db"
            REGISTRY.create_aurora(root, database)
            REGISTRY.create_aurora(root, database)
            with closing(sqlite3.connect(database)) as connection:
                row = connection.execute(
                    "SELECT controller_id,agent_id,customer_id FROM instances WHERE id='cliente-demo'"
                ).fetchone()
                self.assertEqual(row, ("controller-demo", "agent-demo", "CLI-DEMO-001"))
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM instances").fetchone()[0], 1)
                contract = connection.execute(
                    "SELECT contract_id FROM instance_contracts WHERE instance_id='cliente-demo'"
                ).fetchone()
                self.assertEqual(contract, ("aurora-minecraft-001",))
                contracts = connection.execute(
                    "SELECT id,game_id,instance_limit FROM service_contracts WHERE customer_id='CLI-DEMO-001' ORDER BY id"
                ).fetchall()
                self.assertEqual(contracts, [
                    ("aurora-dayz-001", "dayz", 1),
                    ("aurora-minecraft-001", "minecraft", 1),
                ])
            self.assertTrue((root / "instances" / "DemoNode" / "minecraft" / "cliente-demo" / ".dsm" / "instance-metadata.json").is_file())

    def test_customer_creation_consumes_the_contracted_slot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "data" / "capivara.db"
            REGISTRY.create_aurora(root, database)

            # Placement now requires explicit geographic topology and factual
            # runtime evidence for games with technical requirements.
            with closing(sqlite3.connect(database)) as connection:
                with connection:
                    connection.execute(
                        "INSERT INTO regions("
                        "id,name,country_code,continent_code,"
                        "latitude,longitude,status"
                        ") VALUES (?,?,?,?,?,?,?)",
                        (
                            "br-test",
                            "Brasil Teste",
                            "BR",
                            "SA",
                            -23.5505,
                            -46.6333,
                            "active",
                        ),
                    )
                    connection.execute(
                        "INSERT INTO datacenters("
                        "id,region_id,name,provider,city,"
                        "country_code,latitude,longitude,status"
                        ") VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            "dc-test",
                            "br-test",
                            "Datacenter Teste",
                            "test",
                            "São Paulo",
                            "BR",
                            -23.5505,
                            -46.6333,
                            "active",
                        ),
                    )
                    connection.execute(
                        "INSERT INTO agent_locations("
                        "agent_id,datacenter_id,latitude,"
                        "longitude,public_host,status"
                        ") VALUES (?,?,?,?,?,?)",
                        (
                            "agent-demo",
                            "dc-test",
                            -23.5505,
                            -46.6333,
                            "127.0.0.1",
                            "active",
                        ),
                    )
                    seed_dayz_agent_runtime(connection)

            runtime = root / "catalog" / "v2" / "runtimes" / "dayz"
            runtime.mkdir(parents=True)
            (runtime / "stable.json").write_text(
                '{"id":"dayz.stable","game":"dayz","variant":"stable",'
                '"artifact":{"provider":"steam","auth":"required"},'
                '"installation":{"directory":"/opt/dsm/game-data/dayz/serverfiles"}}',
                encoding="utf-8",
            )
            user = {"username": "aurora", "role": "customer", "scope_id": "CLI-DEMO-001"}
            payload = {
                "game": "dayz",
                "runtime_id": "dayz.stable",
                "edition": "stable",
                "version": "latest",
                "build": "default",
            }
            with (
                mock.patch.object(
                    SERVER,
                    "start_instance_provisioning",
                    return_value={
                        "status": "queued",
                        "progress": 5,
                    },
                ),
                mock.patch.object(
                    SERVER.subprocess,
                    "run",
                    return_value=mock.Mock(
                        returncode=0,
                        stdout="",
                        stderr="",
                    ),
                ),
            ):
                result = SERVER.create_customer_instance(
                    user,
                    payload,
                    root=root,
                    database_path=database,
                )
            self.assertTrue(result["created"])
            self.assertEqual(result["instance_id"], "cli-demo-001-dayz-001")
            self.assertEqual(result["name"], "Servidor DayZ 001")
            self.assertEqual(result["agent_id"], "agent-demo")
            self.assertEqual(result["contract_id"], "aurora-dayz-001")
            self.assertTrue((root / "instances" / "DemoNode" / "dayz" / "cli-demo-001-dayz-001" / "config" / "server.conf").is_file())
            with self.assertRaisesRegex(PermissionError, "contracted instance slot"):
                SERVER.create_customer_instance(user, payload, root=root, database_path=database)

    def test_deleting_instance_removes_runtime_resource_and_releases_contract_slot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "data" / "capivara.db"
            REGISTRY.create_aurora(root, database)
            instance = root / "instances" / "DemoNode" / "minecraft" / "cliente-demo"
            resource = root / "runtime" / "resources" / "DemoNode" / "minecraft" / "cliente-demo"
            user = {"username": "aurora", "role": "customer", "scope_id": "CLI-DEMO-001"}

            previous_root = SERVER.DSM_ROOT
            previous_instances = SERVER.INSTANCE_ROOT
            SERVER.DSM_ROOT = root
            SERVER.INSTANCE_ROOT = (root / "instances").resolve()
            try:
                with mock.patch.object(SERVER, "control_instance", return_value=(True, {"status": "stopped"})):
                    result = SERVER.delete_instance(user, instance, database_path=database)
                contracts = SERVER.customer_contracts(user, database_path=database)
            finally:
                SERVER.DSM_ROOT = previous_root
                SERVER.INSTANCE_ROOT = previous_instances

            self.assertTrue(result["deleted"])
            self.assertFalse(instance.exists())
            self.assertFalse(resource.exists())
            resource.mkdir(parents=True)
            (resource / "instance.json").write_text(
                '{"controller_id":"controller-demo","agent_id":"agent-demo",'
                '"customer":{"id":"CLI-DEMO-001"}}',
                encoding="utf-8",
            )
            (resource / "server.json").write_text('{"status":"online"}', encoding="utf-8")
            self.assertEqual(SERVER.api_runtime_list(database_path=database), [])
            minecraft_contract = next(contract for contract in contracts if contract["game_id"] == "minecraft")
            self.assertEqual(minecraft_contract["instances_used"], 0)
            self.assertTrue(minecraft_contract["available"])

    def test_deleting_instance_completes_when_the_local_directory_is_already_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "data" / "capivara.db"
            REGISTRY.create_aurora(root, database)
            instance = root / "instances" / "DemoNode" / "minecraft" / "cliente-demo"
            resource = root / "runtime" / "resources" / "DemoNode" / "minecraft" / "cliente-demo"
            shutil.rmtree(instance)
            user = {"username": "aurora", "role": "customer", "scope_id": "CLI-DEMO-001"}

            previous_root = SERVER.DSM_ROOT
            previous_instances = SERVER.INSTANCE_ROOT
            SERVER.DSM_ROOT = root
            SERVER.INSTANCE_ROOT = (root / "instances").resolve()
            try:
                result = SERVER.delete_instance(user, instance, database_path=database)
                contracts = SERVER.customer_contracts(user, database_path=database)
            finally:
                SERVER.DSM_ROOT = previous_root
                SERVER.INSTANCE_ROOT = previous_instances

            self.assertTrue(result["deleted"])
            self.assertTrue(result["directory_was_missing"])
            self.assertFalse(resource.exists())
            minecraft_contract = next(contract for contract in contracts if contract["game_id"] == "minecraft")
            self.assertEqual(minecraft_contract["instances_used"], 0)

    def test_purge_orphan_removes_only_a_record_without_instance_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "data" / "capivara.db"
            REGISTRY.create_aurora(root, database)
            with closing(sqlite3.connect(database)) as connection:
                with connection:
                    connection.execute(
                        "INSERT INTO instances(id,node_id,game_id,name,status,manifest_path,metadata_json,controller_id,agent_id,customer_id) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        ("dayz-server", "DemoNode", "dayz", "DayZ Server", "offline", "", "{}",
                         "controller-demo", "agent-demo", "CLI-DEMO-001"),
                    )
                    connection.execute(
                        "INSERT INTO instance_contracts(instance_id,contract_id) VALUES (?,?)",
                        ("dayz-server", "aurora-dayz-001"),
                    )
            resource = root / "runtime" / "resources" / "DemoNode" / "dayz" / "dayz-server"
            resource.mkdir(parents=True)

            result = REGISTRY.purge_orphan_instance(root, database, "dayz-server")

            self.assertTrue(result["purged"])
            self.assertFalse(resource.exists())
            with closing(sqlite3.connect(database)) as connection:
                self.assertIsNone(connection.execute("SELECT 1 FROM instances WHERE id='dayz-server'").fetchone())
            with self.assertRaisesRegex(ValueError, "local directory"):
                REGISTRY.purge_orphan_instance(root, database, "cliente-demo")

    def test_provisioning_waits_for_steam_auth_and_alerts_controller(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "data" / "capivara.db"
            REGISTRY.create_aurora(root, database)

            with closing(sqlite3.connect(database)) as connection:
                with connection:
                    connection.execute(
                        "INSERT INTO regions("
                        "id,name,country_code,continent_code,"
                        "latitude,longitude,status"
                        ") VALUES (?,?,?,?,?,?,?)",
                        (
                            "br-test",
                            "Brasil Teste",
                            "BR",
                            "SA",
                            -23.5505,
                            -46.6333,
                            "active",
                        ),
                    )
                    connection.execute(
                        "INSERT INTO datacenters("
                        "id,region_id,name,provider,city,"
                        "country_code,latitude,longitude,status"
                        ") VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            "dc-test",
                            "br-test",
                            "Datacenter Teste",
                            "test",
                            "São Paulo",
                            "BR",
                            -23.5505,
                            -46.6333,
                            "active",
                        ),
                    )
                    connection.execute(
                        "INSERT INTO agent_locations("
                        "agent_id,datacenter_id,latitude,"
                        "longitude,public_host,status"
                        ") VALUES (?,?,?,?,?,?)",
                        (
                            "agent-demo",
                            "dc-test",
                            -23.5505,
                            -46.6333,
                            "127.0.0.1",
                            "active",
                        ),
                    )

            runtime = root / "catalog" / "v2" / "runtimes" / "dayz"
            runtime.mkdir(parents=True)
            (runtime / "stable.json").write_text('{"id":"dayz.stable","game":"dayz","variant":"stable","artifact":{"provider":"steam","auth":"required"},"installation":{"directory":"/opt/dsm/game-data/dayz/serverfiles"}}')
            instance = root / "instances" / "DemoNode" / "dayz" / "demo-dayz"
            (instance / ".dsm").mkdir(parents=True)
            resource = root / "runtime" / "resources" / "DemoNode" / "dayz" / "demo-dayz"
            resource.mkdir(parents=True)
            with mock.patch.object(SERVER, "_controller_alert", return_value=True) as alert:
                SERVER._provision_worker(
                    root, database, "demo-dayz", "DemoNode", "dayz",
                    "dayz.stable", "stable", "latest", "default", instance, "agent-demo"
                )
            provision = SERVER.read_json(resource / "provision.json")
            self.assertEqual(provision["status"], "pending_steam_auth")
            self.assertIn("autenticação Steam", provision["message"])
            alert.assert_called_once()
            self.assertEqual(alert.call_args.args[3], "demo-dayz")

    def test_provisioning_reuses_local_game_data_and_copies_instance_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "data" / "capivara.db"
            REGISTRY.create_aurora(root, database)
            runtime = root / "catalog" / "v2" / "runtimes" / "minecraft"
            runtime.mkdir(parents=True)
            (runtime / "vanilla.json").write_text(
                '{"id":"minecraft.java.vanilla","game":"minecraft","variant":"vanilla",'
                '"artifact":{"provider":"http","auth":"anonymous"},'
                '"installation":{"directory":"/opt/dsm/game-data/minecraft/vanilla"},'
                '"process":{"engine":"java","executable":"server.jar"}}',
                encoding="utf-8",
            )
            game_data = root / "game-data" / "minecraft" / "vanilla"
            game_data.mkdir(parents=True)
            (game_data / "server.jar").write_bytes(b"test-server")
            (game_data / "server.properties").write_text("motd=Capivara\n")
            instance = root / "instances" / "DemoNode" / "minecraft" / "demo-minecraft"
            (instance / ".dsm").mkdir(parents=True)
            resource = root / "runtime" / "resources" / "DemoNode" / "minecraft" / "demo-minecraft"
            resource.mkdir(parents=True)
            SERVER._provision_worker(
                root, database, "demo-minecraft", "DemoNode", "minecraft",
                "minecraft.java.vanilla", "java", "latest", "default", instance, "agent-demo"
            )
            provision = SERVER.read_json(resource / "provision.json")
            self.assertEqual(provision["status"], "offline")
            self.assertEqual(provision["progress"], 100)
            self.assertEqual((instance / "serverfiles" / "server.properties").read_text(), "motd=Capivara\n")
            self.assertTrue((instance / "serverfiles" / "server.jar").is_file())
            self.assertIn('RUNTIME_ID="minecraft.java.vanilla"', (instance / "instance.conf").read_text())


if __name__ == "__main__":
    unittest.main()
