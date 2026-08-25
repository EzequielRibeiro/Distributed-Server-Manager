#!/usr/bin/env python3
import importlib.util
import json
import os
import threading
import tempfile
import unittest
import urllib.request
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["DSM_ROOT"] = str(ROOT)
SPEC = importlib.util.spec_from_file_location("dashboard_server", ROOT / "dashboard" / "server.py")
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from admin_management_repository import AdminManagementRepository
from runtime_backend import backend_from_environment


class CatalogV2DashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = SERVER.DashboardServer(("127.0.0.1", 0))
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close(); cls.thread.join(timeout=2)

    def public_json(self, path):
        with urllib.request.urlopen(self.base_url + path, timeout=2) as response:
            self.assertEqual(response.status, 200)
            return json.loads(response.read().decode("utf-8"))

    def test_public_health_requires_no_credentials(self):
        self.assertIn(self.public_json("/health")["status"], {"healthy", "warning", "critical"})

    def test_public_ping_requires_no_credentials(self):
        self.assertEqual(self.public_json("/ping")["status"], "ok")

    def test_dashboard_uses_project_version(self):
        expected = (ROOT / "version").read_text(encoding="utf-8").strip()
        self.assertEqual(SERVER.DSM_VERSION, expected)
        self.assertEqual(SERVER.SERVER_NAME, f"DSM Dashboard v{expected}")

    def test_login_uses_capivara_brand(self):
        login = (ROOT / "dashboard/web/login.html").read_text(encoding="utf-8")
        self.assertIn("Capivara DSM", login)
        self.assertNotIn("DayZ Server Manager", login)

    def test_instance_path_safety_contract_is_preserved(self):
        instance = ROOT / "instances/node01/minecraft/instance01"
        self.assertEqual(SERVER.catalog_instance_path(str(instance)), str(instance.resolve()))
        with self.assertRaisesRegex(ValueError, "cannot be the instances root"):
            SERVER.catalog_instance_path(str(ROOT / "instances"))
        with self.assertRaisesRegex(ValueError, "must be inside DSM instances root"):
            SERVER.catalog_instance_path(str(ROOT / "runtime/server01"))

    def test_catalog_is_game_definition_not_instance_management(self):
        html = (ROOT / "dashboard/web/catalog.html").read_text(encoding="utf-8")
        self.assertIn("Catálogo de Jogos", html)
        self.assertIn("Preparar jogos sem criar instâncias", html)
        self.assertNotIn('id="catalog-v2-instance"', html)
        self.assertNotIn("Reinstalar instância", html)
        self.assertNotIn('id="catalog-v2-config-editor"', html)

    def test_catalog_exposes_new_administrative_areas(self):
        html = (ROOT / "dashboard/web/catalog.html").read_text(encoding="utf-8")
        for text in ("Game Data", "Parâmetros", "Configuração", "Recursos", "Conteúdo", "Agents", "Versões"):
            self.assertIn(text, html)
        self.assertIn('id="catalog-game"', html)
        self.assertIn('id="catalog-runtime"', html)
        self.assertIn('id="catalog-agent"', html)
        self.assertIn('id="catalog-resource-profiles"', html)

    def test_catalog_javascript_uses_distributed_game_data_api(self):
        script = (ROOT / "dashboard/web/catalog-page.js").read_text(encoding="utf-8")
        self.assertIn("/api/catalog/runtimes", script)
        self.assertIn("/api/catalog/content?game=", script)
        self.assertIn("/api/agents/game-data", script)
        self.assertIn("/api/agents/game-data/jobs", script)
        self.assertIn("/api/catalog/resource-profiles?game=", script)
        self.assertNotIn("/api/instance/config", script)

    def test_runtime_definition_remains_execution_source(self):
        runtime = json.loads((ROOT / "catalog/v2/games/minecraft/runtimes/java-vanilla.json").read_text(encoding="utf-8"))
        self.assertEqual(runtime["kind"], "RuntimeDefinition")
        self.assertEqual(runtime["process"]["engine"], "java")
        self.assertEqual(runtime["process"]["executable"], "server.jar")
        self.assertTrue(runtime["installation"]["directory"].startswith("/opt/dsm/game-data/"))

    def test_resource_profiles_are_catalog_level(self):
        profiles = json.loads((ROOT / "catalog/v2/games/minecraft/resource-profiles.json").read_text(encoding="utf-8"))
        self.assertEqual(profiles["kind"], "GameResourceProfiles")
        self.assertEqual(profiles["game"], "minecraft")
        self.assertEqual({p["id"] for p in profiles["profiles"]}, {"standard", "large"})

    def test_controller_and_customer_instance_scope_is_preserved(self):
        instance = ROOT / "instances/DemoNode/minecraft/cliente-demo"
        controller = {"username":"controller","role":"controller","scope_id":"controller-demo"}
        customer = {"username":"customer","role":"customer","scope_id":"CLI-DEMO-001"}
        outsider = {"username":"outsider","role":"controller","scope_id":"controller-other"}
        admin = {"username":"admin","role":"admin","scope_id":""}
        self.assertTrue(SERVER.can_access_instance(admin, instance, write=True))
        self.assertTrue(SERVER.can_access_instance(controller, instance, write=True))
        self.assertTrue(SERVER.can_access_instance(customer, instance, write=True))
        self.assertFalse(SERVER.can_access_instance(outsider, instance, write=True))

    def test_instance_config_path_cannot_escape_instance(self):
        instance = ROOT / "instances/DemoNode/minecraft/cliente-demo"
        with self.assertRaisesRegex(ValueError, "invalid instance config file"):
            SERVER.instance_config_path(instance, "../../config/dsm.conf")

    def test_customer_contract_remains_instance_creation_context(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name); database = root / "data/capivara.db"
        backend = backend_from_environment({
            "DSM_DATABASE_DRIVER": "sqlite",
            "DSM_DATABASE": str(database),
        })
        backend.initialize()
        repo = AdminManagementRepository(backend)
        with repo.session(transaction=True) as session:
            session.execute(
                "INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)",
                ("controller-demo", "Controller Demo", "controller", "active"),
            )
            session.execute(
                "INSERT INTO controllers(id,node_id,name,status) VALUES (?,?,?,?)",
                ("controller-demo", "controller-demo", "Controller Demo", "active"),
            )
        customer = repo.create_customer(
            name="Aurora Games Ltda.",
            username="aurora",
            password_hash="test-hash",
            controller_id="controller-demo",
        )
        self.assertEqual(customer["customer_code"], "CLI-000001")
        user = SERVER.load_users(database)["aurora"]
        page = (ROOT / "dashboard/web/customer.html").read_text(encoding="utf-8")
        customer_script = (ROOT / "dashboard/web/customer.js").read_text(encoding="utf-8")
        runtime_selector = (ROOT / "dashboard/web/runtime-selector.js").read_text(encoding="utf-8")
        self.assertEqual(user["role"], "customer")
        self.assertIn("Criar servidor", page)
        self.assertIn('/api/customer/contracts', customer_script)
        self.assertIn('/api/instance/create', runtime_selector)

    def test_system_user_administration_page(self):
        page = (ROOT / "dashboard/web/users.html").read_text(encoding="utf-8")
        script = (ROOT / "dashboard/web/users.js").read_text(encoding="utf-8")
        self.assertIn("Administração de usuários", page)
        self.assertIn('/api/users/save', script)
        self.assertIn('/api/users/delete', script)


if __name__ == "__main__":
    unittest.main()
