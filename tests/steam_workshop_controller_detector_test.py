#!/usr/bin/env python3
"""Safety regressions for opt-in Steam Workshop update detection."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "core", ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from content_update_detector import ControllerContentUpdateDetector, _workshop_observation


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


if __name__ == "__main__":
    unittest.main()
