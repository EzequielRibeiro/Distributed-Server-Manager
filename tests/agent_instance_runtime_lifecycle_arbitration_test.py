#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from agent_instance_runtime_repository import (
    AgentInstanceRuntimeRepository,
    InstanceLifecycleCommandConflict,
)
from agent_pairing_repository import AgentPairingRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class AgentInstanceRuntimeLifecycleArbitrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(Path(self.temp.name) / "capivara.db"),
            )
        )
        identity = installation_profile_identity(
            RegistryRepository(self.backend),
            profile="controller",
            hostname="lifecycle-arbitration-controller",
        )
        self.controller_id = str(identity["controller_id"])
        self.agent_id = "agent-lifecycle-test"
        self.node_id = "node-lifecycle-test"
        self.customer_id = 1
        pairing = AgentPairingRepository(self.backend)
        token = pairing.issue_token(controller_id=self.controller_id, created_by="test")
        pairing.enroll(
            pairing_token=token.token,
            agent_id=self.agent_id,
            node_id=self.node_id,
            name="Lifecycle Agent",
            fingerprint="sha256:lifecycle-agent-test",
            hostname="lifecycle-host",
            os_name="linux",
            architecture="x86_64",
            address="192.0.2.80",
        )
        self.instance_ids = ("instance-lifecycle-01", "instance-lifecycle-02")
        with self.backend.transaction() as connection:
            connection.execute("UPDATE agents SET status='active' WHERE id=?", (self.agent_id,))
            connection.execute("UPDATE nodes SET status='online' WHERE id=?", (self.node_id,))
            connection.execute(
                "INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)",
                (self.customer_id, self.controller_id, "Lifecycle Customer", "active"),
            )
            for index, instance_id in enumerate(self.instance_ids, start=1):
                connection.execute(
                    "INSERT INTO instances("
                    "id,node_id,game_id,name,status,controller_id,agent_id,customer_id"
                    ") VALUES(?,?,?,?,?,?,?,?)",
                    (
                        instance_id,
                        self.node_id,
                        "dayz",
                        f"Lifecycle {index}",
                        "offline",
                        self.controller_id,
                        self.agent_id,
                        self.customer_id,
                    ),
                )
        self.runtime = AgentInstanceRuntimeRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _enqueue(self, action: str, instance_id: str | None = None):
        return self.runtime.enqueue(
            agent_id=self.agent_id,
            instance_id=instance_id or self.instance_ids[0],
            action=action,
            requested_by="test",
        )

    def _lifecycle_count(self, instance_id: str | None = None) -> int:
        instance_id = instance_id or self.instance_ids[0]
        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM agent_instance_commands "
                "WHERE instance_id=? AND action IN ('start','stop','restart')",
                (instance_id,),
            ).fetchone()
        return int(row["n"])

    def _active_lifecycle_count(self, instance_id: str | None = None) -> int:
        instance_id = instance_id or self.instance_ids[0]
        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM agent_instance_commands "
                "WHERE instance_id=? AND action IN ('start','stop','restart') "
                "AND status IN ('queued','delivered')",
                (instance_id,),
            ).fetchone()
        return int(row["n"])

    def _finish(self, command: dict, status: str):
        payload = {
            "command_id": command["command_id"],
            "instance_id": command["instance_id"],
            "action": command["action"],
            "status": status,
            "result": {"observed_state": "running" if command["action"] != "stop" else "stopped"},
        }
        if status == "failed":
            payload["error"] = "expected test failure"
        return self.runtime.apply_result(self.agent_id, payload)

    def test_same_queued_action_reuses_command(self):
        first = self._enqueue("start")
        second = self._enqueue("start")
        self.assertEqual(second["command_id"], first["command_id"])
        self.assertEqual(self._lifecycle_count(), 1)

    def test_same_delivered_action_reuses_command(self):
        first = self._enqueue("restart")
        self.runtime.mark_delivered(first["command_id"])
        second = self._enqueue("restart")
        self.assertEqual(second["command_id"], first["command_id"])
        self.assertEqual(second["status"], "delivered")
        self.assertEqual(self._lifecycle_count(), 1)

    def test_different_action_conflicts_while_queued_or_delivered(self):
        for delivered in (False, True):
            with self.subTest(delivered=delivered):
                first = self._enqueue("start")
                if delivered:
                    self.runtime.mark_delivered(first["command_id"])
                with self.assertRaises(InstanceLifecycleCommandConflict) as raised:
                    self._enqueue("stop")
                conflict = raised.exception
                self.assertEqual(conflict.command_id, first["command_id"])
                self.assertEqual(conflict.active_action, "start")
                self.assertEqual(conflict.requested_action, "stop")
                self.assertEqual(conflict.as_dict()["error"], "lifecycle_operation_in_progress")
                self.assertEqual(self._active_lifecycle_count(), 1)
                self._finish(first, "completed")

    def test_completed_or_failed_command_releases_instance(self):
        for terminal_status in ("completed", "failed"):
            with self.subTest(terminal_status=terminal_status):
                first = self._enqueue("start")
                self._finish(first, terminal_status)
                second = self._enqueue("stop")
                self.assertNotEqual(second["command_id"], first["command_id"])
                self.assertEqual(second["action"], "stop")
                self._finish(second, "completed")

    def test_different_instances_are_independent_on_same_agent(self):
        first = self._enqueue("start", self.instance_ids[0])
        second = self._enqueue("stop", self.instance_ids[1])
        self.assertNotEqual(first["command_id"], second["command_id"])
        self.assertEqual(self._lifecycle_count(self.instance_ids[0]), 1)
        self.assertEqual(self._lifecycle_count(self.instance_ids[1]), 1)

    def test_concurrent_same_action_is_atomic_and_deduplicated(self):
        barrier = threading.Barrier(2)

        def enqueue_start():
            barrier.wait(timeout=5)
            repository = AgentInstanceRuntimeRepository(self.backend)
            return repository.enqueue(
                agent_id=self.agent_id,
                instance_id=self.instance_ids[0],
                action="start",
                requested_by="concurrent-test",
            )["command_id"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            command_ids = list(pool.map(lambda _: enqueue_start(), range(2)))

        self.assertEqual(command_ids[0], command_ids[1])
        self.assertEqual(self._lifecycle_count(), 1)

    def _enable_dayz_maintenance(self):
        from maintenance_repository import MaintenanceRepository
        from dayz_native_restart_repository import DayZNativeRestartRepository
        policy = MaintenanceRepository(self.backend)
        policy.set_policy(self.instance_ids[0], {
            "enabled": True, "schedule_mode": "interval",
            "interval_seconds": 28800,
            "warning_offsets_seconds": [],
            "broadcast_enabled": False,
        })
        return policy, DayZNativeRestartRepository(self.backend)

    def test_dayz_start_waits_for_native_agent_ack_and_due_alignment(self):
        from datetime import datetime, timezone
        policy, native = self._enable_dayz_maintenance()
        start = self._enqueue("start")
        self.assertIsNone(self.runtime.command_for_agent(self.agent_id))
        issued = native.command_for_agent(self.agent_id)
        self.assertIsNotNone(issued)
        self.assertEqual(str(issued["instance_id"]), self.instance_ids[0])
        due = policy.snapshot(self.instance_ids[0])["state"]["next_due_at"]
        self.assertEqual(
            datetime.fromisoformat(str(issued["due_at"]).replace("Z","+00:00")),
            datetime.fromisoformat(str(due).replace("Z","+00:00")),
        )
        self.assertIsNone(self.runtime.command_for_agent(self.agent_id))
        native.apply_result(self.agent_id, {
            "command_id": issued["command_id"],
            "instance_id": self.instance_ids[0],
            "status": "completed",
            "result": {"kind": "CapivaraDayZNativeRestartPrepared",
                       "materialized": True, "due_at": issued["due_at"]},
        })
        dispatched = self.runtime.command_for_agent(self.agent_id)
        self.assertEqual(dispatched["command_id"], start["command_id"])
        self.assertEqual(dispatched["action"], "start")
        self.assertEqual(self.runtime.snapshot(start["command_id"])["status"], "queued")
        self.assertEqual(self._lifecycle_count(), 1)

    def test_waiting_bootstrap_does_not_starve_unrelated_instance(self):
        self._enable_dayz_maintenance()
        waiting = self._enqueue("start", self.instance_ids[0])
        unrelated = self._enqueue("status", self.instance_ids[1])
        dispatched = self.runtime.command_for_agent(self.agent_id)
        self.assertEqual(dispatched["command_id"], unrelated["command_id"])
        self.assertEqual(dispatched["action"], "status")
        self.assertEqual(self.runtime.snapshot(waiting["command_id"])["status"], "queued")
        from dayz_native_restart_repository import DayZNativeRestartRepository
        native = DayZNativeRestartRepository(self.backend)
        self.assertIsNotNone(native.command_for_agent(self.agent_id))

    def test_failed_native_preparation_blocks_start_and_releases_command(self):
        _, native = self._enable_dayz_maintenance()
        start = self._enqueue("start")
        self.assertIsNone(self.runtime.command_for_agent(self.agent_id))
        issued = native.command_for_agent(self.agent_id)
        native.apply_result(self.agent_id, {
            "command_id": issued["command_id"], "instance_id": self.instance_ids[0],
            "status": "failed", "error": "Agent confirmed server already running",
        })
        self.assertIsNone(self.runtime.command_for_agent(self.agent_id))
        status = self.runtime.snapshot(start["command_id"])
        self.assertEqual(status["status"], "failed")
        self.assertIn("already running", status["last_error"])
        self.assertEqual(self._active_lifecycle_count(), 0)

    def test_native_bootstrap_rejects_mismatched_success_payload(self):
        _, native = self._enable_dayz_maintenance()
        start = self._enqueue("start")
        self.assertIsNone(self.runtime.command_for_agent(self.agent_id))
        issued = native.command_for_agent(self.agent_id)
        native.apply_result(self.agent_id, {
            "command_id": issued["command_id"], "instance_id": self.instance_ids[0],
            "status": "completed",
            "result": {"kind": "CapivaraDayZNativeRestartPrepared",
                       "materialized": True, "due_at": "2026-01-01T01:00:00Z"},
        })
        self.assertIsNone(self.runtime.command_for_agent(self.agent_id))
        state = self.runtime.snapshot(start["command_id"])
        self.assertEqual(state["status"], "failed")
        self.assertIn("mismatched", state["last_error"])

    def test_native_bootstrap_pending_start_has_a_bounded_deadline(self):
        from datetime import datetime, timedelta, timezone
        self._enable_dayz_maintenance()
        start = self._enqueue("start")
        with self.backend.transaction() as connection:
            connection.execute(
                "UPDATE agent_instance_commands SET created_at=? WHERE command_id=?",
                ((datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(), start["command_id"]),
            )
        self.assertIsNone(self.runtime.command_for_agent(self.agent_id))
        state = self.runtime.snapshot(start["command_id"])
        self.assertEqual(state["status"], "failed")
        self.assertIn("within 5 minutes", state["last_error"])

    def test_two_agents_prepare_independently_without_cross_delivery(self):
        from maintenance_repository import MaintenanceRepository
        from dayz_native_restart_repository import DayZNativeRestartRepository
        other_agent = "agent-lifecycle-second"
        other_node = "node-lifecycle-second"
        other_instance = "instance-other-agent"
        pairing = AgentPairingRepository(self.backend)
        token = pairing.issue_token(controller_id=self.controller_id, created_by="test")
        pairing.enroll(
            pairing_token=token.token, agent_id=other_agent, node_id=other_node,
            name="Second Agent", fingerprint="sha256:lifecycle-second-agent",
            hostname="second-lifecycle-host", os_name="linux", architecture="x86_64",
            address="192.0.2.81",
        )
        with self.backend.transaction() as connection:
            connection.execute("UPDATE agents SET status='active' WHERE id=?", (other_agent,))
            connection.execute("UPDATE nodes SET status='online' WHERE id=?", (other_node,))
            connection.execute(
                "INSERT INTO instances("
                "id,node_id,game_id,name,status,controller_id,agent_id,customer_id"
                ") VALUES(?,?,?,?,?,?,?,?)",
                (other_instance, other_node, "dayz", "Second Agent DayZ",
                 "offline", self.controller_id, other_agent, self.customer_id),
            )
        maintenance = MaintenanceRepository(self.backend)
        options = {
            "enabled": True, "schedule_mode": "interval",
            "interval_seconds": 28800, "warning_offsets_seconds": [],
            "broadcast_enabled": False,
        }
        maintenance.set_policy(self.instance_ids[0], options)
        maintenance.set_policy(other_instance, options)
        native = DayZNativeRestartRepository(self.backend)
        first_start = self._enqueue("start")
        second_start = self.runtime.enqueue(
            agent_id=other_agent, instance_id=other_instance,
            action="start", requested_by="test",
        )

        self.assertIsNone(self.runtime.command_for_agent(self.agent_id))
        self.assertIsNone(self.runtime.command_for_agent(other_agent))
        first = native.command_for_agent(self.agent_id)
        second = native.command_for_agent(other_agent)
        self.assertEqual(first["instance_id"], self.instance_ids[0])
        self.assertEqual(second["instance_id"], other_instance)
        self.assertNotEqual(first["command_id"], second["command_id"])

        second_ack = {
            "command_id": second["command_id"], "instance_id": other_instance,
            "status": "completed", "result": {
                "kind": "CapivaraDayZNativeRestartPrepared",
                "materialized": True, "due_at": second["due_at"],
            },
        }
        with self.assertRaises(PermissionError):
            native.apply_result(self.agent_id, second_ack)

        first_ack = {
            "command_id": first["command_id"], "instance_id": self.instance_ids[0],
            "status": "completed", "result": {
                "kind": "CapivaraDayZNativeRestartPrepared",
                "materialized": True, "due_at": first["due_at"],
            },
        }
        native.apply_result(self.agent_id, first_ack)
        self.assertEqual(
            self.runtime.command_for_agent(self.agent_id)["command_id"],
            first_start["command_id"],
        )
        self.assertIsNone(self.runtime.command_for_agent(other_agent))
        native.apply_result(other_agent, second_ack)
        self.assertEqual(
            self.runtime.command_for_agent(other_agent)["command_id"],
            second_start["command_id"],
        )

    def test_schedule_changed_with_old_native_command_fails_closed(self):
        from maintenance_repository import MaintenanceRepository
        maintenance, native = self._enable_dayz_maintenance()
        start = self._enqueue("start")
        self.assertIsNone(self.runtime.command_for_agent(self.agent_id))
        old = native.command_for_agent(self.agent_id)
        old_due = old["due_at"]

        maintenance.set_policy(self.instance_ids[0], {
            "enabled": True, "schedule_mode": "interval",
            "interval_seconds": 14400, "warning_offsets_seconds": [],
            "broadcast_enabled": False,
        })
        from datetime import datetime, timezone
        new_due = maintenance.snapshot(self.instance_ids[0])["state"]["next_due_at"]
        old_utc = datetime.fromisoformat(str(old_due).replace("Z","+00:00")).astimezone(timezone.utc)
        new_utc = datetime.fromisoformat(str(new_due).replace("Z","+00:00")).astimezone(timezone.utc)
        self.assertNotEqual(new_utc, old_utc)
        self.assertLess(new_utc, old_utc)
        # The old command must never authorize the reconfigured schedule.
        self.assertIsNone(self.runtime.command_for_agent(self.agent_id))
        state = self.runtime.snapshot(start["command_id"])
        self.assertEqual(state["status"], "failed")
        self.assertIn("bootstrap blocked", state["last_error"])
        self.assertEqual(self._active_lifecycle_count(), 0)
        self.assertEqual(native.snapshot(old["command_id"])["status"], "queued")

    def test_no_maintenance_policy_retains_normal_lifecycle_delivery(self):
        start = self._enqueue("start")
        dispatched = self.runtime.command_for_agent(self.agent_id)
        self.assertEqual(dispatched["command_id"], start["command_id"])
        self.assertEqual(dispatched["action"], "start")

    def test_maintenance_worker_start_keeps_its_existing_ordering(self):
        self._enable_dayz_maintenance()
        start = self.runtime.enqueue(
            agent_id=self.agent_id, instance_id=self.instance_ids[0],
            action="start", requested_by="maintenance-worker",
        )
        dispatched = self.runtime.command_for_agent(self.agent_id)
        self.assertEqual(dispatched["command_id"], start["command_id"])

    def test_remove_deduplication_is_preserved(self):
        first = self._enqueue("remove")
        second = self._enqueue("remove")
        self.assertEqual(second["command_id"], first["command_id"])


if __name__ == "__main__":
    unittest.main()
