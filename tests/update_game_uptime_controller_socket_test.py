"""#928: bind and close the real Controller HTTPServer class on loopback.

Uses the actual DashboardServer and run definitions from dashboard/server.py,
with a disposable handler and suppressed background worker. Does not import
production globals or launch the full dashboard daemon.
"""
from __future__ import annotations

import ast
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ControllerSocketLifecycleTests(unittest.TestCase):
    def test_actual_dashboard_server_binds_and_releases_ephemeral_socket(self):
        source = ROOT / "dashboard/server.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        nodes = [node for node in tree.body if
                 (isinstance(node, ast.ClassDef) and node.name == "DashboardServer")
                 or (isinstance(node, ast.FunctionDef) and node.name == "run")]
        self.assertEqual(len(nodes), 2)
        module = ast.Module(body=nodes, type_ignores=[])
        ast.fix_missing_locations(module)
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
        class FakeWorker:
            def __init__(self, target, daemon):
                self.assert_target = target
                self.assert_daemon = daemon
            def start(self):
                assert self.assert_daemon is True
                seen.append("worker")
        class Server(ThreadingHTTPServer):
            pass
        namespace = {
            "ThreadingHTTPServer": Server, "DashboardHandler": Handler,
            "time": time, "threading": type("Threads", (), {"Thread": FakeWorker}),
            "notification_worker": lambda: None,
            "validate_environment": lambda: seen.append("validate"),
            "print_banner": lambda: seen.append("banner"),
            "HOST": "127.0.0.1", "PORT": 0,
        }
        exec(compile(module, str(source), "exec"), namespace)
        actual = namespace["DashboardServer"]
        original_serve = actual.serve_forever
        def controlled_serve(server):
            seen.append("serving")
            host, port = server.server_address
            self.assertEqual(host, "127.0.0.1")
            self.assertGreater(port, 0)
            with socket.create_connection((host, port), timeout=2):
                pass
            seen.append(("bound_port", port))
            raise KeyboardInterrupt()
        actual.serve_forever = controlled_serve
        try:
            namespace["run"]()
        finally:
            actual.serve_forever = original_serve
        self.assertEqual(seen[:4], ["validate", "banner", "worker", "serving"])
        port = seen[-1][1]
        # A fresh socket must be able to bind the just-released ephemeral port.
        with socket.socket() as check:
            check.bind(("127.0.0.1", port))


if __name__ == "__main__":
    unittest.main()
