#!/usr/bin/env python3
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("customer_portal_server", ROOT / "dashboard" / "server.py")
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


class CustomerPortalTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.instance_root = self.root / "instances"
        self.instance = self.instance_root / "node" / "minecraft" / "aurora"
        (self.instance / ".dsm").mkdir(parents=True)
        (self.instance / "config").mkdir()
        (self.instance / "serverfiles").mkdir()
        (self.instance / "runtime").mkdir()
        (self.instance / ".dsm" / "instance-metadata.json").write_text(
            '{"controller_id":"controller","agent_id":"agent","customer":{"id":"customer"}}',
            encoding="utf-8",
        )
        (self.instance / "config" / "instance.conf").write_text("INTERNAL=true\n", encoding="utf-8")
        (self.instance / "serverfiles" / "server.properties").write_text("motd=Aurora\n", encoding="utf-8")
        (self.instance / "serverfiles" / "plugins.yml").write_text("plugins: []\n", encoding="utf-8")
        (self.instance / "runtime" / "instance.log").write_text("started\nready\n", encoding="utf-8")
        self.previous_root = SERVER.DSM_ROOT
        self.previous_instances = SERVER.INSTANCE_ROOT
        SERVER.DSM_ROOT = self.root
        SERVER.INSTANCE_ROOT = self.instance_root

    def tearDown(self):
        SERVER.DSM_ROOT = self.previous_root
        SERVER.INSTANCE_ROOT = self.previous_instances
        self.temporary.cleanup()

    def test_customer_owner_receives_manager_permissions(self):
        user = {"username": "aurora", "role": "customer", "scope_id": "customer"}
        self.assertTrue(SERVER.has_instance_permission(user, self.instance, "instance.control"))
        self.assertTrue(SERVER.has_instance_permission(user, self.instance, "instance.delete"))

    def test_outsider_has_no_instance_permissions(self):
        user = {"username": "other", "role": "customer", "scope_id": "other"}
        self.assertFalse(SERVER.has_instance_permission(user, self.instance, "logs.read"))

    def test_file_browser_hides_internal_paths_and_rejects_escape(self):
        names = {entry["name"] for entry in SERVER.list_instance_files(self.instance)}
        self.assertIn("server.properties", names)
        self.assertNotIn("config", names)
        self.assertNotIn(".dsm", names)
        self.assertNotIn("runtime", names)
        with self.assertRaisesRegex(ValueError, "invalid instance file path"):
            SERVER.instance_file_path(self.instance, "../../etc/passwd")
        with self.assertRaisesRegex(ValueError, "protected instance path"):
            SERVER.instance_file_path(self.instance, "runtime/instance.log")

    def test_create_instance_directory(self):
        result = SERVER.create_instance_directory(
            self.instance,
            ".",
            "plugins",
        )
        self.assertEqual(result["created"], True)
        self.assertEqual(result["name"], "plugins")
        self.assertEqual(result["path"], "plugins")
        self.assertTrue((self.instance / "serverfiles" / "plugins").is_dir())

    def test_invalid_instance_directory_name(self):
        with self.assertRaisesRegex(ValueError, "invalid directory name"):
            SERVER.create_instance_directory(
                self.instance,
                ".",
                "../bad",
            )

    def test_configuration_editor_uses_game_files_not_instance_metadata(self):
        self.assertEqual(SERVER.list_instance_configs(self.instance), ["plugins.yml", "server.properties"])
        self.assertEqual(SERVER.instance_config_path(self.instance, "server.properties"), self.instance / "serverfiles" / "server.properties")
        with self.assertRaisesRegex(ValueError, "invalid instance config file"):
            SERVER.instance_config_path(self.instance, "../config/instance.conf")

    def test_logs_and_backups_are_scoped_to_instance(self):
        self.assertEqual(SERVER.instance_logs(self.instance)["logs"], ["started", "ready"])
        backup = SERVER.create_instance_backup(self.instance)
        self.assertTrue(backup["name"].endswith(".tar.gz"))
        self.assertEqual(SERVER.list_instance_backups(self.instance)[0]["name"], backup["name"])

    def test_customer_pages_include_demo_and_critical_controls(self):
        instance_page = (ROOT / "dashboard" / "web" / "customer-instance.html").read_text(encoding="utf-8")
        instance_script = (ROOT / "dashboard" / "web" / "customer-instance.js").read_text(encoding="utf-8")
        demo_page = (ROOT / "dashboard" / "web" / "contract-demo.html").read_text(encoding="utf-8")
        self.assertIn("Log em tempo real", instance_page)
        self.assertIn("Excluir permanentemente", instance_page)
        self.assertIn('id="delete-progress"', instance_page)
        self.assertIn("setDeleteProgress", instance_script)
        self.assertIn("Criando backup final antes da exclusão", instance_script)
        self.assertIn("contratação e cobrança ainda não disponíveis", demo_page)

    def test_provisioning_status_is_visible_and_blocks_server_controls(self):
        instance_page = (ROOT / "dashboard" / "web" / "customer-instance.html").read_text(encoding="utf-8")
        instance_script = (ROOT / "dashboard" / "web" / "customer-instance.js").read_text(encoding="utf-8")
        customer_script = (ROOT / "dashboard" / "web" / "customer.js").read_text(encoding="utf-8")
        self.assertIn('id="provision-progress"', instance_page)
        self.assertIn("renderProvision", instance_script)
        self.assertIn("pending_steam_auth", instance_script)
        self.assertIn("item.provision", customer_script)


if __name__ == "__main__":
    unittest.main()
