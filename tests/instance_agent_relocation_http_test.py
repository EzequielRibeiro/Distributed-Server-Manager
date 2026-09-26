#!/usr/bin/env python3
"""Default-off administrative relocation API, without touching real instances."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT/"database", ROOT/"dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from tests.instance_agent_relocation_test import AgentRelocationTest
from instance_agent_relocation_http import PATH, install_instance_agent_relocation_http
from instance_agent_relocation_repository import InstanceAgentRelocationRepository


class DisabledRelocationHttpTest(unittest.TestCase):
    setUp = AgentRelocationTest.setUp
    def test_mutation_is_locked_by_default_even_for_admin(self):
        class Handler:
            path = PATH
            headers = {"X-Capivara-Auth-Area": "controller"}
            response = None

            def do_GET(self):
                raise AssertionError("unexpected route")
            def do_POST(self):
                raise AssertionError("unexpected route")
            def read_json_body(self):
                return {"action": "start", "instance_id": "server-1",
                        "target_agent_id": "target-agent", "confirmation": "server-1"}
            def send_json(self, code, payload):
                self.response = (code, payload)

        legacy = SimpleNamespace(
            DashboardHandler=Handler,
            dashboard_repository=lambda path: SimpleNamespace(backend=self.backend),
            DATABASE_FILE=str(self.root/"test.db"), DSM_ROOT=ROOT,
        )
        with patch.dict(os.environ, {"CAPIVARA_ENABLE_AGENT_RELOCATION": ""}), patch.object(
            InstanceAgentRelocationRepository, "enqueue",
            side_effect=AssertionError("no migration allowed before certification")
        ):
            install_instance_agent_relocation_http(
                legacy, lambda headers: {"role": "admin", "username": "test-admin"}
            )
            obj = Handler()
            obj.do_POST()
        self.assertEqual(obj.response[0], 423)
        self.assertEqual(obj.response[1]["error"], "relocation_not_certified")
        self.assertEqual(self.repo.list_for_instance("server-1"), [])


if __name__ == "__main__":
    unittest.main()
