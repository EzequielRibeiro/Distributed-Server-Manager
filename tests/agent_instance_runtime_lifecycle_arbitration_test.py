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
            for index, instance_id in enumerate(self.instance_ids, start=1):
                connection.execute(
                    "INSERT INTO instances("
                    "id,node_id,name,game_id,status,agent_id,runtime_adapter,runtime_root,runtime_account,created_at,updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        instance_id,
                        self.node_id,
                        f"Lifecycle {index}",
                        "dayz",
                        "online",
                        self.agent_id,
                        "dayz",
                        f"/srv/capivara/{instance_id}",
                        "capivara",
                        "2026-09-12T00:00:00Z",
                        "2026-09-12T00:00:00Z",
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
                self.assertEqual(self._lifecycle_count(), 1)
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

    def test_remove_deduplication_is_preserved(self):
        first = self._enqueue("remove")
        second = self._enqueue("remove")
        self.assertEqual(second["command_id"], first["command_id"])


if __name__ == "__main__":
    unittest.main()
