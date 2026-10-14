#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (
    ROOT,
    ROOT / "core",
    ROOT / "database",
    ROOT / "dashboard",
    ROOT / "dashboard" / "workers",
):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

import maintenance_worker as worker_module
from maintenance_platform import maintenance_event, normalize_policy
from maintenance_worker import MaintenanceWorker


class FakeRepo:
    def __init__(self, run):
        self.current = run
        self.p = normalize_policy({
            "enabled": True,
            "broadcast_enabled": False,
            "warning_offsets_seconds": [],
            "coalesce_updates": True,
        })
        self.finished = []

    def initialize(self):
        pass

    def candidates(self, now=None):
        return []

    def ensure_run(self, iid, now=None):
        return None

    def active_runs(self):
        if self.current and self.current.get("status") in {"pending", "running"}:
            return [self.current]
        return []

    def run(self, rid):
        return self.current

    def policy(self, iid):
        return self.p

    def instance_context(self, iid):
        return {
            "id": iid,
            "agent_id": self.current["agent_id"],
            "game_id": "dayz",
            "runtime_id": "dayz.stable",
            "status": "running",
        }

    def set_event(self, rid, event):
        self.current["event"] = event
        return self.current

    def update_event(self, rid, event, stage=None):
        self.current["event"] = event
        if stage is not None:
            self.current["stage"] = stage
        return self.current

    def next_due_for_run(self, rid, now=None):
        return datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc)

    def finish(
        self,
        rid,
        *,
        success,
        error_code=None,
        error_detail=None,
        now=None,
    ):
        self.finished.append({
            "success": success,
            "error_code": error_code,
            "error_detail": error_detail,
        })
        self.current["status"] = "completed" if success else "failed"
        return self.current


class FakeAutomation:
    def initialize(self):
        pass

    def create_broadcast(self, *args, **kwargs):
        raise AssertionError("DayZ native countdown must not use generic broadcast")


class FakeLifecycle:
    def __init__(self):
        self.enqueued = []
        self.states = {}

    def initialize(self):
        pass

    def enqueue(self, **kwargs):
        self.enqueued.append(kwargs)
        cid = f"cmd-{len(self.enqueued)}"
        self.states[cid] = {
            "command_id": cid,
            "status": "queued",
            "requested_by": kwargs.get("requested_by"),
        }
        return self.states[cid]

    def snapshot(self, cid):
        return self.states[cid]


class FakeNativeRestart:
    def __init__(self, current):
        self.current = current

    def for_instance_due(self, instance_id, due_at):
        return dict(self.current)

    def snapshot(self, command_id):
        return dict(self.current)

    def enqueue(self, **kwargs):
        raise AssertionError(
            "test should not prepare the next native restart at this stage"
        )


def complete(lifecycle, cid, observed_state):
    lifecycle.states[cid] = {
        "command_id": cid,
        "status": "completed",
        "requested_by": "maintenance-worker",
        "result": {
            "status": "completed",
            "result": {
                "observed_state": observed_state,
            },
        },
    }


def run_state():
    caps = {
        "scheduled_restart": True,
        "broadcast": False,
        "save": False,
        "graceful_shutdown": True,
        "native_countdown": True,
    }
    return {
        "run_id": "r1",
        "instance_id": "dayz-001",
        "agent_id": "agent-001",
        "due_at": "2026-09-16T15:00:00Z",
        "status": "running",
        "stage": "preflight",
        "event": maintenance_event(
            {
                "enabled": True,
                "broadcast_enabled": False,
                "warning_offsets_seconds": [],
                "coalesce_updates": True,
            },
            caps,
        ),
        "warnings_sent": [],
        "preflight_command_id": "pre",
        "save_command_id": None,
        "stop_command_id": None,
        "start_command_id": None,
        "readiness_command_id": None,
    }


class DayZNativeMaintenanceWorkerTest(unittest.TestCase):

    def make_worker(self, run):
        repo = FakeRepo(run)
        life = FakeLifecycle()
        worker = MaintenanceWorker(
            None,
            repository=repo,
            automation=FakeAutomation(),
            lifecycle=life,
            capability_resolver=lambda _iid: {
                "scheduled_restart": True,
                "broadcast": False,
                "save": False,
                "graceful_shutdown": True,
                "native_countdown": True,
            },
            content_coordinator=None,
            game_coordinator=None,
        )
        worker.native_restart = FakeNativeRestart({
            "command_id": "dayz-maint-current",
            "instance_id": "dayz-001",
            "due_at": "2026-09-16T15:00:00Z",
            "status": "completed",
        })
        return repo, life, worker

    def test_armed_native_restart_never_enqueues_generic_stop(self):
        run = run_state()
        repo, life, worker = self.make_worker(run)

        complete(life, "pre", "running")

        report = worker.tick(
            now=datetime(2026, 9, 16, 15, 0, 5, tzinfo=timezone.utc)
        )

        actions = [item["action"] for item in life.enqueued]

        self.assertEqual(actions, ["status"])
        self.assertNotIn("stop", actions)
        self.assertEqual(report["stops"], 0)
        self.assertEqual(report["native_shutdown_checks"], 1)
        self.assertEqual(repo.current["stage"], "awaiting-native-shutdown")

    def test_native_shutdown_timeout_is_fail_closed(self):
        run = run_state()
        run["event"]["native_shutdown"] = {
            "started_at": "2026-09-16T14:55:00Z",
            "status": "waiting",
        }

        repo, life, worker = self.make_worker(run)
        complete(life, "pre", "running")

        original_timeout = worker_module.NATIVE_SHUTDOWN_TIMEOUT_SECONDS
        worker_module.NATIVE_SHUTDOWN_TIMEOUT_SECONDS = 180

        try:
            report = worker.tick(
                now=datetime(2026, 9, 16, 15, 0, 5, tzinfo=timezone.utc)
            )
        finally:
            worker_module.NATIVE_SHUTDOWN_TIMEOUT_SECONDS = original_timeout

        actions = [item["action"] for item in life.enqueued]

        self.assertNotIn("stop", actions)
        self.assertNotIn("start", actions)

        self.assertEqual(report["native_shutdown_timeouts"], 1)
        self.assertEqual(report["failed"], 1)

        self.assertEqual(len(repo.finished), 1)
        self.assertFalse(repo.finished[0]["success"])
        self.assertEqual(
            repo.finished[0]["error_code"],
            "native_shutdown_timeout",
        )

    def test_completed_stop_probe_before_timeout_is_accepted(self):
        run = run_state()
        run["event"]["native_shutdown"] = {
            "started_at": "2026-09-16T14:55:00Z",
            "command_id": "native-probe",
            "status": "checking",
        }
        repo, life, worker = self.make_worker(run)
        complete(life, "pre", "running")
        complete(life, "native-probe", "stopped")
        worker._prepare_next_native_restart = (
            lambda run, event, now, result: (event, False)
        )
        report = worker.tick(
            now=datetime(2026, 9, 16, 15, 0, 5, tzinfo=timezone.utc)
        )
        self.assertEqual(report["native_shutdown_timeouts"], 0)
        self.assertEqual(report["native_shutdowns"], 1)
        self.assertEqual(repo.current["event"]["native_shutdown"]["status"], "completed")\n        self.assertEqual([item["action"] for item in life.enqueued], ["status"])

    def test_running_with_replaced_pid_requires_proven_native_transition(self):
        run = run_state()
        run["event"]["native_shutdown"] = {
            "started_at": "2026-09-16T14:59:00Z",
            "command_id": "native-probe",
            "status": "checking",
            "initial_pid": 3738932,
        }
        repo, life, worker = self.make_worker(run)
        complete(life, "pre", "running")
        complete(life, "native-probe", "running")
        life.states["native-probe"]["result"]["result"]["adapter_state"] = {
            "main_pid": 224240, "active_state": "active"
        }
        report = worker.tick(
            now=datetime(2026, 9, 16, 15, 0, 5, tzinfo=timezone.utc)
        )
        self.assertEqual(report["native_shutdowns"], 0)
        self.assertEqual(report["starts"], 0)
        self.assertIn(repo.current["event"]["native_shutdown"]["status"], {"waiting", "checking"})
        self.assertTrue(all(item["action"] == "status" for item in life.enqueued))

    def test_delayed_pending_probe_does_not_trigger_duplicate_commands(self):
        run = run_state()
        run["event"]["native_shutdown"] = {
            "started_at": "2026-09-16T14:59:00Z",
            "command_id": "native-probe",
            "status": "checking",
        }
        repo, life, worker = self.make_worker(run)
        complete(life, "pre", "running")
        life.states["native-probe"] = {
            "command_id": "native-probe", "status": "delivered"
        }
        report = worker.tick(
            now=datetime(2026, 9, 16, 15, 0, 5, tzinfo=timezone.utc)
        )
        self.assertEqual(report["native_shutdown_checks"], 0)
        self.assertEqual(report["native_shutdowns"], 0)
        self.assertEqual(life.enqueued, [])
        self.assertEqual(repo.current["status"], "running")

    def test_untrusted_claim_cannot_override_native_shutdown_timeout(self):
        # Production-like timeline: previous PID stopped at 12:36:11Z,
        # replacement started at 12:36:19Z, next probe saw only 'running'.
        # 'verified_transition' must eventually be populated from trusted
        # lifecycle evidence; an arbitrary PID change is not sufficient.
        run = run_state()
        run["event"]["native_shutdown"] = {
            "started_at": "2026-10-14T12:33:10Z",
            "expected_shutdown_at": "2026-10-14T12:33:10Z",
            "command_id": "native-probe",
            "initial_pid": 3738932,
            "verified_transition": {
                "old_pid": 3738932,
                "new_pid": 224240,
                "stopped_at": "2026-10-14T12:36:11Z",
                "restarted_at": "2026-10-14T12:36:19Z",
                "source": "trusted-systemd-lifecycle",
            },
        }
        repo, life, worker = self.make_worker(run)
        complete(life, "pre", "running")
        complete(life, "native-probe", "running")
        life.states["native-probe"]["result"]["result"]["adapter_state"] = {
            "main_pid": 224240, "active_state": "active"
        }
        report = worker.tick(
            now=datetime(2026, 10, 14, 12, 37, 15, tzinfo=timezone.utc)
        )
        self.assertEqual(report["native_shutdown_timeouts"], 1)
        self.assertEqual(report["failed"], 1)
        self.assertEqual(repo.current["status"], "failed")
        self.assertNotIn("stop", [item["action"] for item in life.enqueued])

    def test_already_stopped_native_instance_does_not_enqueue_stop(self):
        run = run_state()
        repo, life, worker = self.make_worker(run)

        complete(life, "pre", "stopped")

        # Prevent this test from entering preparation of the next cycle;
        # the assertion concerns recognition of native self-shutdown.
        worker._prepare_next_native_restart = (
            lambda run, event, now, result: (event, False)
        )

        report = worker.tick(
            now=datetime(2026, 9, 16, 15, 0, 5, tzinfo=timezone.utc)
        )

        actions = [item["action"] for item in life.enqueued]

        self.assertNotIn("stop", actions)
        self.assertEqual(report["skipped"], 0)
        self.assertEqual(repo.current["status"], "running")


if __name__ == "__main__":
    unittest.main()
