from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "web"


class ControllerCustomerInstanceSeparationTest(unittest.TestCase):
    def test_controller_dashboard_has_no_instance_runtime_controls(self):
        html = (WEB / "controller-dashboard.html").read_text(encoding="utf-8")
        self.assertNotIn('id="btn-start"', html)
        self.assertNotIn('id="btn-stop"', html)
        self.assertNotIn('id="btn-restart"', html)
        self.assertNotIn('id="catalog-v2-instance"', html)
        self.assertIn('href="/customers.html"', html)
        self.assertIn('href="/agents.html"', html)
        self.assertIn('href="/servers-v2.html"', html)

    def test_controller_entrypoint_routes_index_to_dedicated_page(self):
        server = (ROOT / "dashboard" / "server_part13.py").read_text(encoding="utf-8")
        self.assertIn('"/":legacy.WEB_DIR/"controller-dashboard.html"', server)
        self.assertIn('"/index.html":legacy.WEB_DIR/"controller-dashboard.html"', server)
        self.assertIn('"/controller-dashboard.js"', server)
        self.assertIn('"/controller-dashboard.css"', server)

    def test_customer_dashboard_lists_contracts_and_instances(self):
        html = (WEB / "customer.html").read_text(encoding="utf-8")
        script = (WEB / "customer.js").read_text(encoding="utf-8")
        self.assertIn('id="customer-contracts"', html)
        self.assertIn('id="customer-servers"', html)
        self.assertIn('"/api/customer/contracts"', script)
        self.assertIn('"/api/runtime/list"', script)
        self.assertIn('"Administrar instância"', script)
        self.assertIn('"/customer-instance.html?"', script)

    def test_runtime_list_and_instance_files_keep_existing_access_guards(self):
        server = (ROOT / "dashboard" / "server.py").read_text(encoding="utf-8")
        runtime_list = server.index('if path == "/api/runtime/list":')
        config = server.index('if path == "/api/instance/config":', runtime_list)
        runtime_block = server[runtime_list:config]
        self.assertIn('if user["role"] != "admin":', runtime_block)
        self.assertIn("can_access_instance(", runtime_block)
        self.assertIn("INSTANCE_ROOT", runtime_block)
        config_end = server.index('if path in {', config)
        config_block = server[config:config_end]
        self.assertIn('has_instance_permission(user, instance, "game.files.read")', config_block)

    def test_instance_page_owns_runtime_content_files_backups_logs_and_events(self):
        html = (WEB / "customer-instance.html").read_text(encoding="utf-8")
        for view in ("overview", "logs", "events", "config", "files", "content", "backups", "danger"):
            self.assertIn(f'id="view-{view}"', html)
        for control in ("instance-start", "instance-restart", "instance-stop"):
            self.assertIn(f'id="{control}"', html)
        self.assertIn('src="/customer-instance-events.js"', html)
        self.assertIn('href="/customer-instance-events.css"', html)

    def test_instance_events_are_scoped_by_instance_identity(self):
        script = (WEB / "customer-instance-events.js").read_text(encoding="utf-8")
        self.assertIn('Object.fromEntries(new URLSearchParams(location.search))', script)
        self.assertIn('/api/runtime?', script)
        self.assertIn('identity.server', script)
        self.assertIn('identity.game', script)
        self.assertIn('identity.instance', script)

    def test_responsive_styles_avoid_global_horizontal_overflow(self):
        controller_css = (WEB / "controller-dashboard.css").read_text(encoding="utf-8")
        events_css = (WEB / "customer-instance-events.css").read_text(encoding="utf-8")
        self.assertIn("overflow-x:hidden", controller_css)
        self.assertIn("minmax(0,1fr)", controller_css)
        self.assertIn("overflow-wrap:anywhere", controller_css)
        self.assertIn("overflow-wrap:anywhere", events_css)


if __name__ == "__main__":
    unittest.main()
