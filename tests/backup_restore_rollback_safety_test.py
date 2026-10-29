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


if __name__ == "__main__":
    unittest.main()
