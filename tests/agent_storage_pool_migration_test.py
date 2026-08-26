#!/usr/bin/env python3
from __future__ import annotations

from contextlib import nullcontext
import importlib.util
from pathlib import Path
from types import SimpleNamespace
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


class StoragePoolMigrationExecutorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.target = self.root / "target"
        self.source.mkdir()
        self.target.mkdir()
        self.config = {
            "agent_id": "agent-one",
            "default_storage_pool_id": "source",
            "storage_pools": [
                {"id": "source", "root_path": str(self.source), "enabled": True},
                {"id": "target", "root_path": str(self.target), "enabled": True},
            ],
        }
        source_instance = self.source / "instance-one"
        self.original = {
            "instance_id": "instance-one",
            "agent_id": "agent-one",
            "game_id": "dayz",
            "environment_id": "dayz.stable",
            "runtime_id": "runtime-one",
            "adapter": "systemd",
            "profile": "dayz",
            "profile_version": 1,
            "storage_pool_id": "source",
            "instance_state_root": str(source_instance),
            "config_path": str(source_instance / "config" / "serverDZ.cfg"),
            "arguments": [f"-profiles={source_instance / 'profiles'}"],
            "working_directory": str(self.root / "serverfiles"),
            "desired_state": "stopped",
        }
        self.command = {
            "migration_id": "migration-one",
            "agent_id": "agent-one",
            "instance_id": "instance-one",
            "source_storage_pool_id": "source",
            "target_storage_pool_id": "target",
        }
        self.result = self.root / "result.json"

    def tearDown(self):
        self.temp.cleanup()

    def _common(self):
        return (
            patch.object(executor.instance_runtime, "_owned", return_value=dict(self.original)),
            patch.object(executor.instance_runtime, "status", return_value={"observed_state": "stopped"}),
            patch.object(executor, "runtime_operation", return_value=nullcontext()),
            patch.object(executor, "emit_runtime_event", return_value={}),
        )

    def test_success_switches_only_instance_to_target_pool(self):
        registered = []
        mocks = self._common()
        with mocks[0], mocks[1], mocks[2], mocks[3], \
             patch.object(executor.privileged_materialization, "migrate_storage_pool_copy", return_value={
                 "atomic_commit": True, "verified_files": 2, "verified_bytes": 2048, "source_preserved": True,
             }) as copy, \
             patch.object(executor.privileged_materialization, "materialize", return_value={"operation": {"changed": True}}), \
             patch.object(executor.instance_runtime, "register_instance", side_effect=lambda value: registered.append(dict(value)) or value):
            result = executor.execute(self.config, self.command, self.result)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["verified_files"], 2)
        self.assertTrue(result["source_preserved"])
        copy.assert_called_once()
        migrated = registered[-1]
        self.assertEqual(migrated["storage_pool_id"], "target")
        self.assertEqual(Path(migrated["instance_state_root"]), self.target / "instance-one")
        self.assertEqual(Path(migrated["config_path"]), self.target / "instance-one" / "config" / "serverDZ.cfg")
        self.assertIn(str(self.target / "instance-one" / "profiles"), migrated["arguments"][0])

    def test_running_instance_is_rejected_before_copy(self):
        mocks = self._common()
        with mocks[0], patch.object(executor.instance_runtime, "status", return_value={"observed_state": "running"}), \
             mocks[2], mocks[3], patch.object(executor.privileged_materialization, "migrate_storage_pool_copy") as copy:
            result = executor.execute(self.config, self.command, self.result)
        self.assertEqual(result["status"], "failed")
        self.assertIn("must be stopped", result["error"])
        copy.assert_not_called()

    def test_stale_source_pool_is_rejected(self):
        stale = dict(self.original)
        stale["storage_pool_id"] = "target"
        with patch.object(executor.instance_runtime, "_owned", return_value=stale), \
             patch.object(executor, "runtime_operation", return_value=nullcontext()), \
             patch.object(executor, "emit_runtime_event", return_value={}), \
             patch.object(executor.privileged_materialization, "migrate_storage_pool_copy") as copy:
            result = executor.execute(self.config, self.command, self.result)
        self.assertEqual(result["status"], "failed")
        self.assertIn("changed before migration", result["error"])
        copy.assert_not_called()

    def test_materialization_failure_rolls_runtime_back_to_original(self):
        registered = []
        mocks = self._common()
        with mocks[0], mocks[1], mocks[2], mocks[3], \
             patch.object(executor.privileged_materialization, "migrate_storage_pool_copy", return_value={
                 "atomic_commit": True, "verified_files": 1, "verified_bytes": 10, "source_preserved": True,
             }), \
             patch.object(executor.privileged_materialization, "materialize", side_effect=[RuntimeError("switch failed"), {"operation": {"changed": True}}]) as materialize, \
             patch.object(executor.instance_runtime, "register_instance", side_effect=lambda value: registered.append(dict(value)) or value):
            result = executor.execute(self.config, self.command, self.result)
        self.assertEqual(result["status"], "failed")
        self.assertIn("switch failed", result["error"])
        self.assertTrue(result["source_preserved"])
        self.assertTrue(result["target_committed"])
        self.assertEqual(materialize.call_count, 2)
        self.assertEqual(registered[-1]["storage_pool_id"], "source")

    def test_command_rejects_disabled_target_pool(self):
        config = dict(self.config)
        config["storage_pools"] = [dict(self.config["storage_pools"][0]), {**self.config["storage_pools"][1], "enabled": False}]
        with self.assertRaisesRegex(ValueError, "disabled"):
            executor.validate_command(config, self.command)


class PrivilegedStoragePoolCopyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        module_path = ROOT / "agents" / "linux" / "privileged" / "materialize_instance.py"
        spec = importlib.util.spec_from_file_location("capivara_privileged_storage_pool_test", module_path)
        cls.helper = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(cls.helper)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.target = self.root / "target"
        self.legacy = self.root / "legacy-target"
        (self.source / "instance-one" / "config").mkdir(parents=True)
        (self.source / "instance-one" / "config" / "a.cfg").write_bytes(b"abc")
        (self.source / "instance-one" / "profiles").mkdir()
        (self.source / "instance-one" / "profiles" / "state.bin").write_bytes(b"0123456789")
        self.target.mkdir()
        self.config = {
            "agent_id": "agent-one",
            "default_storage_pool_id": "source",
            "storage_pools": [
                {"id": "source", "root_path": str(self.source), "enabled": True},
                {"id": "target", "root_path": str(self.target), "enabled": True},
            ],
        }
        self.spec = {
            "instance_id": "instance-one",
            "agent_id": "agent-one",
            "storage_pool_id": "source",
            "instance_state_root": str(self.source / "instance-one"),
            "user": "test-runtime",
        }

    def tearDown(self):
        self.temp.cleanup()

    def _account(self):
        return SimpleNamespace(pw_uid=0, pw_gid=0)

    def test_pool_copy_verifies_and_atomically_commits_without_deleting_source(self):
        with patch.object(self.helper, "_validate_runtime_user", return_value=self._account()), \
             patch.object(self.helper.os, "chown", return_value=None):
            result = self.helper._migrate_storage_copy(
                self.config,
                self.spec,
                target_storage_pool_id="target",
                migration_id="migration-one",
            )
        self.assertTrue(result["atomic_commit"])
        self.assertEqual(result["verified_files"], 2)
        self.assertEqual(result["verified_bytes"], 13)
        self.assertTrue((self.source / "instance-one" / "config" / "a.cfg").is_file())
        self.assertEqual((self.target / "instance-one" / "profiles" / "state.bin").read_bytes(), b"0123456789")
        self.assertFalse(any(self.target.glob(".capivara-migrate-*")))

    def test_pool_copy_rejects_symlinks(self):
        link = self.source / "instance-one" / "unsafe-link"
        try:
            link.symlink_to(self.root / "outside")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with patch.object(self.helper, "_validate_runtime_user", return_value=self._account()), \
             patch.object(self.helper.os, "chown", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "refuses symlink"):
                self.helper._migrate_storage_copy(
                    self.config,
                    self.spec,
                    target_storage_pool_id="target",
                    migration_id="migration-two",
                )
        self.assertFalse((self.target / "instance-one").exists())

    def test_legacy_root_copy_contract_remains_available(self):
        with patch.object(self.helper, "_validate_runtime_user", return_value=self._account()), \
             patch.object(self.helper.os, "chown", return_value=None):
            result = self.helper._migrate_storage_copy(
                self.config,
                self.spec,
                target_root_value=str(self.legacy),
            )
        self.assertTrue(result["atomic_commit"])
        self.assertIsNone(result["target_storage_pool_id"])
        self.assertTrue((self.legacy / "instance-one" / "config" / "a.cfg").is_file())

    def test_pool_copy_rejects_unconfigured_target_identity(self):
        with self.assertRaisesRegex(RuntimeError, "storage pool not found"):
            self.helper._migrate_storage_copy(
                self.config,
                self.spec,
                target_storage_pool_id="missing",
                migration_id="migration-three",
            )


if __name__ == "__main__":
    unittest.main()
