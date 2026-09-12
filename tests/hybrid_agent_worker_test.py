#!/usr/bin/env python3
"""Persistent Hybrid Agent worker regression tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "dashboard" / "workers"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from backend import DatabaseConfig
from backend_factory import create_backend
from hybrid_agent_worker import heartbeat_cycle, process_hybrid_backup_cycle
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

    def test_hybrid_backup_cycle_round_trips_state_and_commands(self):
        agent_id = "hybrid-backup-agent"
        config = {"agent_id": agent_id}
        previous = [
            {
                "command_id": "backup-old",
                "instance_id": "instance-1",
                "status": "completed",
            }
        ]
        commands = [
            {
                "command_id": "backup-new",
                "instance_id": "instance-1",
                "action": "create",
            }
        ]
        reports = [
            {
                "command_id": "backup-new",
                "instance_id": "instance-1",
                "action": "create",
                "status": "completed",
            }
        ]

        client = Mock()
        client.backup_state.return_value = previous
        client.apply_backup_commands.return_value = reports

        repository = Mock()
        repository.record_agent_state.side_effect = [1, 1]
        repository.commands_for_agent.return_value = commands

        with (
            patch(
                "hybrid_agent_worker._hybrid_agent_config",
                return_value=config,
            ),
            patch(
                "hybrid_agent_worker._backup_client_module",
                return_value=client,
            ),
            patch(
                "hybrid_agent_worker.BackupRepository",
                return_value=repository,
            ),
        ):
            result = process_hybrid_backup_cycle(
                self.backend,
                self.root,
                agent_id,
            )

        repository.initialize.assert_called_once_with()
        repository.record_agent_state.assert_any_call(agent_id, previous)
        repository.commands_for_agent.assert_called_once_with(agent_id)
        client.apply_backup_commands.assert_called_once_with(config, commands)
        repository.record_agent_state.assert_any_call(agent_id, reports)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["reported"], 1)
        self.assertEqual(result["commands"], 1)
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["failed"], 0)

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
        self.assertIn("start_python_worker_with_env hybrid_agent_worker.py", shell)
        self.assertIn('"CAPIVARA_AGENT_MODE=hybrid"', shell)
        self.assertIn('"CAPIVARA_DSM_ROOT=${DSM_ROOT}"', shell)
        self.assertIn('env "$@" python3 "${WORKERS_DIR}/${WORKER}"', shell)

    def test_hybrid_health_cycle_persists_runtime_inventory(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from hybrid_agent_worker import process_hybrid_instance_health_cycle

        inventory = [
            {
                "instance_id": "instance-healthy",
                "health": "healthy",
                "desired_state": "running",
                "observed_state": "running",
                "reconcile_status": "healthy",
            },
            {
                "instance_id": "instance-degraded",
                "health": "degraded",
                "desired_state": "running",
                "observed_state": "failed",
                "reconcile_status": "degraded",
            },
        ]

        runtime_health = SimpleNamespace(
            health_inventory=lambda config: inventory
        )

        repository = Mock()
        repository.apply_inventory.return_value = [
            {
                "instance_id": "instance-healthy",
                "health": "healthy",
            },
            {
                "instance_id": "instance-degraded",
                "health": "degraded",
            },
        ]

        with (
            patch(
                "hybrid_agent_worker._hybrid_agent_config",
                return_value={"agent_id": "hybrid-agent"},
            ),
            patch(
                "hybrid_agent_worker._runtime_health_module",
                return_value=runtime_health,
            ),
            patch(
                "hybrid_agent_worker.AgentInstanceRuntimeHealthRepository",
                return_value=repository,
            ),
        ):
            result = process_hybrid_instance_health_cycle(
                self.backend,
                self.root,
                "hybrid-agent",
            )

        repository.initialize.assert_called_once_with()
        repository.apply_inventory.assert_called_once_with(
            "hybrid-agent",
            inventory,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["samples"], 2)
        self.assertEqual(result["applied"], 2)
        self.assertEqual(result["healthy"], 1)
        self.assertEqual(result["degraded"], 1)

        # Fresh runtime health must be persisted before the backup
        # scheduler/command exchange runs in heartbeat_cycle.
        import inspect
        from hybrid_agent_worker import heartbeat_cycle

        source = inspect.getsource(heartbeat_cycle)
        self.assertLess(
            source.index("process_hybrid_instance_health_cycle"),
            source.index("process_hybrid_backup_cycle"),
        )



if __name__ == "__main__":
    unittest.main()
