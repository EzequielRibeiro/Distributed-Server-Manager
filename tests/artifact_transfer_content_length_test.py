#!/usr/bin/env python3
"""Regression tests for bounded artifact HTTP-body streaming."""
from __future__ import annotations

import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT / "database", ROOT / "dashboard"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from artifact_transfer_repository import ArtifactTransferRepository
from backend import DatabaseConfig
from backend_factory import create_backend


class StrictContentLengthStream(io.BytesIO):
    """Fail if a reader asks past the bytes left in the HTTP request body."""

    def read(self, size=-1):
        remaining = len(self.getbuffer()) - self.tell()
        if remaining and size > remaining:
            raise AssertionError(
                f"read({size}) exceeds declared body remainder {remaining}"
            )
        return super().read(size)


class ArtifactTransferContentLengthTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "dsm"
        self.root.mkdir()
        self.backend = create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(Path(self.temp.name) / "capivara.db"),
            )
        )
        self.repo = ArtifactTransferRepository(self.backend, self.root)
        self.repo.initialize()
        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO nodes(id,name,role) VALUES (?,?,?)",
                ("controller-node", "Controller", "controller"),
            )
            connection.execute(
                "INSERT INTO nodes(id,name,role) VALUES (?,?,?)",
                ("agent-node", "Agent", "agent"),
            )
            connection.execute(
                "INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",
                ("controller-1", "controller-node", "Controller"),
            )
            connection.execute(
                "INSERT INTO agents(id,controller_id,node_id,name,status) "
                "VALUES (?,?,?,?,?)",
                ("agent-1", "controller-1", "agent-node", "Agent", "active"),
            )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    @staticmethod
    def payload():
        return (b"c" * (1024 * 1024)) + (b"tail" * 9647)

    def test_controller_upload_reads_only_declared_remaining_bytes(self):
        payload = self.payload()
        item = self.repo.create(
            agent_id="agent-1",
            direction="controller_to_agent",
            purpose="backup_import",
            filename="external.tar.gz",
        )
        saved = self.repo.stage_from_controller(
            item["transfer_id"],
            StrictContentLengthStream(payload),
            content_length=len(payload),
        )

        self.assertEqual("queued", saved["status"])
        self.assertEqual(len(payload), saved["size_bytes"])
        self.assertEqual(hashlib.sha256(payload).hexdigest(), saved["sha256"])
        self.assertEqual(
            payload,
            Path(saved["controller_path"]).read_bytes(),
        )

    def test_agent_upload_reads_only_declared_remaining_bytes(self):
        payload = self.payload()
        item = self.repo.create(
            agent_id="agent-1",
            direction="agent_to_controller",
            purpose="backup_export",
            filename="backup.tar.gz",
        )
        saved = self.repo.receive_from_agent(
            item["transfer_id"],
            "agent-1",
            StrictContentLengthStream(payload),
            content_length=len(payload),
        )

        self.assertEqual("completed", saved["status"])
        self.assertEqual(len(payload), saved["transferred_bytes"])
        self.assertEqual(hashlib.sha256(payload).hexdigest(), saved["sha256"])

    def test_short_body_is_rejected_and_partial_file_is_removed(self):
        payload = b"short-body"
        item = self.repo.create(
            agent_id="agent-1",
            direction="controller_to_agent",
            purpose="backup_import",
            filename="external.tar.gz",
        )
        with self.assertRaisesRegex(ValueError, "content length mismatch"):
            self.repo.stage_from_controller(
                item["transfer_id"],
                io.BytesIO(payload),
                content_length=len(payload) + 7,
            )

        path = Path(item["controller_path"])
        self.assertFalse(path.exists())
        self.assertFalse(path.with_suffix(path.suffix + ".part").exists())


if __name__ == "__main__":
    unittest.main()
