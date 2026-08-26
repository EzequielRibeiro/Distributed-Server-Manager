#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import controller_cli


class _PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ping":
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        return


class AgentControllerCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp.name) / "agent.json"
        self.config = {
            "agent_id": "agent-one",
            "controller_id": "controller-one",
            "controller_url": "http://192.168.15.35:8080",
            "credential_id": "cred-one",
            "credential_secret": "secret-one",
        }
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        self.config_path.chmod(0o600)
        self.original_config = controller_cli.CONFIG_PATH
        controller_cli.CONFIG_PATH = self.config_path

    def tearDown(self):
        controller_cli.CONFIG_PATH = self.original_config
        self.temp.cleanup()

    def test_normalize_preserves_public_nat_port(self):
        value = controller_cli._normalize_url("http://controller.example:18080/")
        self.assertEqual(value, "http://controller.example:18080")

    def test_normalize_rejects_embedded_credentials(self):
        with self.assertRaises(ValueError):
            controller_cli._normalize_url("https://user:pass@controller.example:18080")

    def test_show_reports_reachable_endpoint_parts(self):
        payload = controller_cli._show(self.config)
        self.assertTrue(payload["configured"])
        self.assertEqual(payload["host"], "192.168.15.35")
        self.assertEqual(payload["port"], 8080)
        self.assertEqual(payload["scheme"], "http")
        self.assertTrue(payload["enrolled"])

    def test_set_updates_only_controller_url_without_restart(self):
        with patch.object(controller_cli, "_restart_service") as restart:
            code = controller_cli.main([
                "set",
                "http://public.example:18080/",
                "--no-restart",
                "--json",
            ])
        self.assertEqual(code, 0)
        restart.assert_not_called()
        updated = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(updated["controller_url"], "http://public.example:18080")
        self.assertEqual(updated["agent_id"], "agent-one")
        self.assertEqual(updated["credential_secret"], "secret-one")
        self.assertEqual(self.config_path.stat().st_mode & 0o777, 0o600)

    def test_probe_checks_dns_tcp_and_http_ping(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _PingHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            payload = controller_cli._probe(
                f"http://127.0.0.1:{port}",
                config=self.config,
                timeout=2.0,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["dns"]["ok"])
        self.assertTrue(payload["tcp"]["ok"])
        self.assertFalse(payload["tls"]["required"])
        self.assertTrue(payload["http"]["ok"])
        self.assertEqual(payload["http"]["status_code"], 200)
        self.assertTrue(payload["authentication"]["configured"])
        self.assertFalse(payload["authentication"]["verified"])

    def test_probe_failure_is_nonzero(self):
        with patch.object(controller_cli, "_probe", return_value={"ok": False}):
            code = controller_cli.main(["test", "http://127.0.0.1:18080", "--json"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
