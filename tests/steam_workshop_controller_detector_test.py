#!/usr/bin/env python3
"""Safety regressions for opt-in Steam Workshop update detection."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "core", ROOT / "database", ROOT / "dashboard", ROOT / "dashboard/workers"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from content_update_detector import ControllerContentUpdateDetector, _workshop_observation
from backend import DatabaseConfig
from backend_factory import create_backend
from content_repository import ContentRepository
from server_update_repository import ServerUpdateRepository
from content_update_dispatch_repository import ContentUpdateDispatchRepository
from content_update_worker import ContentUpdateWorker
from hybrid_agent_worker import process_hybrid_content_cycle


def assignment():
    return {
        "instance_id": "dayz-1",
        "agent_id": "agent-1",
        "content_id": "steam-workshop:2289456201",
        "provider": "steam-workshop",
        "content_type": "workshop",
        "desired_state": "installed",
        "revision": 1,
        "checksum": "checksum-1",
        "artifact": {"package_id": "221100:2289456201"},
    }


def applied():
    return {
        "status": "applied",
        "applied_revision": 1,
        "applied_checksum": "checksum-1",
        "installed_version": "1740499952",
    }


def resolve(_published_id, *, expected_app_id):
    assert expected_app_id == "221100"
    return {"metadata": {"time_updated": "1792603787"}}


class Content:
    def __init__(self, state=None):
        self.state = applied() if state is None else state

    def initialize(self):
        pass

    def list(self, **_kwargs):
        return [assignment()]

    def agent_state_for_instance(self, _iid):
        return {"steam-workshop:2289456201": self.state}


class Repository:
    def __init__(self):
        self.items = []

    def initialize(self):
        pass

    def record_content_update_inventory(self, _agent_id, payload):
        self.items += payload["content"]


class DetectorTest(unittest.TestCase):
    def make_detector(self, state=None):
        repo = Repository()
        detector = ControllerContentUpdateDetector(
            None, ROOT, content=Content(state), instances=Repository(),
            state=repo, workshop_resolver=resolve,
        )
        return detector, repo

    def test_disabled_by_default(self):
        detector, repo = self.make_detector()
        with patch.dict(os.environ, {}, clear=True):
            report = detector.scan(force=True)
        self.assertEqual(report["checked"], 0)
        self.assertEqual(repo.items, [])

    def test_detects_update_using_applied_revision(self):
        detector, repo = self.make_detector()
        with patch.dict(os.environ, {"DSM_WORKSHOP_UPDATE_DETECTION_ENABLED": "1"}):
            report = detector.scan(force=True)
        self.assertEqual(report["available"], 1)
        self.assertEqual(repo.items[0]["installed_revision"], "1740499952")
        self.assertEqual(repo.items[0]["available_revision"], "1792603787")
        self.assertEqual(repo.items[0]["state"], "update_available")

    def test_pending_assignment_never_dispatches(self):
        state = {**applied(), "applied_revision": 0}
        detector, repo = self.make_detector(state)
        with patch.dict(os.environ, {"DSM_WORKSHOP_UPDATE_DETECTION_ENABLED": "1"}):
            report = detector.scan(force=True)
        self.assertEqual(report["skipped"], 1)
        self.assertEqual(repo.items, [])

    def test_upstream_failure_is_visible_not_update_available(self):
        detector, repo = self.make_detector()
        def fail(*_args, **_kwargs):
            raise RuntimeError("Steam API unavailable")
        detector.workshop_resolver = fail
        with patch.dict(os.environ, {"DSM_WORKSHOP_UPDATE_DETECTION_ENABLED": "1"}):
            report = detector.scan(force=True)
        self.assertEqual(report["failed"], 1)
        self.assertEqual(repo.items[0]["state"], "probe_failed")

    def test_invalid_applied_revision(self):
        with self.assertRaises(ValueError):
            _workshop_observation(assignment(), {**applied(), "installed_version": "latest"}, resolver=resolve)



class WorkshopInventorySQLiteIntegrationTest(unittest.TestCase):
    """Real inventory persistence and dispatch-policy selection in an isolated SQLite database."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(
            driver="sqlite", database=str(Path(self.tmp.name) / "controller.sqlite")
        ))
        self.backend.initialize()
        with self.backend.transaction() as connection:
            connection.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",
                               ("ctrl-node","Controller","controller"))
            connection.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",
                               ("agent-node","Agent","agent"))
            connection.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",
                               ("ctrl","ctrl-node","Controller"))
            connection.execute(
                "INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",
                ("agent-1","ctrl","agent-node","Agent","active"),
            )
            customer = connection.execute(
                "INSERT INTO customers(controller_id,name) VALUES (?,?)",("ctrl","Customer")
            )
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) "
                "VALUES (?,?,?,?,?,?,?,?)",
                ("dayz-1","agent-node","dayz","DayZ","stopped","ctrl","agent-1",customer.lastrowid),
            )
        self.content = ContentRepository(self.backend)
        self.state = ServerUpdateRepository(self.backend)
        self.dispatch = ContentUpdateDispatchRepository(self.backend)
        self.content.initialize()
        self.state.initialize()
        self.dispatch.initialize()
        self.current = self.content.put({
            "instance_id": "dayz-1",
            "content_id": "steam-workshop:2289456201",
            "content_type": "workshop",
            "provider": "steam-workshop",
            "version": "1740499952",
            "desired_state": "installed",
            "artifact": {"provider": "steam-workshop", "package_id": "221100:2289456201"},
        })["assignment"]
        self.content.record_agent_state("agent-1", [{
            "instance_id": "dayz-1",
            "content_id": "steam-workshop:2289456201",
            "desired_revision": self.current["revision"],
            "applied_revision": self.current["revision"],
            "desired_checksum": self.current["checksum"],
            "applied_checksum": self.current["checksum"],
            "status": "applied",
            "installed_version": "1740499952",
            "security_state": "clean",
        }])

    def tearDown(self):
        self.backend.close()
        self.tmp.cleanup()

    def scan(self):
        detector = ControllerContentUpdateDetector(
            self.backend, ROOT, content=self.content, state=self.state, workshop_resolver=resolve
        )
        with patch.dict(os.environ, {"DSM_WORKSHOP_UPDATE_DETECTION_ENABLED": "1"}):
            return detector.scan(force=True)

    def _worker(self, *, resolved_version="1792603787"):
        repository = self.content

        class SimulatedCanonicalService:
            content = repository

            def mutate(self, user, instance_id, content_id, action, body):
                assert user["role"] == "admin"
                assert action == "update"
                assert body == {}
                repository.put({
                    "instance_id": instance_id,
                    "content_id": content_id,
                    "content_type": "workshop",
                    "provider": "steam-workshop",
                    "version": resolved_version,
                    "desired_state": "installed",
                    "artifact": {
                        "provider": "steam-workshop",
                        "package_id": "221100:2289456201",
                    },
                }, requested_by="sandbox-test")

        class NoScan:
            def scan(self, **_kwargs):
                return {"checked": 0, "available": 0, "current": 0, "failed": 0, "skipped": 0}

        return ContentUpdateWorker(
            self.backend, ROOT, repository=self.dispatch,
            service=SimulatedCanonicalService(), detector=NoScan(),
        )

    def test_worker_dispatch_creates_versioned_assignment_and_dedupes(self):
        self.assertEqual(self.scan()["available"], 1)
        self.state.set_content_policy(
            instance_id="dayz-1", content_id="steam-workshop:2289456201",
            mode="automatic", requested_by="test",
        )
        report = self._worker().tick()
        self.assertEqual((report["due"], report["claimed"], report["updated"], report["failed"]),
                         (1, 1, 1, 0))
        current = self.content.get("dayz-1", "steam-workshop:2289456201")
        self.assertEqual(current["version"], "1792603787")
        self.assertEqual(current["revision"], self.current["revision"] + 1)
        self.assertEqual(self.dispatch.due(), [])
        # The isolated Agent has not applied the new desired revision.
        self.assertEqual(self.content.agent_state_for_instance("dayz-1")[
            "steam-workshop:2289456201"]["applied_revision"], self.current["revision"])

    def test_worker_rejects_wrong_upstream_revision_and_preserves_rollback(self):
        self.assertEqual(self.scan()["available"], 1)
        self.state.set_content_policy(
            instance_id="dayz-1", content_id="steam-workshop:2289456201",
            mode="automatic", requested_by="test",
        )
        result = self._worker(resolved_version="1792523756").tick()
        self.assertEqual((result["claimed"], result["updated"], result["failed"]), (1, 0, 1))
        with self.backend.connect() as conn:
            error = conn.execute(
                "SELECT dispatch_error FROM content_update_state"
            ).fetchone()[0]
        self.assertIn("does not match detected upstream revision", error)
        before = self.content.get("dayz-1", "steam-workshop:2289456201")
        self.assertGreater(before["revision"], self.current["revision"])
        restored = self.content.rollback(
            "dayz-1", "steam-workshop:2289456201", self.current["revision"],
            requested_by="test", reason="revision mismatch",
        )["assignment"]
        self.assertEqual(restored["version"], "1740499952")
        self.assertGreater(restored["revision"], before["revision"])

    def test_hybrid_agent_roundtrip_records_new_applied_version(self):
        self.assertEqual(self.scan()["available"], 1)
        self.state.set_content_policy(
            instance_id="dayz-1", content_id="steam-workshop:2289456201",
            mode="automatic", requested_by="test",
        )
        self.assertEqual(self._worker().tick()["updated"], 1)
        new_assignment = self.content.get("dayz-1", "steam-workshop:2289456201")
        self.assertEqual(new_assignment["version"], "1792603787")
        seen = []

        def emulate_agent_commands(_config, commands):
            chosen = next(cmd for cmd in commands if cmd["content_id"] == "steam-workshop:2289456201")
            seen.append(chosen)
            return [{
                "instance_id": chosen["instance_id"],
                "content_id": chosen["content_id"],
                "desired_revision": chosen["revision"],
                "applied_revision": chosen["revision"],
                "desired_checksum": chosen["checksum"],
                "applied_checksum": chosen["checksum"],
                "status": "applied",
                "installed_version": chosen["version"],
                "security_state": "clean",
            }]

        fake_client = SimpleNamespace(content_state=lambda: [], apply_content_commands=emulate_agent_commands)
        with (
            patch("hybrid_agent_worker._hybrid_agent_config", return_value={"agent_id": "agent-1"}),
            patch("hybrid_agent_worker._content_client_module", return_value=fake_client),
        ):
            outcome = process_hybrid_content_cycle(self.backend, ROOT, "agent-1")
        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(outcome["applied"], 1)
        self.assertEqual(outcome["failed"], 0)
        self.assertEqual(len(seen), 1)
        persisted = self.content.agent_state_for_instance("dayz-1")[
            "steam-workshop:2289456201"]
        self.assertEqual(persisted["installed_version"], "1792603787")
        self.assertEqual(persisted["applied_revision"], new_assignment["revision"])
        self.assertEqual(self.scan()["current"], 1)
        with self.backend.connect() as conn:
            state = conn.execute("SELECT state FROM content_update_state").fetchone()[0]
        self.assertEqual(state, "up_to_date")

    def test_inventory_persists_and_manual_policy_never_dispatches(self):
        self.assertEqual(self.scan()["available"], 1)
        with self.backend.connect() as conn:
            row = conn.execute(
                "SELECT installed_version,available_version,state FROM content_update_state"
            ).fetchone()
        self.assertEqual(tuple(row), ("1740499952", "1792603787", "update_available"))
        self.state.set_content_policy(
            instance_id="dayz-1", content_id="steam-workshop:2289456201",
            mode="manual", requested_by="test",
        )
        self.assertEqual(self.dispatch.due(), [])

    def test_automatic_policy_exposes_due_without_executing_update(self):
        self.assertEqual(self.scan()["available"], 1)
        self.state.set_content_policy(
            instance_id="dayz-1", content_id="steam-workshop:2289456201",
            mode="automatic", requested_by="test",
        )
        due = self.dispatch.due()
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["available_version"], "1792603787")
        self.assertEqual(due[0]["effective_mode"], "automatic")
        # No worker.tick(), claim(), mutate(), SteamCMD, or Agent applied.
        self.assertEqual(self.content.get("dayz-1", "steam-workshop:2289456201")["revision"],
                         self.current["revision"])


if __name__ == "__main__":
    unittest.main()
