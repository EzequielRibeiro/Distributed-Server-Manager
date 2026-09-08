#!/usr/bin/env python3
"""Regression tests for instance-private Universal Smart Backup roots."""

from __future__ import annotations

import importlib.util
import sys
import tarfile
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def _load_backup_client():
    module_path = ROOT / "agents/linux/runtime/backup_client.py"

    runtime_stub = types.ModuleType("instance_runtime")
    runtime_stub.get_instance = lambda instance_id: None
    runtime_stub.lifecycle = lambda config, instance_id, action: {}
    runtime_stub.status = lambda config, instance_id: {
        "observed_state": "stopped"
    }

    sentinel = object()
    previous = sys.modules.get("instance_runtime", sentinel)

    try:
        sys.modules["instance_runtime"] = runtime_stub

        spec = importlib.util.spec_from_file_location(
            "capivara_linux_backup_client_root_test",
            module_path,
        )

        if spec is None or spec.loader is None:
            raise RuntimeError(
                f"unable to load backup client from {module_path}"
            )

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    finally:
        if previous is sentinel:
            sys.modules.pop("instance_runtime", None)
        else:
            sys.modules["instance_runtime"] = previous


backup_client = _load_backup_client()


class BackupClientInstanceRootTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

        self.shared = self.root / "shared-game-content"
        self.private = self.root / "instance-private"

        self.shared.mkdir()
        self.private.mkdir()

        (self.shared / "shared-only.txt").write_text(
            "shared-sentinel",
            encoding="utf-8",
        )
        (self.private / "save.txt").write_text(
            "private-before",
            encoding="utf-8",
        )

        self.record = {
            "instance_id": "instance-safe",
            "agent_id": "agent-safe",
            "game_id": "dayz",
            "runtime_id": "dayz.stable",

            # Shared provider/game content.
            "path": str(self.shared),
            "working_directory": str(self.shared),

            # Canonical instance-private state.
            "files_root": str(self.private),
            "instance_state_root": str(self.private),
        }

        self.config = {
            "agent_id": "agent-safe",
        }

        self.old_backup_root = backup_client.BACKUP_ROOT
        self.old_result_root = backup_client.RESULT_ROOT

        backup_client.BACKUP_ROOT = self.root / "backups"
        backup_client.RESULT_ROOT = self.root / "backup-results"

    def tearDown(self):
        backup_client.BACKUP_ROOT = self.old_backup_root
        backup_client.RESULT_ROOT = self.old_result_root
        self.temp.cleanup()

    def command(self):
        return {
            "command_id": "backup-command-safe",
            "instance_id": "instance-safe",
            "action": "create",
            "policy": {
                "mode": "full",
                "consistency": "live",
                "compression": "none",
                "retention_count": 3,
            },
        }

    def test_backup_root_prefers_files_root_over_shared_runtime_path(self):
        with patch.object(
            backup_client,
            "get_instance",
            return_value=self.record,
        ):
            record, selected = backup_client._owned(
                self.config,
                "instance-safe",
            )

        self.assertEqual(record["instance_id"], "instance-safe")
        self.assertEqual(selected, self.private.resolve())
        self.assertNotEqual(selected, self.shared.resolve())

    def test_create_archives_private_state_not_shared_game_content(self):
        with patch.object(
            backup_client,
            "get_instance",
            return_value=self.record,
        ):
            created = backup_client._create(
                self.config,
                self.command(),
            )

        artifact = Path(created["artifact_path"])
        self.assertTrue(artifact.is_file())

        with tarfile.open(artifact, "r:*") as archive:
            names = {
                name.lstrip("./")
                for name in archive.getnames()
            }

        self.assertIn("save.txt", names)
        self.assertNotIn("shared-only.txt", names)

    def test_restore_replaces_private_state_without_touching_shared_content(self):
        with patch.object(
            backup_client,
            "get_instance",
            return_value=self.record,
        ):
            created = backup_client._create(
                self.config,
                self.command(),
            )

        backup_id = created["backup_id"]

        (self.private / "save.txt").write_text(
            "private-after",
            encoding="utf-8",
        )
        (self.shared / "shared-only.txt").write_text(
            "shared-still-safe",
            encoding="utf-8",
        )

        with (
            patch.object(
                backup_client,
                "get_instance",
                return_value=self.record,
            ),
            patch.object(
                backup_client,
                "status",
                return_value={"observed_state": "stopped"},
            ),
        ):
            restored = backup_client._restore(
                self.config,
                {
                    "instance_id": "instance-safe",
                    "backup_id": backup_id,
                },
            )

        self.assertEqual(
            restored["backup_id"],
            backup_id,
        )
        self.assertEqual(
            (self.private / "save.txt").read_text(
                encoding="utf-8"
            ),
            "private-before",
        )
        self.assertEqual(
            (self.shared / "shared-only.txt").read_text(
                encoding="utf-8"
            ),
            "shared-still-safe",
        )

    def test_legacy_path_only_record_remains_supported(self):
        legacy = {
            "instance_id": "legacy-instance",
            "agent_id": "agent-safe",
            "path": str(self.private),
        }

        with patch.object(
            backup_client,
            "get_instance",
            return_value=legacy,
        ):
            _, selected = backup_client._owned(
                self.config,
                "legacy-instance",
            )

        self.assertEqual(
            selected,
            self.private.resolve(),
        )


if __name__ == "__main__":
    unittest.main()
