from pathlib import Path
import unittest


CLI = Path("agents/linux/runtime/controller_cli.py").read_text(encoding="utf-8")
CAP = Path("bin/cap").read_text(encoding="utf-8")


class P10ControllerConnectivityContractTest(unittest.TestCase):
    def test_controller_test_checks_dns_tcp_tls_and_http(self):
        self.assertIn('"dns": {"ok": False}', CLI)
        self.assertIn('"tcp": {"ok": False}', CLI)
        self.assertIn('"tls": {"required": endpoint["scheme"] == "https"', CLI)
        self.assertIn('"http": {"ok": False}', CLI)
        self.assertIn('socket.getaddrinfo', CLI)
        self.assertIn('socket.create_connection', CLI)
        self.assertIn('ssl.create_default_context()', CLI)
        self.assertIn('normalized.rstrip("/") + "/ping"', CLI)
        self.assertIn('latency_ms', CLI)

    def test_public_cap_cli_routes_controller_diagnostics(self):
        self.assertIn('cap agent controller test [URL]', CAP)
        self.assertIn('agent_controller_exec', CAP)
        self.assertIn('controller) require_role "cap agent controller" agent hybrid', CAP)

    def test_endpoint_validation_rejects_embedded_credentials(self):
        self.assertIn('Credentials must not be embedded in the Controller URL', CLI)
        self.assertIn('Controller URL must use http:// or https://', CLI)


if __name__ == "__main__":
    unittest.main()
