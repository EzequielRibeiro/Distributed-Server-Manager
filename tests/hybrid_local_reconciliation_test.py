#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from hybrid_local_reconciliation import _hybrid_capabilities, reconcile_local_hybrid_runtime
from infrastructure_role_cli import promote_local_controller
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class HybridLocalReconciliationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir(parents=True)
        (self.root / "version").write_text("1.4.3\n", encoding="utf-8")
        self.config = self.root / "config" / "agent.conf"
        self.config.write_text(
            'AGENT_ID=""\n'
            'AGENT_NAME=""\n'
            'AGENT_STATUS="pending"\n'
            'DSM_NODE_ID=""\n'
            'DSM_NODE_ROLE="controller"\n'
            'HOSTNAME=""\n'
            'AGENT_TOKEN="keep-me"\n',
            encoding="utf-8",
        )

        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(self.root / "capivara.db"))
        )
        self.repository = RegistryRepository(self.backend)
        installation_profile_identity(
            self.repository,
            profile="controller",
            hostname="phase23-host",
            node_id="phase23-host",
            controller_id="controller-phase23-host",
        )
        self.transition = promote_local_controller(
            self.repository,
            node_id="phase23-host",
            controller_id="controller-phase23-host",
            agent_id="agent-phase23-host",
        )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _inventory(self):
        return {
            "hostname": "phase23-host",
            "os_name": "linux",
            "architecture": "x86_64",
            "capivara_version": "1.4.3",
            "capabilities": {"native-linux": True, "steamcmd": True},
            "cpu": {"logical_cores": 4},
            "ram_total_bytes": 8 * 1024**3,
            "storage": {"root_free_bytes": 50 * 1024**3},
            "network": {"tcp_listen": [], "udp_listen": []},
            "telemetry": {
                "schema_version": 1,
                "host": {
                    "cpu_usage_pct": 12.5,
                    "memory": {"usage_pct": 31.0},
                    "temperature_c": 54.0,
                },
                "agent": {"pid": 1234, "cpu_usage_pct": 1.5},
            },
        }

    def test_reconciles_agent_conf_and_runtime_without_touching_secret(self):
        result = reconcile_local_hybrid_runtime(
            self.repository,
            self.root,
            node_id="phase23-host",
            agent_id="agent-phase23-host",
            hostname="phase23-host",
            inventory=self._inventory(),
        )

        text = self.config.read_text(encoding="utf-8")
        self.assertIn('AGENT_ID="agent-phase23-host"', text)
        self.assertIn('AGENT_NAME="Agent phase23-host"', text)
        self.assertIn('AGENT_STATUS="active"', text)
        self.assertIn('DSM_NODE_ID="phase23-host"', text)
        self.assertIn('DSM_NODE_ROLE="hybrid"', text)
        self.assertIn('HOSTNAME="phase23-host"', text)
        self.assertIn('AGENT_TOKEN="keep-me"', text)
        self.assertTrue(result["runtime_reconciled"])
        self.assertEqual(result["health_status"], "online")
        self.assertEqual(result["telemetry"]["host"]["temperature_c"], 54.0)

        with self.repository.transaction() as session:
            row = session.execute(
                "SELECT metadata_json FROM agents WHERE id=?",
                ("agent-phase23-host",),
            ).fetchone()
        metadata = json.loads(row["metadata_json"] or "{}")
        self.assertEqual(metadata["telemetry"]["host"]["cpu_usage_pct"], 12.5)
        self.assertEqual(metadata["telemetry"]["agent"]["pid"], 1234)

    def test_hybrid_capability_probe_uses_writable_local_state_root(self):
        seen = {}

        def fake_detect():
            seen["state_root"] = os.environ.get("CAPIVARA_AGENT_STATE_DIR")
            return {
                "steamcmd": True,
                "steamcmd_status": {"installed": True, "functional": True},
            }

        original = os.environ.get("CAPIVARA_AGENT_STATE_DIR")
        with patch("hybrid_local_reconciliation.detect_capabilities", side_effect=fake_detect):
            result = _hybrid_capabilities(self.root)

        self.assertTrue(result["steamcmd"])
        self.assertEqual(
            seen["state_root"],
            str(self.root / "runtime" / "state" / "hybrid-agent"),
        )
        self.assertEqual(os.environ.get("CAPIVARA_AGENT_STATE_DIR"), original)

    @unittest.skipUnless(hasattr(os, "chown"), "POSIX ownership test")
    def test_reconciliation_preserves_agent_conf_owner_group_and_mode(self):
        self.config.chmod(0o640)
        before = self.config.stat()

        with patch("hybrid_local_reconciliation.os.chown", wraps=os.chown) as chown:
            reconcile_local_hybrid_runtime(
                self.repository,
                self.root,
                node_id="phase23-host",
                agent_id="agent-phase23-host",
                hostname="phase23-host",
                inventory=self._inventory(),
            )

        self.assertTrue(chown.called)
        _, uid, gid = chown.call_args.args
        self.assertEqual(uid, before.st_uid)
        self.assertEqual(gid, before.st_gid)

        after = self.config.stat()
        self.assertEqual(after.st_uid, before.st_uid)
        self.assertEqual(after.st_gid, before.st_gid)
        self.assertEqual(after.st_mode & 0o777, 0o640)

    def test_reconciliation_is_retry_safe(self):
        first = reconcile_local_hybrid_runtime(
            self.repository,
            self.root,
            node_id="phase23-host",
            agent_id="agent-phase23-host",
            hostname="phase23-host",
            inventory=self._inventory(),
        )
        second = reconcile_local_hybrid_runtime(
            self.repository,
            self.root,
            node_id="phase23-host",
            agent_id="agent-phase23-host",
            hostname="phase23-host",
            inventory=self._inventory(),
        )
        self.assertTrue(first["config_changed"])
        self.assertFalse(second["config_changed"])
        self.assertEqual(second["health_status"], "online")

        with self.repository.transaction() as session:
            agent_count = session.execute(
                "SELECT COUNT(*) AS total FROM agents WHERE node_id=?",
                ("phase23-host",),
            ).fetchone()["total"]
            runtime_count = session.execute(
                "SELECT COUNT(*) AS total FROM agent_runtime_inventory WHERE agent_id=?",
                ("agent-phase23-host",),
            ).fetchone()["total"]
        self.assertEqual(agent_count, 1)
        self.assertEqual(runtime_count, 1)


if __name__ == "__main__":
    unittest.main()
