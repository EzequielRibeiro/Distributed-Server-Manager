#!/usr/bin/env python3
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
for path in (ROOT, ROOT / "database", ROOT / "dashboard", RUNTIME):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import storage_pool_migration_executor as executor


class StoragePoolSourceCleanupExecutorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.target = self.root / "target"
        self.source_instance = self.source / "instance-one"
        self.target_instance = self.target / "instance-one"
        (self.source_instance / "config").mkdir(parents=True)
        (self.source_instance / "config" / "server.cfg").write_bytes(b"abc")
        (self.source_instance / "profiles").mkdir()
        (self.source_instance / "profiles" / "state.bin").write_bytes(b"0123456789")
        self.target_instance.mkdir(parents=True)
        self.config = {
            "agent_id": "agent-one",
            "default_storage_pool_id": "target",
            "storage_pools": [
                {"id": "source", "root_path": str(self.source), "enabled": True},
                {"id": "target", "root_path": str(self.target), "enabled": True},
            ],
        }
        self.current = {
            "instance_id": "instance-one",
            "agent_id": "agent-one",
            "storage_pool_id": "target",
            "instance_state_root": str(self.target_instance),
        }
        self.command = {
            "schema_version": 1,
            "kind": "CapivaraInstanceStoragePoolSourceCleanup",
            "action": "cleanup-source",
            "migration_id": "storage-cleanup-one",
            "source_migration_id": "storage-migration-one",
            "agent_id": "agent-one",
            "instance_id": "instance-one",
            "source_storage_pool_id": "source",
            "target_storage_pool_id": "target",
            "expected_verified_files": 2,
            "expected_verified_bytes": 13,
        }
        self.result_path = self.root / "cleanup-result.json"

    def tearDown(self):
        self.temp.cleanup()

    def _patches(self, current=None):
        return (
            patch.object(executor.instance_runtime, "_owned", return_value=dict(current or self.current)),
            patch.object(executor, "runtime_operation", return_value=nullcontext()),
            patch.object(executor, "emit_runtime_event", return_value={}),
        )

    def test_cleanup_removes_only_verified_source_copy(self):
        patches = self._patches()
        with patches[0], patches[1], patches[2]:
            result = executor.execute(self.config, self.command, self.result_path)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["removed_files"], 2)
        self.assertEqual(result["removed_bytes"], 13)
        self.assertFalse(self.source_instance.exists())
        self.assertTrue(self.target_instance.exists())

    def test_cleanup_refuses_when_runtime_is_not_on_target_pool(self):
        stale = dict(self.current)
        stale["storage_pool_id"] = "source"
        patches = self._patches(stale)
        with patches[0], patches[1], patches[2]:
            result = executor.execute(self.config, self.command, self.result_path)
        self.assertEqual(result["status"], "failed")
        self.assertIn("not assigned to cleanup target", result["error"])
        self.assertTrue(self.source_instance.exists())

    def test_cleanup_refuses_when_runtime_root_does_not_match_target(self):
        stale = dict(self.current)
        stale["instance_state_root"] = str(self.source_instance)
        patches = self._patches(stale)
        with patches[0], patches[1], patches[2]:
            result = executor.execute(self.config, self.command, self.result_path)
        self.assertEqual(result["status"], "failed")
        self.assertIn("state root does not match", result["error"])
        self.assertTrue(self.source_instance.exists())

    def test_cleanup_refuses_changed_source_copy(self):
        (self.source_instance / "unexpected.dat").write_bytes(b"changed")
        patches = self._patches()
        with patches[0], patches[1], patches[2]:
            result = executor.execute(self.config, self.command, self.result_path)
        self.assertEqual(result["status"], "failed")
        self.assertIn("file count changed", result["error"])
        self.assertTrue(self.source_instance.exists())

    def test_cleanup_refuses_symlink_in_source(self):
        link = self.source_instance / "unsafe-link"
        try:
            link.symlink_to(self.root / "outside")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        command = dict(self.command)
        command["expected_verified_files"] = None
        command["expected_verified_bytes"] = None
        patches = self._patches()
        with patches[0], patches[1], patches[2]:
            result = executor.execute(self.config, command, self.result_path)
        self.assertEqual(result["status"], "failed")
        self.assertIn("contains symlink", result["error"])
        self.assertTrue(self.source_instance.exists())

    def test_cleanup_is_idempotent_when_source_is_already_absent(self):
        import shutil
        shutil.rmtree(self.source_instance)
        patches = self._patches()
        with patches[0], patches[1], patches[2]:
            result = executor.execute(self.config, self.command, self.result_path)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["already_absent"])
        self.assertEqual(result["removed_files"], 0)


class StoragePoolSourceCleanupContractTest(unittest.TestCase):
    def test_cleanup_requires_source_migration_identity(self):
        config = {
            "agent_id": "agent-one",
            "default_storage_pool_id": "target",
            "storage_pools": [
                {"id": "source", "root_path": "/srv/source", "enabled": True},
                {"id": "target", "root_path": "/srv/target", "enabled": True},
            ],
        }
        command = {
            "action": "cleanup-source",
            "migration_id": "cleanup-one",
            "agent_id": "agent-one",
            "instance_id": "instance-one",
            "source_storage_pool_id": "source",
            "target_storage_pool_id": "target",
        }
        with self.assertRaisesRegex(ValueError, "source_migration_id"):
            executor.validate_command(config, command)


if __name__ == "__main__":
    unittest.main()
