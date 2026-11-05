#!/usr/bin/env python3
"""Instance-private BattlEye configuration path contract for DayZ."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents" / "linux" / "runtime"))
from profiles.base import ProfileError
from profiles.dayz import DayZRuntimeProfile


class DayZBattlEyePathTest(unittest.TestCase):
    def setUp(self):
        self.profile = DayZRuntimeProfile()
        self.instance = {"instance_id": "dayz-test-01", "agent_id": "agent-test"}
        self.context = {
            "install_path": "/tmp/dayz-bepath-test-content",
            "instance_state_root": "/tmp/dayz-bepath-test-private",
            "ports": {"game": 24000, "game_aux": 24002,
                      "battleye": 24004, "steam_query": 24003},
        }

    def test_default_is_unique_private_directory(self):
        spec = self.profile.build_runtime_spec(self.instance, self.context)
        expected = "/tmp/dayz-bepath-test-private/battleye"
        self.assertIn("-BEpath=" + expected, spec["arguments"])
        self.assertIn(expected, spec["writable_directories"])
        self.assertEqual(sum(x.lower().startswith("-bepath=") for x in spec["arguments"]), 1)

    def test_customer_can_select_safe_private_subdirectory(self):
        self.context["battleye_directory"] = "anticheat/battleye"
        spec = self.profile.build_runtime_spec(self.instance, self.context)
        self.assertIn("-BEpath=/tmp/dayz-bepath-test-private/anticheat/battleye", spec["arguments"])

    def test_invalid_custom_paths_fail_closed(self):
        for path in ("/etc", "../escape", "a/../../b", "a\\b", "", ".",
                     "battleye//other", "battleye/../other", "battleye space",
                     "-option", 123, None):
            with self.subTest(path=path):
                self.context["battleye_directory"] = path
                with self.assertRaises(ProfileError):
                    self.profile.build_runtime_spec(self.instance, self.context)

    def test_raw_bepath_override_is_rejected(self):
        for argument in ("-BEpath=/etc", "-bepath=../unsafe", "-BEpath /etc", "-bepath"):
            with self.subTest(argument=argument):
                self.context["arguments"] = [argument]
                with self.assertRaises(ProfileError):
                    self.profile.build_runtime_spec(self.instance, self.context)

    def test_migration_discards_legacy_bepath_flags(self):
        record = {
            "instance_id": "dayz-test-01",
            "working_directory": "/tmp/dayz-bepath-test-content",
            "arguments": ["-BEpath=/tmp/unsafe", "-mod=@CF", "-profiles=/tmp/old"],
            "ports": self.context["ports"],
        }
        ctx = self.profile.migration_context(record)
        self.assertEqual(ctx["arguments"], ["-mod=@CF"])
        spec = self.profile.build_runtime_spec(self.instance, ctx)
        self.assertIn("-mod=@CF", spec["arguments"])
        self.assertEqual(sum(x.lower().startswith("-bepath=") for x in spec["arguments"]), 1)


if __name__ == "__main__":
    unittest.main()
