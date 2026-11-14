"""#928: isolated Controller run() lifecycle contract.

Extracts the actual run() function from dashboard/server.py without importing
its module-level production initialization. This is a narrow startup/cleanup
rehearsal, NOT a complete Controller daemon or a no-drain release gate.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


class ControllerLifecycleTests(unittest.TestCase):
    def test_real_run_starts_listener_worker_and_closes_on_interrupt(self):
        source = (ROOT / "dashboard/server.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        functions = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "run"]
        self.assertEqual(len(functions), 1)
        run_module = ast.Module(body=functions, type_ignores=[])
        ast.fix_missing_locations(run_module)
        calls = []
        server = Mock()
        server.serve_forever.side_effect = KeyboardInterrupt()
        server.server_close.side_effect = lambda: calls.append("close")
        def validate():
            calls.append("validate")
        def banner():
            calls.append("banner")
        def make_server(address):
            self.assertEqual(address, ("127.0.0.1", 0))
            calls.append("server")
            return server
        class Worker:
            def __init__(self, target, daemon):
                self.assert_target = target
                self.assert_daemon = daemon
            def start(self):
                calls.append("worker")
                assert self.assert_daemon is True, "notification worker must be daemonized"
        namespace = {
            "validate_environment": validate,
            "print_banner": banner,
            "DashboardServer": make_server,
            "HOST": "127.0.0.1",
            "PORT": 0,
            "threading": type("Threads", (), {"Thread": Worker}),
            "notification_worker": lambda: None,
        }
        exec(compile(run_module, "dashboard/server.py", "exec"), namespace)
        namespace["run"]()
        self.assertEqual(calls, ["validate", "banner", "server", "worker", "close"])
        server.serve_forever.assert_called_once_with()
        server.server_close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
