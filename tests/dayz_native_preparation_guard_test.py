#!/usr/bin/env python3
"""Sandbox-free regression tests for startup-only DayZ native preparation."""
from __future__ import annotations
import unittest
from agents.common.dayz_native_preparation_guard import require_stopped_instance

class DayZNativePreparationGuardTest(unittest.TestCase):
    def test_verified_inactive_is_allowed(self):
        require_stopped_instance({
            "observed_state": "stopped",
            "adapter_state": {"available": True, "active_state": "inactive"},
        })

    def test_other_states_fail_closed(self):
        for state in (
            None,
            {},
            {"observed_state": "stopped", "adapter_state": None},
            {"observed_state": "stopped", "adapter_state": {"available": False, "active_state": "inactive"}},
            {"observed_state": "stopped", "adapter_state": {"available": "true", "active_state": "inactive"}},
            {"observed_state": "running", "adapter_state": {"available": True, "active_state": "active"}},
            {"observed_state": "running", "adapter_state": {"available": True, "active_state": "inactive"}},
            {"observed_state": "stopped", "adapter_state": {"available": True, "active_state": "deactivating"}},
        ):
            with self.subTest(state=state), self.assertRaisesRegex(RuntimeError, "verified stopped instance"):
                require_stopped_instance(state)

if __name__ == "__main__":
    unittest.main()
