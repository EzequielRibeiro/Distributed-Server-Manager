#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HybridCustomerFilesAccessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper = _load(
            "prepare_customer_files_test_module",
            ROOT / "agents" / "linux" / "privileged" / "prepare_customer_files.py",
        )

    def test_prepare_tree_grants_group_access_without_other_bits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "instance"
            child = root / "config"
            file_path = child / "server.cfg"
            child.mkdir(parents=True)
            file_path.write_text("hostname=test\n", encoding="utf-8")
            os.chmod(root, 0o700)
            os.chmod(child, 0o700)
            os.chmod(file_path, 0o600)

            with mock.patch.object(self.helper.os, "chown") as chown:
                result = self.helper._prepare_tree(root, 987)

            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o770)
            self.assertEqual(stat.S_IMODE(child.stat().st_mode), 0o770)
            self.assertEqual(stat.S_IMODE(file_path.stat().st_mode), 0o660)
            self.assertEqual(result, {"directories": 2, "files": 1})
            self.assertEqual(chown.call_count, 3)
            for path in (root, child, file_path):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o007, 0)

    def test_prepare_tree_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "instance"
            root.mkdir()
            target = Path(temp) / "outside"
            target.mkdir()
            link = root / "link"
            try:
                link.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")

            with mock.patch.object(self.helper.os, "chown"):
                with self.assertRaisesRegex(RuntimeError, "contains a symlink"):
                    self.helper._prepare_tree(root, 987)


class HybridRuntimeReconcileCycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worker = _load(
            "hybrid_agent_worker_test_module",
            ROOT / "dashboard" / "workers" / "hybrid_agent_worker.py",
        )

    def test_reconcile_cycle_runs_reconciler_and_repairs_files_access(self):
        class FakeReconciler:
            @staticmethod
            def reconcile_all(config):
                self.assertEqual(config["agent_id"], "agent-hybrid")
                return [
                    {"instance_id": "instance-healthy", "status": "healthy"},
                    {"instance_id": "instance-retry", "status": "retry_wait"},
                ]

        def prepare(instance_id: str):
            if instance_id == "instance-retry":
                raise OSError("helper unavailable")

        with mock.patch.object(
            self.worker,
            "_hybrid_agent_config",
            return_value={"agent_id": "agent-hybrid"},
        ), mock.patch.object(
            self.worker,
            "_runtime_reconciler_module",
            return_value=FakeReconciler,
        ), mock.patch.object(
            self.worker,
            "_prepare_hybrid_customer_files_access",
            side_effect=prepare,
        ) as access:
            result = self.worker.process_hybrid_instance_reconcile_cycle(ROOT, "agent-hybrid")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["instances"], 2)
        self.assertEqual(result["healthy"], 1)
        self.assertEqual(result["files_access_prepared"], 1)
        self.assertEqual(result["files_access_failed"], 1)
        self.assertEqual(access.call_count, 2)

    def test_reconcile_cycle_tolerates_bootstrap_without_agent_config(self):
        with mock.patch.object(self.worker, "_hybrid_agent_config", return_value=None):
            result = self.worker.process_hybrid_instance_reconcile_cycle(ROOT, "agent-hybrid")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "config_unavailable")
        self.assertEqual(result["instances"], 0)


if __name__ == "__main__":
    unittest.main()
