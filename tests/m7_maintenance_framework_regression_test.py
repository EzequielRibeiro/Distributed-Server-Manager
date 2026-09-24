#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "core", ROOT / "database", ROOT / "dashboard", ROOT / "dashboard/workers"):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

from maintenance_platform import normalize_policy
from maintenance_worker import MaintenanceWorker


NOW = datetime(2026, 9, 17, 22, 30, tzinfo=timezone.utc)


class _Repository:
    def __init__(self):
        self.p = normalize_policy(
            {
                "enabled": True,
                "coalesce_updates": True,
                "warning_offsets_seconds": [],
                "broadcast_enabled": False,
            }
        )
        self.current = {
            "run_id": "run-m7",
            "instance_id": "instance-m7",
            "agent_id": "agent-m7",
            "due_at": "2026-09-17T22:30:00Z",
            "status": "pending",
            "stage": "planning",
            "event": {},
            "warnings_sent": [],
            "preflight_command_id": None,
            "save_command_id": None,
            "stop_command_id": None,
            "start_command_id": None,
            "readiness_command_id": None,
        }
        self.finished = []

    def initialize(self):
        pass

    def candidates(self, now=None):
        return []

    def active_runs(self):
        return [dict(self.current)] if self.current["status"] in {"pending", "running"} else []

    def policy(self, instance_id):
        return dict(self.p)

    def run(self, run_id):
        return dict(self.current)

    def set_event(self, run_id, event):
        self.current["event"] = dict(event)
        self.current["stage"] = "warning"
        return dict(self.current)

    def update_event(self, run_id, event, stage=None):
        self.current["event"] = dict(event)
        if stage:
            self.current["stage"] = stage
        return dict(self.current)

    def _mark(self, key, command_id, stage):
        self.current[key] = command_id
        self.current["status"] = "running"
        self.current["stage"] = stage
        return dict(self.current)

    def mark_preflight(self, run_id, command_id):
        return self._mark("preflight_command_id", command_id, "preflight")

    def mark_save(self, run_id, command_id):
        return self._mark("save_command_id", command_id, "saving")

    def mark_stop(self, run_id, command_id):
        return self._mark("stop_command_id", command_id, "stopping")

    def mark_start(self, run_id, command_id):
        return self._mark("start_command_id", command_id, "starting")

    def mark_readiness(self, run_id, command_id):
        return self._mark("readiness_command_id", command_id, "validating")

    def finish(self, run_id, success, error_code=None, error_detail=None, now=None, next_due_override=None):
        self.finished.append((bool(success), error_code, error_detail))
        self.current["status"] = "completed" if success else "failed"
        return dict(self.current)


class _Automation:
    def initialize(self):
        pass

    def create_broadcast(self, *args, **kwargs):
        raise AssertionError("warnings are disabled in this regression fixture")


class _Lifecycle:
    def __init__(self):
        self.enqueued = []
        self.states = {}

    def initialize(self):
        pass

    def enqueue(self, **kwargs):
        command_id = f"cmd-{len(self.enqueued) + 1}"
        self.enqueued.append(kwargs["action"])
        self.states[command_id] = {
            "command_id": command_id,
            "status": "queued",
            "requested_by": kwargs.get("requested_by"),
        }
        return dict(self.states[command_id])

    def snapshot(self, command_id):
        return dict(self.states[command_id])

    def complete(self, command_id, payload):
        self.states[command_id] = {
            "command_id": command_id,
            "status": "completed",
            "requested_by": "maintenance-worker",
            "result": {"status": "completed", "result": dict(payload)},
        }


class _GameCoordinator:
    def __init__(self):
        self.prepared = 0
        self.finalized = 0
        self.rolled_back = 0

    def discover(self, instance_id):
        return [
            {
                "kind": "game-update",
                "ref": "server",
                "available_version": "next",
                "status": "pending",
            }
        ]

    def prepare(self, instance_id, item):
        value = dict(item)
        self.prepared += 1
        value.update(status="activated", transaction_id="m7-game-transaction")
        return value, True

    def finalize(self, instance_id, item):
        value = dict(item)
        self.finalized += 1
        value.update(status="committed")
        return value, True

    def rollback(self, instance_id, item):
        value = dict(item)
        self.rolled_back += 1
        value.update(status="rolled_back")
        return value, True


class _ContentAndConfigurationCoordinator:
    def __init__(self):
        self.dispatches = 0
        self.alignments = 0

    def discover(self, instance_id):
        return [
            {
                "kind": "content-update",
                "ref": "steam-workshop:100",
                "available_version": "101",
                "status": "pending",
            },
            {
                "kind": "configuration",
                "ref": "server-settings",
                "available_version": "resolved-m7",
                "status": "pending",
            },
        ]

    def dispatch_pending(self, instance_id, pending_work):
        self.dispatches += 1
        result = []
        for raw in pending_work:
            item = dict(raw)
            if item.get("kind") == "content-update":
                item.update(status="dispatched", desired_revision=2)
            result.append(item)
        return result

    def alignment(self, instance_id, pending_work):
        self.alignments += 1
        result = []
        aligned = []
        for raw in pending_work:
            item = dict(raw)
            if item.get("kind") in {"content-update", "configuration"}:
                item["status"] = "aligned"
                aligned.append(str(item.get("ref")))
            result.append(item)
        return {
            "ready": True,
            "pending": [],
            "failed": [],
            "aligned": aligned,
            "work": result,
        }


def _worker():
    repository = _Repository()
    lifecycle = _Lifecycle()
    game = _GameCoordinator()
    content = _ContentAndConfigurationCoordinator()
    worker = MaintenanceWorker(
        None,
        repository=repository,
        automation=_Automation(),
        lifecycle=lifecycle,
        capability_resolver=lambda _instance_id: {
            "scheduled_restart": True,
            "broadcast": True,
            "save": True,
            "graceful_shutdown": False,
            "native_countdown": False,
        },
        content_coordinator=content,
        game_coordinator=game,
    )
    return worker, repository, lifecycle, game, content


class M7MaintenanceFrameworkRegressionTest(unittest.TestCase):
    def test_game_content_and_restart_required_configuration_share_one_window(self):
        worker, repository, lifecycle, game, content = _worker()

        worker.tick(now=NOW)
        lifecycle.complete(repository.current["preflight_command_id"], {"observed_state": "running"})

        worker.tick(now=NOW)
        lifecycle.complete(repository.current["save_command_id"], {})

        worker.tick(now=NOW)
        lifecycle.complete(repository.current["stop_command_id"], {"observed_state": "stopped"})

        worker.tick(now=NOW)
        self.assertEqual(lifecycle.enqueued, ["status", "save", "stop", "start"])
        self.assertEqual(game.prepared, 1)
        self.assertEqual(content.dispatches, 1)
        self.assertEqual(content.alignments, 1)

        pending = repository.current["event"]["pending_work"]
        self.assertEqual(
            {item["kind"] for item in pending},
            {"game-update", "content-update", "configuration"},
        )

        lifecycle.complete(repository.current["start_command_id"], {"observed_state": "running"})
        worker.tick(now=NOW)
        self.assertEqual(lifecycle.enqueued, ["status", "save", "stop", "start", "doctor"])

        lifecycle.complete(repository.current["readiness_command_id"], {"ready": True})
        worker.tick(now=NOW)

        self.assertEqual(lifecycle.enqueued.count("stop"), 1)
        self.assertEqual(lifecycle.enqueued.count("start"), 1)
        self.assertEqual(lifecycle.enqueued.count("doctor"), 1)
        self.assertEqual(game.finalized, 1)
        self.assertEqual(game.rolled_back, 0)
        self.assertEqual(repository.finished, [(True, None, None)])

    def test_stopped_instance_with_native_save_capability_remains_stopped(self):
        worker, repository, lifecycle, game, content = _worker()

        worker.tick(now=NOW)
        lifecycle.complete(repository.current["preflight_command_id"], {"observed_state": "stopped"})
        result = worker.tick(now=NOW)

        self.assertEqual(lifecycle.enqueued, ["status"])
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(game.prepared, 0)
        self.assertEqual(content.dispatches, 0)
        self.assertEqual(repository.finished, [(True, None, None)])


if __name__ == "__main__":
    unittest.main()
