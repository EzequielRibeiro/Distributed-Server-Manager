#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "database", ROOT / "dashboard" / "workers"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from observability_repository import ObservabilityRepository
from observability_retention_worker import ObservabilityRetentionWorker
from artifact_transfer_repository import ArtifactTransferRepository


class ObservabilityRetentionWorkerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        self.backend.initialize()
        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO nodes(id,name,role) VALUES (?,?,?)",
                ("node-controller", "Controller", "controller"),
            )
            connection.execute(
                "INSERT INTO nodes(id,name,role) VALUES (?,?,?)",
                ("node-agent", "Agent", "agent"),
            )
            connection.execute(
                "INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",
                ("controller-c3", "node-controller", "C3"),
            )
            connection.execute(
                "INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",
                ("agent-c3", "controller-c3", "node-agent", "Agent C3", "active"),
            )
            customer = connection.execute(
                "INSERT INTO customers(controller_id,name) VALUES (?,?)",
                ("controller-c3", "Retention Customer"),
            )
            self.customer_id = int(customer.lastrowid)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_worker_prunes_in_bounded_batches(self):
        repo = ObservabilityRepository(self.backend, history_interval_seconds=60)
        for minute in range(6):
            repo.ingest_agent_samples(
                "agent-c3",
                [{
                    "metric_name": "system.load.1",
                    "value": float(minute),
                    "unit": "load",
                    "collected_at": f"2026-09-01T00:0{minute}:00Z",
                }],
            )
        worker = ObservabilityRetentionWorker(self.backend, retention_days=7, batch_size=100)
        report = worker.tick(datetime(2026, 9, 20, tzinfo=timezone.utc))
        self.assertEqual(report["pending"], 6)
        self.assertEqual(report["deleted"], 6)
        self.assertEqual(repo.count_before("2026-09-13T00:00:00Z"), 0)


    def _expired_upload(self, repo, suffix):
        instance_id = "instance-"+suffix
        with self.backend.transaction() as connection:
            connection.execute(
                 "INSERT OR IGNORE INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",
                (instance_id,"node-agent","minecraft","Retention "+suffix,"stopped","controller-c3","agent-c3",self.customer_id),
            )
        item = repo.create(
            agent_id="agent-c3",
            instance_id=instance_id,
            customer_id=None,
            direction="controller_to_agent",
            purpose="content_upload",
            filename="pack.zip",
            ttl_hours=1,
        )
        destination = f"quarantine/instance-{suffix}/{item['transfer_id']}/pack.zip"
        with self.backend.transaction() as connection:
            connection.execute(
                "UPDATE artifact_transfers SET status=?,destination_ref=?,expires_at=? WHERE transfer_id=?",
                ("expired", destination, "2000-01-01T00:00:00Z", item["transfer_id"]),
            )
        return repo.get(item["transfer_id"])

    def _assignment_reference(self, transfer_id, *, historical=False):
        now = "2026-10-03T00:00:00Z"
        provenance = '{"transfer_id":"'+transfer_id+'"}'
        with self.backend.transaction() as connection:
            if historical:
                connection.execute(
                    """INSERT INTO content_assignment_revisions(
                       assignment_id,revision,desired_state,version,provider,target,
                       artifact_json,provenance_json,dependencies_json,conflicts_json,
                       checksum,requested_by,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    ("assignment-history",1,"installed","1","local","external/pack",
                     "{}",provenance,"[]","[]","checksum","tester",now),
                )
            else:
                connection.execute(
                    """INSERT INTO content_assignments(
                       assignment_id,instance_id,agent_id,content_id,game_id,content_type,
                       desired_state,version,provider,target,artifact_json,provenance_json,
                       dependencies_json,conflicts_json,revision,checksum,requested_by,
                       created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    ("assignment-current","instance-current","agent-c3","pack","minecraft",
                     "modpack","installed","1","local","external/pack","{}",provenance,
                     "[]","[]",1,"checksum","tester",now,now),
                )

    def test_expired_unreferenced_upload_queues_agent_quarantine_cleanup(self):
        root = Path(self.temp.name) / "dsm-cleanup"
        repo = ArtifactTransferRepository(self.backend, root)
        repo.initialize()
        original = self._expired_upload(repo, "orphan")

        self.assertEqual(repo.enqueue_expired_content_upload_cleanup(), 1)
        command = repo.command_for_agent("agent-c3")
        self.assertEqual(command["purpose"], "content_upload_cleanup")
        self.assertEqual(command["source_ref"], original["transfer_id"])
        self.assertEqual(command["instance_id"], "instance-orphan")

    def test_expired_upload_with_current_assignment_reference_is_preserved(self):
        root = Path(self.temp.name) / "dsm-current"
        repo = ArtifactTransferRepository(self.backend, root)
        repo.initialize()
        original = self._expired_upload(repo, "current")
        self._assignment_reference(original["transfer_id"])

        self.assertEqual(repo.enqueue_expired_content_upload_cleanup(), 0)
        self.assertIsNone(repo.command_for_agent("agent-c3"))

    def test_expired_upload_with_historical_assignment_reference_is_preserved(self):
        root = Path(self.temp.name) / "dsm-history"
        repo = ArtifactTransferRepository(self.backend, root)
        repo.initialize()
        original = self._expired_upload(repo, "history")
        self._assignment_reference(original["transfer_id"], historical=True)

        self.assertEqual(repo.enqueue_expired_content_upload_cleanup(), 0)
        self.assertIsNone(repo.command_for_agent("agent-c3"))

    def test_artifact_cleanup_removes_only_expired_spool_files(self):
        root = Path(self.temp.name) / "dsm"
        repo = ArtifactTransferRepository(self.backend, root)
        repo.initialize()
        expired = repo.create(
            agent_id="agent-c3",
            instance_id=None,
            customer_id=None,
            direction="controller_to_agent",
            purpose="content_upload",
            filename="expired.zip",
            ttl_hours=1,
        )
        active = repo.create(
            agent_id="agent-c3",
            instance_id=None,
            customer_id=None,
            direction="controller_to_agent",
            purpose="content_upload",
            filename="active.zip",
            ttl_hours=24,
        )
        expired_path = Path(expired["controller_path"])
        active_path = Path(active["controller_path"])
        expired_path.parent.mkdir(parents=True, exist_ok=True)
        active_path.parent.mkdir(parents=True, exist_ok=True)
        expired_path.write_bytes(b"expired")
        active_path.write_bytes(b"active")
        with self.backend.transaction() as connection:
            connection.execute(
                "UPDATE artifact_transfers SET expires_at=? WHERE transfer_id=?",
                ("2000-01-01T00:00:00Z", expired["transfer_id"]),
            )

        self.assertEqual(repo.cleanup_expired(), 1)
        self.assertFalse(expired_path.exists())
        self.assertTrue(active_path.exists())
        self.assertEqual(repo.get(expired["transfer_id"])["status"], "expired")
        self.assertNotEqual(repo.get(active["transfer_id"])["status"], "expired")


if __name__ == "__main__":
    unittest.main()
