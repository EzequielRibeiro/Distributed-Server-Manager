#!/usr/bin/env python3
"""Dashboard contract tests for Controller -> Hybrid administration."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "dashboard", ROOT / "agents" / "linux" / "runtime"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from backend import DatabaseConfig
from backend_factory import create_backend
from infrastructure_role_api import local_role_status, promote_local_controller_for_user
from infrastructure_role_http import (
    INFRASTRUCTURE_ROLE_PATH,
    dispatch_infrastructure_role_get,
    dispatch_infrastructure_role_post,
)
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class InfrastructureRoleDashboardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "dsm"
        (self.root / "config").mkdir(parents=True)
        (self.root / "config" / "agent.conf").write_text(
            'AGENT_ID=""\nAGENT_NAME=""\nAGENT_STATUS="pending"\nDSM_NODE_ID=""\n',
            encoding="utf-8",
        )
        (self.root / "version").write_text("1.4.3\n", encoding="utf-8")
        self.backend = create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(Path(self.temp.name) / "capivara.db"),
            )
        )
        self.identity = installation_profile_identity(
            RegistryRepository(self.backend),
            profile="controller",
            hostname="dashboard-role-host",
        )
        self.admin = {"username": "admin", "role": "admin"}
        self.controller_user = {"username": "operator", "role": "controller"}

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_get_reports_controller_without_local_agent(self):
        payload = local_role_status(self.backend, node_id="dashboard-role-host")
        self.assertEqual(payload["role"], "controller")
        self.assertEqual(payload["controller_id"], self.identity["controller_id"])
        self.assertIsNone(payload["agent_id"])

    def test_only_admin_can_promote_local_node(self):
        with self.assertRaises(PermissionError):
            promote_local_controller_for_user(
                self.controller_user,
                self.backend,
                self.root,
                {"role": "hybrid", "node_id": "dashboard-role-host"},
            )

    def test_admin_promotion_reconciles_agent_and_is_idempotent(self):
        inventory = {
            "hostname": "dashboard-role-host",
            "os_name": "linux",
            "architecture": "x86_64",
            "capivara_version": "1.4.3",
            "capabilities": {"native-linux": True, "steamcmd": True},
            "cpu": {"logical_cores": 8},
            "ram_total_bytes": 16 * 1024**3,
            "storage": {"root_total_bytes": 100 * 1024**3, "root_free_bytes": 80 * 1024**3},
            "network": {"tcp_listen": [], "udp_listen": []},
        }
        with patch("hybrid_local_reconciliation._default_inventory", return_value=inventory):
            first = promote_local_controller_for_user(
                self.admin,
                self.backend,
                self.root,
                {"role": "hybrid", "node_id": "dashboard-role-host"},
            )
            second = promote_local_controller_for_user(
                self.admin,
                self.backend,
                self.root,
                {"role": "hybrid", "node_id": "dashboard-role-host"},
            )

        self.assertEqual(first["role"], "hybrid")
        self.assertEqual(first["agent_id"], "agent-dashboard-role-host")
        self.assertEqual(first["health_status"], "online")
        self.assertEqual(second["agent_id"], first["agent_id"])
        text = (self.root / "config" / "agent.conf").read_text(encoding="utf-8")
        self.assertIn('AGENT_ID="agent-dashboard-role-host"', text)
        self.assertIn('DSM_NODE_ID="dashboard-role-host"', text)
        with RegistryRepository(self.backend).transaction() as session:
            total = session.execute(
                "SELECT COUNT(*) AS total FROM agents WHERE node_id=?",
                ("dashboard-role-host",),
            ).fetchone()["total"]
        self.assertEqual(int(total), 1)

    def test_http_dispatch_contract(self):
        status, body = dispatch_infrastructure_role_get(
            INFRASTRUCTURE_ROLE_PATH,
            user=self.admin,
            backend=self.backend,
            node_id="dashboard-role-host",
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["role"], "controller")

        status, body = dispatch_infrastructure_role_post(
            INFRASTRUCTURE_ROLE_PATH,
            {"role": "hybrid", "node_id": "dashboard-role-host"},
            user=self.controller_user,
            backend=self.backend,
            root=self.root,
        )
        self.assertEqual(status, 403)
        self.assertIn("admin", body["error"])

    def test_agents_page_loads_role_ui_asset(self):
        html = (ROOT / "dashboard" / "web" / "agents.html").read_text(encoding="utf-8")
        script = (ROOT / "dashboard" / "web" / "infrastructure-role-ui.js").read_text(encoding="utf-8")
        self.assertIn('/infrastructure-role-ui.js', html)
        self.assertIn('Ativar Agent local · modo híbrido', script)
        self.assertIn('/api/infrastructure/role', script)
        self.assertIn('window.confirm', script)


if __name__ == "__main__":
    unittest.main()
