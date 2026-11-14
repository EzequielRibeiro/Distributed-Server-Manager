#!/usr/bin/env python3
"""Disposable large backup stream: Controller -> Agent progress and ACK gating."""
from __future__ import annotations
import hashlib
import io
import json
import sys
import tarfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "dashboard", ROOT / "database", ROOT / "agents/linux/runtime"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from backend import DatabaseConfig
from backend_factory import create_backend
from artifact_transfer_repository import ArtifactTransferRepository
from artifact_transfer_http import install_artifact_transfer_http
from agent_pairing_repository import AgentPairingRepository
import artifact_transfer_client as client


class BackupControllerAgentDeliveryProgressTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dsm-backup-progress-")
        self.root = Path(self.temp.name)
        self.ctrl = self.root / "controller"
        self.ctrl.mkdir()
        self.backend = create_backend(DatabaseConfig(
            driver="sqlite", database=str(self.root / "controller.db")
        ))
        self.backend.initialize()
        with self.backend.transaction() as db:
            db.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",
                       ("node-c", "Controller", "controller"))
            db.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",
                       ("node-a", "Agent", "agent"))
            db.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",
                       ("ctrl", "node-c", "Controller"))
            db.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",
                       ("agent-a", "ctrl", "node-a", "Agent", "active"))
            customer = db.execute(
                "INSERT INTO customers(controller_id,name) VALUES (?,?)",
                ("ctrl", "Sandbox Customer"),
            )
            db.execute("INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",
                       ("dayz-sandbox", "node-a", "dayz", "Isolated DayZ", "stopped", "ctrl", "agent-a", customer.lastrowid))
        self.repo = ArtifactTransferRepository(self.backend, self.ctrl)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _create_import(self, size=10 * 1024 * 1024):
        # Uncompressed valid tar; real binary content streamed with >2 checkpoints.
        archive = self.root / "synthetic-dayz-backup.tar"
        with tarfile.open(archive, "w") as tar:
            data = b"D" * size
            member = tarfile.TarInfo("synthetic-state/test-marker.txt")
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
        item = self.repo.create(
            agent_id="agent-a", instance_id="dayz-sandbox",
            direction="controller_to_agent", purpose="backup_import",
            filename=archive.name, destination_ref="import-synthetic",
            requested_by="sandbox",
        )
        with archive.open("rb") as stream:
            staged = self.repo.stage_from_controller(
                item["transfer_id"], stream, archive.stat().st_size,
            )
        return staged, archive

    def test_large_backup_progress_is_observed_but_not_marked_complete_until_agent_ack(self):
        item, archive = self._create_import()
        cmd = self.repo.command_for_agent("agent-a")
        self.assertEqual(cmd["transfer_id"], item["transfer_id"])
        observations = []
        real_method = ArtifactTransferRepository.record_controller_delivery_progress

        def spy(repository, transfer_id, agent_id, amount):
            state = real_method(repository, transfer_id, agent_id, amount)
            observations.append((state["status"], state["transferred_bytes"]))
            return state

        backend = self.backend
        class Legacy:
            DSM_ROOT = self.ctrl
            DATABASE_FILE = str(self.root / "controller.db")
            dashboard_repository = staticmethod(
                lambda _path: SimpleNamespace(backend=backend)
            )

            class DashboardHandler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def send_json(self, status, value):
                    content = json.dumps(value).encode("utf-8")
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)

                def do_GET(self):
                    self.send_json(404, {"error": "not_found"})

                def do_POST(self):
                    self.send_json(404, {"error": "not_found"})

        install_artifact_transfer_http(Legacy, lambda _headers: None)

        def authenticate(_self, credential_id, credential_secret, fingerprint):
            return ({"agent_id": "agent-a"} if
                    (credential_id, credential_secret, fingerprint) ==
                    ("test-id", "test-secret", "test-fingerprint") else None)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Legacy.DashboardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config = {
                "controller_url": f"http://127.0.0.1:{server.server_port}",
                "credential_id": "test-id",
                "credential_secret": "test-secret",
                "fingerprint": "test-fingerprint",
            }
            with (
                patch.object(AgentPairingRepository, "authenticate", authenticate),
                patch.object(ArtifactTransferRepository, "record_controller_delivery_progress", spy),
                patch.object(client, "BACKUPS", self.root / "agent-backups"),
                patch.object(client, "RESULT", self.root / "agent-results"),
            ):
                result = client.handle_command(config, cmd)
            self.assertEqual(result["status"], "completed", result)
            destination = self.root / "agent-backups" / "dayz-sandbox" / "import-synthetic.tar"
            self.assertEqual(destination.read_bytes(), archive.read_bytes())
            self.assertEqual(result["transferred_bytes"], archive.stat().st_size)
            self.assertGreaterEqual(len(observations), 3)
            self.assertTrue(all(state == "transferring" for state, _ in observations))
            self.assertEqual([count for _, count in observations],
                             sorted(count for _, count in observations))
            self.assertEqual(observations[-1][1], archive.stat().st_size)
            still_pending = self.repo.get(item["transfer_id"])
            self.assertEqual(still_pending["status"], "transferring")
            self.assertEqual(still_pending["transferred_bytes"], still_pending["size_bytes"])
            finished = self.repo.apply_agent_result("agent-a", result)
            self.assertEqual(finished["status"], "completed")
            self.assertEqual(finished["sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_progress_guard_and_failure_preserve_observed_bytes(self):
        item, _archive = self._create_import(size=2 * 1024 * 1024)
        tid = item["transfer_id"]
        self.repo.command_for_agent("agent-a")
        self.repo.mark_transferring(tid)
        observed = self.repo.record_controller_delivery_progress(tid, "agent-a", 12345)
        self.assertEqual(observed["transferred_bytes"], 12345)
        lower = self.repo.record_controller_delivery_progress(tid, "agent-a", 50)
        self.assertEqual(lower["transferred_bytes"], 12345)
        with self.assertRaises(PermissionError):
            self.repo.record_controller_delivery_progress(tid, "another-agent", 20000)
        with self.assertRaises(ValueError):
            self.repo.record_controller_delivery_progress(tid, "agent-a", int(item["size_bytes"]) + 1)
        failed = self.repo.apply_agent_result("agent-a", {
            "transfer_id": tid, "status": "failed", "error": "simulated checksum failure",
        })
        self.assertEqual(failed["transferred_bytes"], 12345)
        self.assertEqual(failed["status"], "failed")
        unchanged = self.repo.record_controller_delivery_progress(tid, "agent-a", 54321)
        self.assertEqual(unchanged["transferred_bytes"], 12345)


if __name__ == "__main__":
    unittest.main()
