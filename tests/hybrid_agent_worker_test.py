#!/usr/bin/env python3
"""Persistent Hybrid Agent worker regression tests."""

from __future__ import annotations

import json
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
from hybrid_agent_worker import (
    heartbeat_cycle,
    process_hybrid_backup_cycle,
    process_hybrid_configuration_cycle,
    process_hybrid_runtime_event_cycle,
)
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



    def test_runtime_command_filter_selects_safe_remove_without_consuming_start(self):
        from agent_instance_runtime_repository import AgentInstanceRuntimeRepository

        repo = AgentInstanceRuntimeRepository(self.backend)
        with self.backend.transaction() as connection:
            from alert_repository import AlertSession
            session = AlertSession(self.backend, connection)
            try:
                session.execute(
                    "INSERT INTO nodes(id,name,status) VALUES (?,?,?)",
                    ("hybrid-safe-node","hybrid-safe-node","active"),
                )
                session.execute(
                    "INSERT INTO controllers(id,node_id,name,status) VALUES (?,?,?,?)",
                    ("hybrid-safe-controller","hybrid-safe-node","controller","active"),
                )
                session.execute(
                    "INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",
                    ("hybrid-safe-agent","hybrid-safe-controller","hybrid-safe-node","agent","active"),
                )
                session.execute(
                    "INSERT INTO customers(id,name,status) VALUES (?,?,?)",
                    (999,"safe-customer","active"),
                )
                for iid in ("safe-start","safe-remove"):
                    session.execute(
                        "INSERT INTO instances(id,name,game_id,runtime_id,status,node_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",
                        (iid,iid,"minecraft","minecraft.java.vanilla","offline","hybrid-safe-node","hybrid-safe-agent",999),
                    )
            finally:
                session.close()

        repo.enqueue(agent_id="hybrid-safe-agent", instance_id="safe-start", action="start")
        remove = repo.enqueue(agent_id="hybrid-safe-agent", instance_id="safe-remove", action="remove")
        selected = repo.command_for_agent("hybrid-safe-agent", actions={"remove"})

        self.assertEqual(selected["command_id"], remove["command_id"])
        self.assertEqual(selected["action"], "remove")

    def test_heartbeat_services_backup_and_remove_before_port_reconciliation_gate(self):
        import inspect
        source = inspect.getsource(heartbeat_cycle)
        self.assertLess(
            source.index("preflight_backup = process_hybrid_backup_cycle"),
            source.index("result = reconcile_local_hybrid_runtime"),
        )
        self.assertLess(
            source.index("preflight_remove = process_hybrid_instance_runtime_cycle"),
            source.index("result = reconcile_local_hybrid_runtime"),
        )
        self.assertIn('actions={"remove"}', source)

    def test_hybrid_configuration_cycle_round_trips_state_and_commands(self):
        agent_id = "hybrid-configuration-agent"
        config = {"agent_id": agent_id}
        previous = [{
            "target_type": "instance",
            "target_id": "instance-1",
            "namespace": "capivara.instance.server-settings",
            "desired_revision": "1",
            "applied_revision": "1",
            "desired_checksum": "old",
            "applied_checksum": "old",
            "status": "applied",
        }]
        commands = [{
            "target_type": "instance",
            "target_id": "instance-1",
            "namespace": "capivara.instance.server-settings",
            "revision": "2",
            "checksum": "new",
            "value": {"settings": {"server_name": "Hybrid DayZ"}},
        }]
        reports = [{
            "target_type": "instance",
            "target_id": "instance-1",
            "namespace": "capivara.instance.server-settings",
            "desired_revision": "2",
            "applied_revision": "2",
            "desired_checksum": "new",
            "applied_checksum": "new",
            "status": "applied",
        }]

        client = Mock()
        client.configuration_state.return_value = previous
        client.apply_configuration_commands.return_value = reports
        repository = Mock()
        repository.record_agent_state.side_effect = [1, 1]
        repository.desired_for_agent.return_value = commands

        with (
            patch("hybrid_agent_worker._hybrid_agent_config", return_value=config),
            patch("hybrid_agent_worker._configuration_client_module", return_value=client),
            patch("hybrid_agent_worker.ConfigurationRepository", return_value=repository),
        ):
            result = process_hybrid_configuration_cycle(
                self.backend, self.root, agent_id
            )

        repository.initialize.assert_called_once_with()
        repository.record_agent_state.assert_any_call(agent_id, previous)
        repository.desired_for_agent.assert_called_once_with(agent_id)
        client.apply_configuration_commands.assert_called_once_with(commands)
        repository.record_agent_state.assert_any_call(agent_id, reports)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["reported"], 1)
        self.assertEqual(result["commands"], 1)
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["applied"], 1)
        self.assertEqual(result["failed"], 0)


    def test_hybrid_runtime_events_are_persisted_and_acknowledged(self):
        agent_id = "hybrid-events-agent"
        state = self.root / "runtime" / "hybrid-agent-state"
        events_dir = state / "events"
        events_dir.mkdir(parents=True, exist_ok=True)
        event_path = events_dir / "instance-runtime.jsonl"
        payload = {
            "schema_version": 1,
            "kind": "CapivaraRuntimeEvent",
            "event_id": "event-yarax-1",
            "event_type": "YARAX_SCAN_COMPLETED",
            "type": "YARAX_SCAN_COMPLETED",
            "producer": "instance-runtime",
            "source": "agent.runtime",
            "instance_id": "instance-yarax-1",
            "agent_id": agent_id,
            "severity": "critical",
            "occurred_at": "2026-09-19T14:43:16Z",
            "data": {
                "content_id": "eicar",
                "provider": "local",
                "game_id": "dayz",
                "result": "blocked",
                "duration_ms": 18,
                "engine_version": "1.20.0",
                "ruleset_version": "2026.09.18.1",
                "matches": [{"rule": "Capivara_EICAR_Test_File", "tags": ["block","malware","test"]}],
            },
        }
        event_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

        repository = Mock()
        repository.ingest_agent_events.return_value = {
            "accepted_event_ids": ["event-yarax-1"],
            "accepted": 1,
            "created": 1,
            "rejected": 0,
        }
        runtime_events = Mock()
        runtime_events.read_runtime_events_matching.return_value = [payload]
        runtime_events.read_runtime_events.side_effect = [[payload], []]
        runtime_events.acknowledge_runtime_events.return_value = 1

        with (
            patch("hybrid_agent_worker.UniversalEventRepository", return_value=repository),
            patch("hybrid_agent_worker._runtime_events_module", return_value=runtime_events),
        ):
            result = process_hybrid_runtime_event_cycle(
                self.backend,
                self.root,
                agent_id,
                batch_size=1000,
                max_batches=5,
            )

        repository.initialize.assert_called_once_with()
        repository.ingest_agent_events.assert_called_once_with(
            agent_id,
            [payload],
            max_events=1000,
        )
        runtime_events.acknowledge_runtime_events.assert_called_once_with(
            state,
            ["event-yarax-1"],
        )
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["rejected"], 0)
        self.assertEqual(result["acknowledged"], 1)

    def test_hybrid_runtime_event_backlog_is_compacted_once_per_window(self):
        agent_id = "hybrid-backlog-agent"
        state = self.root / "runtime" / "hybrid-agent-state"
        events = [{"event_id": f"event-{index}"} for index in range(2500)]
        repository = Mock()
        repository.ingest_agent_events.side_effect = [
            {"accepted_event_ids":[f"event-{index}" for index in range(0,1000)],"accepted":1000,"created":0,"rejected":0},
            {"accepted_event_ids":[f"event-{index}" for index in range(1000,2000)],"accepted":1000,"created":0,"rejected":0},
            {"accepted_event_ids":[f"event-{index}" for index in range(2000,2500)],"accepted":500,"created":500,"rejected":0},
        ]
        runtime_events = Mock()
        runtime_events.read_runtime_events_matching.return_value = []
        runtime_events.read_runtime_events.side_effect = [events, []]
        runtime_events.acknowledge_runtime_events.return_value = 2500

        with (
            patch("hybrid_agent_worker.UniversalEventRepository", return_value=repository),
            patch("hybrid_agent_worker._runtime_events_module", return_value=runtime_events),
        ):
            result = process_hybrid_runtime_event_cycle(
                self.backend,
                self.root,
                agent_id,
                batch_size=1000,
                max_batches=5,
            )

        self.assertEqual(repository.ingest_agent_events.call_count, 3)
        runtime_events.acknowledge_runtime_events.assert_called_once()
        acknowledged_ids = runtime_events.acknowledge_runtime_events.call_args.args[1]
        self.assertEqual(len(acknowledged_ids), 2500)
        self.assertEqual(result["accepted"], 2500)
        self.assertEqual(result["created"], 500)
        self.assertEqual(result["acknowledged"], 2500)

    def test_hybrid_runtime_events_prioritize_yarax_over_fifo_backlog(self):
        agent_id = "hybrid-priority-agent"
        state = self.root / "runtime" / "hybrid-agent-state"
        yara = {"event_id":"yara-1","event_type":"YARAX_SCAN_COMPLETED","instance_id":"instance-yara"}
        fifo = [{"event_id":f"fifo-{index}","event_type":"INSTANCE_RECOVERED","instance_id":"instance-yara"} for index in range(3)]
        repository = Mock()
        repository.ingest_agent_events.return_value = {
            "accepted_event_ids": ["yara-1","fifo-0","fifo-1","fifo-2"],
            "accepted": 4,
            "created": 4,
            "rejected": 0,
        }
        runtime_events = Mock()
        runtime_events.read_runtime_events_matching.return_value = [yara]
        runtime_events.read_runtime_events.side_effect = [fifo, []]
        runtime_events.acknowledge_runtime_events.return_value = 4

        with (
            patch("hybrid_agent_worker.UniversalEventRepository", return_value=repository),
            patch("hybrid_agent_worker._runtime_events_module", return_value=runtime_events),
        ):
            result = process_hybrid_runtime_event_cycle(
                self.backend,
                self.root,
                agent_id,
                batch_size=1000,
                max_batches=5,
            )

        submitted = repository.ingest_agent_events.call_args.args[1]
        self.assertEqual([item["event_id"] for item in submitted], ["yara-1","fifo-0","fifo-1","fifo-2"])
        runtime_events.read_runtime_events_matching.assert_called_once_with(
            state,
            event_types=("YARAX_SCAN_STARTED","YARAX_SCAN_COMPLETED","YARAX_SCAN_FAILED"),
            limit=200,
        )
        self.assertEqual(result["accepted"], 4)

    def test_hybrid_content_events_are_ingested_before_yarax_admin_exchange(self):
        import inspect
        from hybrid_agent_worker import heartbeat_cycle

        source = inspect.getsource(heartbeat_cycle)
        self.assertLess(
            source.index("process_hybrid_content_cycle"),
            source.index("process_hybrid_runtime_event_cycle"),
        )
        self.assertLess(
            source.index("process_hybrid_runtime_event_cycle"),
            source.index("process_hybrid_yarax_admin_cycle"),
        )

    def test_hybrid_configuration_precedes_runtime_commands_and_uses_hybrid_materializer(self):
        import inspect
        from hybrid_agent_worker import _instance_runtime_module, heartbeat_cycle

        heartbeat_source = inspect.getsource(heartbeat_cycle)
        self.assertLess(
            heartbeat_source.index("process_hybrid_configuration_cycle"),
            heartbeat_source.index("process_hybrid_instance_runtime_cycle"),
        )
        loader_source = inspect.getsource(_instance_runtime_module)
        self.assertIn("CAPIVARA_MATERIALIZER_UNIT_TEMPLATE", loader_source)
        self.assertIn("dsm-hybrid-agent-materialize@{instance_id}.service", loader_source)

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
            agent_row = session.execute(
                "SELECT metadata_json FROM agents WHERE id=?",
                (transition["agent_id"],),
            ).fetchone()
        self.assertEqual(row["health_status"], "online")
        self.assertTrue(row["last_seen"])

        log_path = self.root / "runtime" / "hybrid-agent-state" / "agent-runtime.log"
        self.assertTrue(log_path.is_file())
        local_lines = log_path.read_text(encoding="utf-8").splitlines()
        self.assertTrue(any("hybrid heartbeat ok" in line for line in local_lines))
        self.assertTrue(any(transition["agent_id"] in line for line in local_lines))

        metadata = json.loads(agent_row["metadata_json"] or "{}")
        recent_logs = metadata.get("recent_logs") or []
        self.assertTrue(any("hybrid heartbeat ok" in line for line in recent_logs))
        self.assertTrue(any(transition["agent_id"] in line for line in recent_logs))
        self.assertEqual(second["published_log_lines"], len(recent_logs))

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
