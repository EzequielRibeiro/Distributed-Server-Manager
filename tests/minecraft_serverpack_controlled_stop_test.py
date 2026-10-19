#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents/linux/runtime"))
from minecraft_serverpack_controlled_stop import ControlledStopError, ensure_stopped


class ControlledStopTest(unittest.TestCase):
    def test_already_stopped_does_not_stop_again(self):
        adapter = Mock()
        adapter.status.return_value = {"active_state": "inactive"}
        self.assertFalse(ensure_stopped({}, adapter)["stop_requested"])
        adapter.stop.assert_not_called()

    def test_running_instance_requires_confirmed_inactive(self):
        adapter = Mock()
        adapter.status.side_effect = [
            {"active_state": "active"},
            {"active_state": "deactivating"},
            {"active_state": "inactive"},
        ]
        result = ensure_stopped({}, adapter, sleep=lambda _: None)
        self.assertEqual(result["previous_state"], "active")
        adapter.stop.assert_called_once()

    def test_unknown_state_fails_closed(self):
        adapter = Mock()
        adapter.status.return_value = {"active_state": "failed"}
        with self.assertRaises(ControlledStopError):
            ensure_stopped({}, adapter)
        adapter.stop.assert_not_called()

    def test_deactivating_must_be_confirmed(self):
        adapter = Mock()
        adapter.status.side_effect = [
            {"active_state": "deactivating"},
            {"active_state": "inactive"},
        ]
        result = ensure_stopped({}, adapter, sleep=lambda _: None)
        self.assertFalse(result["stop_requested"])
        adapter.stop.assert_not_called()

    def test_timeout_is_not_success(self):
        adapter = Mock()
        adapter.status.return_value = {"active_state": "active"}
        clock = iter([0.0, 2.0])
        with self.assertRaisesRegex(ControlledStopError, "timed out"):
            ensure_stopped({}, adapter, timeout_seconds=1, monotonic=lambda: next(clock))
        adapter.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
