#!/usr/bin/env python3
"""Regression tests for Agent-side protection of interrupted Server Pack journals.

All journal files live in disposable temporary directories; no production
Agent configuration, service or instance storage is accessed.
"""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class InterruptedServerpackJournalGuardTest(unittest.TestCase):
    def _load_agent(self, platform, temp):
        runtime = types.ModuleType("instance_runtime")
        runtime.STATE_DIR = temp
        runtime._token = lambda value, kind: str(value)
        lock = types.ModuleType("runtime_lock")
        @contextmanager
        def instance_lock(instance_id, operation, timeout_seconds=5.0):
            yield {"instance_id": instance_id}
        lock.instance_lock = instance_lock
        path = ROOT / "agents" / platform / "runtime" / "runtime_operations.py"
        spec = importlib.util.spec_from_file_location("staged_guard_" + platform, path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"instance_runtime": runtime, "runtime_lock": lock}):
            spec.loader.exec_module(module)
        return module

    def test_interrupted_migration_blocks_every_new_runtime_operation(self):
        for platform in ("linux", "windows"):
            for status in ("running", "interrupted", "failed"):
                with self.subTest(platform=platform, status=status), tempfile.TemporaryDirectory() as td:
                    module = self._load_agent(platform, td)
                    journal_path = module._path("sandbox-test")
                    journal_path.parent.mkdir(parents=True)
                    existing = {
                        "agent_id": "test-agent",
                        "instance_id": "sandbox-test",
                        "operation": "minecraft_serverpack_migration",
                        "status": status,
                        "migration_plan_sha256": "a" * 64,
                    }
                    original = json.dumps(existing)
                    journal_path.write_text(original)
                    with self.assertRaisesRegex(RuntimeError, "requires manual recovery"):
                        with module.runtime_operation({"agent_id": "test-agent"},
                                                      "sandbox-test", "provision"):
                            self.fail("locked operation unexpectedly started")
                    self.assertEqual(journal_path.read_text(), original)

    def test_corrupted_existing_journal_blocks_new_operations(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as td:
                module = self._load_agent(platform, td)
                journal_path = module._path("sandbox-test")
                journal_path.parent.mkdir(parents=True)
                journal_path.write_text("{truncated")
                with self.assertRaisesRegex(RuntimeError, "unreadable"):
                    with module.runtime_operation({"agent_id": "test-agent"},
                                                  "sandbox-test", "provision"):
                        self.fail("corrupted journal unexpectedly overwritten")
                self.assertEqual(journal_path.read_text(), "{truncated")

    def test_normal_completed_journal_does_not_block_existing_operations(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as td:
                module = self._load_agent(platform, td)
                previous = module._path("sandbox-test")
                previous.parent.mkdir(parents=True)
                previous.write_text(json.dumps({
                    "agent_id": "test-agent", "instance_id": "sandbox-test",
                    "operation": "minecraft_serverpack_migration", "status": "completed",
                }))
                with module.runtime_operation({"agent_id": "test-agent"},
                                              "sandbox-test", "provision"):
                    during = module.read_operation("sandbox-test")
                    self.assertEqual(during["status"], "running")
                    self.assertFalse(during["previous_interrupted"])
                self.assertEqual(module.read_operation("sandbox-test")["status"], "completed")

    def test_regular_interrupted_operations_retain_existing_behavior(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as td:
                module = self._load_agent(platform, td)
                previous = module._path("sandbox-test")
                previous.parent.mkdir(parents=True)
                previous.write_text(json.dumps({
                    "agent_id": "test-agent", "instance_id": "sandbox-test",
                    "operation": "restart", "status": "interrupted",
                }))
                with module.runtime_operation({"agent_id": "test-agent"},
                                              "sandbox-test", "provision") as journal:
                    self.assertTrue(journal["previous_interrupted"])
                self.assertEqual(module.read_operation("sandbox-test")["status"], "completed")


if __name__ == "__main__":
    unittest.main()
