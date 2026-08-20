#!/usr/bin/env python3
"""Persistent Hybrid Agent worker regression tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "dashboard" / "workers"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from backend import DatabaseConfig
from backend_factory import create_backend
from hybrid_agent_worker import heartbeat_cycle
from infrastructure_role_cli import promote_local_controller
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class HybridAgentWorkerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "dsm"
        (self.root / "config").mkdir(parents=True)
        (self.root / "config" / "agent.conf").write_text(
            'AGENT_ID=""\nAGENT_STATUS="pending"\nDSM_NODE_ID=""\nDSM_NODE_ROLE="controller"\n',
            encoding="utf-8",
        )
        (self.root / "version").write_text("1.4.3\n", encoding="utf-8")
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        self.repository = RegistryRepository(self.backend)
        installation_profile_identity(
            self.repository,
            profile="controller",
            hostname="persistent-hybrid-host",
        )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_controller_node_is_inert(self):
        result = heartbeat_cycle(self.root, backend=self.backend)
        self.assertFalse(result["active"])
        self.assertEqual(result["reason"], "not_hybrid")

    def test_promoted_hybrid_renews_runtime_heartbeat(self):
        transition = promote_local_controller(
            self.repository,
            node_id="persistent-hybrid-host",
        )
        config = self.root / "config" / "agent.conf"
        config.write_text(
            f'AGENT_ID="{transition["agent_id"]}"\n'
            'AGENT_STATUS="active"\n'
            'DSM_NODE_ID="persistent-hybrid-host"\n'
            'DSM_NODE_ROLE="hybrid"\n',
            encoding="utf-8",
        )
        inventory = {
            "hostname": "persistent-hybrid-host",
            "os_name": "linux",
            "architecture": "x86_64",
            "capivara_version": "1.4.3",
            "capabilities": {"native-linux": True, "steamcmd": True},
            "cpu": {"logical_cores": 4},
            "ram_total_bytes": 8 * 1024**3,
            "storage": {"root_free_bytes": 50 * 1024**3},
            "network": {"tcp_listen": [], "udp_listen": []},
        }
        with patch("hybrid_local_reconciliation._default_inventory", return_value=inventory):
            first = heartbeat_cycle(self.root, backend=self.backend)
            second = heartbeat_cycle(self.root, backend=self.backend)

        self.assertTrue(first["active"])
        self.assertTrue(second["active"])
        self.assertEqual(second["health_status"], "online")
        self.assertEqual(second["agent_id"], transition["agent_id"])

        with self.repository.transaction() as session:
            row = session.execute(
                "SELECT health_status,last_seen FROM agent_runtime_inventory WHERE agent_id=?",
                (transition["agent_id"],),
            ).fetchone()
        self.assertEqual(row["health_status"], "online")
        self.assertTrue(row["last_seen"])

    def test_dashboard_worker_starts_persistent_worker(self):
        shell = (ROOT / "dashboard" / "workers" / "worker.sh").read_text(encoding="utf-8")
        self.assertIn("start_python_worker hybrid_agent_worker.py", shell)


if __name__ == "__main__":
    unittest.main()
