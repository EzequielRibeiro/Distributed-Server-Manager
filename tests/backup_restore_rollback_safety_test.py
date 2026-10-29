#!/usr/bin/env python3
"""Fail-closed backup restore regression coverage."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents/linux/runtime"))
import backup_client


class RestoreRollbackSafetyTest(unittest.TestCase):
    def test_preexisting_previous_is_preserved_without_stopping(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "instance"
            root.mkdir()
            previous = Path(temp) / "instance.c5-previous"
            previous.mkdir()
            sentinel = previous / "world.dat"
            sentinel.write_text("keep")
            with (
                patch.object(backup_client, "_owned", return_value=({}, root)),
                patch.object(backup_client, "_artifact", return_value=Path(temp) / "backup.tar"),
                patch.object(backup_client, "status", return_value={"observed_state": "running"}),
                patch.object(backup_client, "lifecycle") as lifecycle,
            ):
                with self.assertRaisesRegex(RuntimeError, "pre-existing recovery"):
                    backup_client._restore_direct({}, {"instance_id": "test", "backup_id": "test"})
                lifecycle.assert_not_called()
            self.assertEqual(sentinel.read_text(), "keep")
            self.assertTrue(root.exists())

    def test_partial_swap_restores_original_if_activation_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "instance"
            root.mkdir()
            (root / "world.dat").write_text("original")
            original_replace = backup_client.os.replace
            calls = []

            def replace(src, dst):
                calls.append((Path(src), Path(dst)))
                if len(calls) == 2:
                    raise OSError("activation failed")
                return original_replace(src, dst)

            with (
                patch.object(backup_client, "_owned", return_value=({}, root)),
                patch.object(backup_client, "_artifact", return_value=Path(temp) / "backup.tar"),
                patch.object(backup_client, "status", return_value={"observed_state": "stopped"}),
                patch.object(backup_client, "_safe_extract", return_value=None),
                patch.object(backup_client.os, "replace", side_effect=replace),
            ):
                with self.assertRaisesRegex(OSError, "activation failed"):
                    backup_client._restore_direct({}, {"instance_id": "test", "backup_id": "test"})
            self.assertEqual((root / "world.dat").read_text(), "original")
            self.assertFalse((Path(temp) / "instance.c5-previous").exists())


    def test_restart_failure_restores_original_and_reports_recovery_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "instance"
            root.mkdir()
            (root / "world.dat").write_text("original")
            starts = []

            def lifecycle(_config, _instance, action):
                if action == "start":
                    starts.append(action)
                    raise RuntimeError("start unavailable")

            with (
                patch.object(backup_client, "_owned", return_value=({}, root)),
                patch.object(backup_client, "_artifact", return_value=Path(temp) / "backup.tar"),
                patch.object(backup_client, "status", return_value={"observed_state": "running"}),
                patch.object(backup_client, "lifecycle", side_effect=lifecycle),
                patch.object(backup_client, "_safe_extract", return_value=None),
            ):
                with self.assertRaisesRegex(RuntimeError, "restart recovery failed"):
                    backup_client._restore_direct({}, {"instance_id": "test", "backup_id": "test"})

            self.assertEqual(len(starts), 2)
            self.assertEqual((root / "world.dat").read_text(), "original")
            self.assertFalse((Path(temp) / "instance.c5-previous").exists())


    def test_privileged_staging_preserves_original_uid_gid(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            original = base / "instance"
            original.mkdir()
            stage = base / "stage"
            stage.mkdir()
            nested = stage / "mpmissions"
            nested.mkdir()
            world = nested / "world.dat"
            world.write_text("unchanged")
            expected = original.stat()
            with (
                patch.object(backup_client.os, "geteuid", return_value=0),
                patch.object(backup_client.os, "chown") as chown,
            ):
                backup_client._preserve_restored_owner(stage, original)
            self.assertEqual(
                {call.args[0] for call in chown.call_args_list},
                {stage, nested, world},
            )
            for call in chown.call_args_list:
                self.assertEqual(call.args[1:], (expected.st_uid, expected.st_gid))
            self.assertEqual(world.read_text(), "unchanged")

    def test_unprivileged_staging_does_not_attempt_chown(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            original = base / "instance"
            original.mkdir()
            stage = base / "stage"
            stage.mkdir()
            with (
                patch.object(backup_client.os, "geteuid", return_value=1000),
                patch.object(backup_client.os, "chown") as chown,
            ):
                backup_client._preserve_restored_owner(stage, original)
            chown.assert_not_called()


if __name__ == "__main__":
    unittest.main()
