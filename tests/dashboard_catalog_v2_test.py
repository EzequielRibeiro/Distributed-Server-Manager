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
sys.path.insert(0, str(ROOT / "database"))
REGISTRY_SPEC = importlib.util.spec_from_file_location("dashboard_registry", ROOT / "database" / "registry.py")
REGISTRY = importlib.util.module_from_spec(REGISTRY_SPEC)
REGISTRY_SPEC.loader.exec_module(REGISTRY)


class CatalogV2DashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = SERVER.DashboardServer(("127.0.0.1", 0))
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def public_json(self, path):
        with urllib.request.urlopen(self.base_url + path, timeout=2) as response:
            self.assertEqual(response.status, 200)
            return json.loads(response.read().decode("utf-8"))

    def test_public_health_requires_no_credentials(self):
        result = self.public_json("/health")
        self.assertIn(result["status"], {"healthy", "warning", "critical"})

    def test_public_ping_requires_no_credentials(self):
        self.assertEqual(self.public_json("/ping")["status"], "ok")

    def test_dashboard_uses_project_version(self):
        expected = (ROOT / "version").read_text(encoding="utf-8").strip()
        self.assertEqual(SERVER.DSM_VERSION, expected)
        self.assertEqual(SERVER.SERVER_NAME, f"DSM Dashboard v{expected}")

    def test_login_uses_capivara_brand(self):
        login = (ROOT / "dashboard" / "web" / "login.html").read_text(encoding="utf-8")
        header = (ROOT / "dashboard" / "web" / "components" / "header.html").read_text(encoding="utf-8")
        self.assertIn("Capivara DSM", login)
        self.assertIn("Distributed Server Manager", login)
        self.assertNotIn("DayZ Server Manager", login)
        self.assertNotIn("DayZ Server Manager", header)

    def test_instance_child_is_accepted(self):
        instance = ROOT / "instances" / "minecraft" / "server01"
        self.assertEqual(SERVER.catalog_instance_path(str(instance)), str(instance.resolve()))

    def test_runtime_hierarchy_instance_is_accepted(self):
        instance = ROOT / "instances" / "node01" / "minecraft" / "instance01"
        self.assertEqual(SERVER.catalog_instance_path(str(instance)), str(instance.resolve()))

    def test_instances_root_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cannot be the instances root"):
            SERVER.catalog_instance_path(str(ROOT / "instances"))

    def test_path_outside_instances_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must be inside DSM instances root"):
            SERVER.catalog_instance_path(str(ROOT / "runtime" / "server01"))

    def test_empty_instance_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "instance path is required"):
            SERVER.catalog_instance_path("")

    def test_dashboard_exposes_runtime_hierarchy_selectors(self):
        html = (ROOT / "dashboard" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="catalog-v2-node"', html)
        self.assertIn('id="catalog-v2-game"', html)
        self.assertIn('id="catalog-v2-instance"', html)
        self.assertIn('id="catalog-v2-runtime-summary"', html)
        self.assertNotIn('id="catalog-v2-instance" value=', html)

    def test_catalog_uses_execution_environment_terminology(self):
        html = (ROOT / "dashboard" / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "dashboard" / "web" / "catalog-v2.js").read_text(encoding="utf-8")
        self.assertIn("Instalação do jogo", html)
        self.assertIn("Ambiente de Execução<select id=\"catalog-v2-runtime\"", html)
        self.assertNotIn("Runtime do Content Catalog", html)
        self.assertIn('id="catalog-v2-environment-install"', html)
        self.assertIn("Instalar jogo via Steam", script)
        self.assertIn('/api/catalog/environment-install', script)
        self.assertIn("Instalar conteúdo selecionado", html)
        self.assertNotIn("Instalar plano", html)
        self.assertIn("Nenhum ambiente de execução disponível no catálogo", script)
        self.assertIn("Selecione um ambiente de execução do catálogo.", script)
        self.assertNotIn("Nenhum runtime no catálogo", script)

    def test_execution_environment_fields_have_no_static_defaults(self):
        html = (ROOT / "dashboard" / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "dashboard" / "web" / "catalog-v2.js").read_text(encoding="utf-8")
        self.assertNotIn('id="catalog-v2-version" value=', html)
        self.assertNotIn('id="catalog-v2-loader-version" value=', html)
        self.assertNotIn('id="catalog-v2-java" type="number" value=', html)
        self.assertIn('id="catalog-v2-version" disabled', html)
        self.assertIn('id="catalog-v2-os" disabled', html)
        self.assertIn('id="catalog-v2-check" disabled', html)
        self.assertIn("function syncExecutionEnvironmentForm()", script)
        self.assertIn('requirements.os || []', script)
        self.assertIn('requirements.architectures || []', script)
        self.assertNotIn('?.value || "linux"', script)
        self.assertNotIn('?.value || "x86_64"', script)

    def test_catalog_javascript_consumes_runtime_api(self):
        script = (ROOT / "dashboard" / "web" / "catalog-v2.js").read_text(encoding="utf-8")
        self.assertIn('request("/api/runtime/list")', script)
        self.assertIn('request(`/api/runtime?${params.toString()}`)', script)
        self.assertIn('/api/catalog/runtimes?game=', script)
        self.assertIn('request("/api/catalog/runtimes")', script)
        self.assertIn('/api/catalog/content?game=', script)
        self.assertIn('/api/catalog/installed?instance=', script)
        self.assertNotIn('/api/catalog/v2/', script)

    def test_catalog_is_browsable_without_runtime_instances(self):
        script = (ROOT / "dashboard" / "web" / "catalog-v2.js").read_text(encoding="utf-8")
        self.assertIn("Ambientes do catálogo disponíveis para consulta.", script)
        self.assertIn("installButton.disabled = false", script)
        self.assertIn("selectedContent().length", script)
        self.assertIn("...state.catalogEnvironments.map(item => item.game)", script)
        self.assertIn("O jogo pode ser instalado pelo Ambiente de Execução.", script)

    def test_catalog_javascript_resolves_instance_from_runtime_identity(self):
        script = (ROOT / "dashboard" / "web" / "catalog-v2.js").read_text(encoding="utf-8")
        self.assertIn('/opt/dsm/instances/${server}/${game}/${instance}', script)
        self.assertIn('Selecione Node, jogo e instância.', script)

    def test_selected_instance_displays_customer_and_logo_metadata(self):
        html = (ROOT / "dashboard" / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "dashboard" / "web" / "catalog-v2.js").read_text(encoding="utf-8")
        demo = json.loads((ROOT / "runtime" / "resources" / "DemoNode" / "minecraft" / "cliente-demo" / "instance.json").read_text(encoding="utf-8"))
        self.assertIn('id="catalog-v2-instance-logo"', html)
        self.assertIn('id="catalog-v2-instance-owner"', html)
        self.assertIn('id="catalog-v2-instance-customer"', html)
        self.assertIn('id="catalog-v2-instance-controller"', html)
        self.assertIn('id="catalog-v2-instance-agent"', html)
        self.assertIn("renderInstanceProfile(summary.instance_metadata || {})", script)
        self.assertEqual(demo["customer"]["id"], "CLI-DEMO-001")
        self.assertEqual(demo["controller_id"], "controller-demo")
        self.assertEqual(demo["agent_id"], "agent-demo")
        self.assertTrue(demo["logo_url"].startswith("data:image/svg+xml,"))

    def test_controller_and_customer_are_scoped_to_owned_instances(self):
        instance = ROOT / "instances" / "DemoNode" / "minecraft" / "cliente-demo"
        controller = {"username": "controller", "role": "controller", "scope_id": "controller-demo"}
        customer = {"username": "customer", "role": "customer", "scope_id": "CLI-DEMO-001"}
        outsider = {"username": "outsider", "role": "controller", "scope_id": "controller-other"}
        admin = {"username": "admin", "role": "admin", "scope_id": ""}
        self.assertTrue(SERVER.can_access_instance(admin, instance, write=True))
        self.assertTrue(SERVER.can_access_instance(controller, instance, write=True))
        self.assertTrue(SERVER.can_access_instance(customer, instance, write=True))
        self.assertFalse(SERVER.can_access_instance(outsider, instance, write=True))

    def test_instance_config_path_cannot_escape_instance(self):
        instance = ROOT / "instances" / "DemoNode" / "minecraft" / "cliente-demo"
        with self.assertRaisesRegex(ValueError, "invalid instance config file"):
            SERVER.instance_config_path(instance, "../../config/dsm.conf")

    def test_dashboard_exposes_scoped_instance_management(self):
        html = (ROOT / "dashboard" / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "dashboard" / "web" / "catalog-v2.js").read_text(encoding="utf-8")
        app = (ROOT / "dashboard" / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="catalog-v2-config-editor"', html)
        self.assertIn("/api/instance/config", script)
        self.assertIn("/api/catalog/remove", script)
        self.assertIn("instance-manager-only", app)

    def test_aurora_customer_login_and_page_are_scoped(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        database = root / "data" / "capivara.db"
        REGISTRY.create_aurora(root, database)
        user = SERVER.load_users(database)["aurora"]
        page = (ROOT / "dashboard" / "web" / "customer.html").read_text(encoding="utf-8")
        self.assertEqual(user["role"], "customer")
        self.assertEqual(user["scope_id"], "CLI-DEMO-001")
        self.assertTrue(SERVER.verify_password("Aurora@2026!", user["password_hash"]))
        self.assertIn("Meus servidores", page)
        self.assertIn("Instâncias existentes", page)
        self.assertIn("Criar servidor", page)
        customer_script = (ROOT / "dashboard" / "web" / "customer.js").read_text(encoding="utf-8")
        self.assertIn('/api/customer/contracts', customer_script)
        self.assertIn('CapivaraRuntimeSelector', customer_script)
        runtime_selector = (ROOT / "dashboard" / "web" / "runtime-selector.js").read_text(encoding="utf-8")
        self.assertIn('/api/instance/create', runtime_selector)
        instance_page = (ROOT / "dashboard" / "web" / "customer-instance.html").read_text(encoding="utf-8")
        instance_script = (ROOT / "dashboard" / "web" / "customer-instance.js").read_text(encoding="utf-8")
        self.assertIn('id="instance-start"', instance_page)
        self.assertIn('id="instance-terminal"', instance_page)
        self.assertIn('id="instance-delete"', instance_page)
        self.assertIn('/api/instance/logs', instance_script)
        self.assertIn('/api/instance/backup/create', instance_script)

    def test_system_user_administration_page(self):
        page = (ROOT / "dashboard" / "web" / "users.html").read_text(encoding="utf-8")
        script = (ROOT / "dashboard" / "web" / "users.js").read_text(encoding="utf-8")
        self.assertIn("Administração de usuários", page)
        self.assertIn('id="user-role"', page)
        self.assertIn('id="user-scope"', page)
        self.assertIn('id="user-active"', page)
        self.assertIn('/api/users/save', script)
        self.assertIn('/api/users/delete', script)
        self.assertNotIn("hash", page.lower())


if __name__ == "__main__":
    unittest.main()
