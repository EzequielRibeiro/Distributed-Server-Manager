"""Regression tests for fail-closed backup archive handling."""
import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents" / "linux" / "runtime"))
import backup_client as backup


class BackupArchiveGuards(unittest.TestCase):
    def test_empty_selection_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "file.txt").write_text("ok")
            with self.assertRaisesRegex(ValueError, "no paths"):
                backup._selected(root, {"mode": "full", "exclude_paths": ["."]})
            with self.assertRaisesRegex(ValueError, "no paths"):
                backup._selected(root, {"mode": "full", "include_paths": ["missing"]})

    def test_manifest_only_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "empty.tar.gz"
            with tarfile.open(path, "w:gz") as tar:
                payload = b"{}"
                info = tarfile.TarInfo(backup.MANIFEST_NAME)
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
            with self.assertRaisesRegex(ValueError, "no instance files"):
                backup._validate_archive_payload(path)

    def test_real_archive_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "instance"
            root.mkdir()
            (root / "config.cfg").write_text("ok")
            archive = Path(temp) / "valid.tar.gz"
            backup._create_archive(root, [root], archive, "gzip", {"kind": "CapivaraInstanceBackup"})
            backup._validate_archive_payload(archive)

    def test_truncated_archive_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "broken.tar.gz"
            with tarfile.open(path, "w:gz") as tar:
                payload = b"hello" * 200
                info = tarfile.TarInfo("config.cfg")
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
            data = path.read_bytes()
            path.write_bytes(data[: max(1, len(data) // 2)])
            with self.assertRaises((tarfile.TarError, EOFError, OSError)):
                backup._validate_archive_payload(path)


    def test_privileged_restore_rejects_empty_before_systemd(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "instance"
            root.mkdir()
            archive = Path(temp) / "empty.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                payload = b'{"kind":"CapivaraInstanceBackup","backup_format":"capivara-instance"}'
                info = tarfile.TarInfo(backup.MANIFEST_NAME)
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
            with (
                patch.object(backup, "_owned", return_value=({}, root)),
                patch.object(backup, "_artifact", return_value=archive),
                patch.object(backup.subprocess, "run") as systemctl,
            ):
                with self.assertRaisesRegex(ValueError, "no instance files"):
                    backup._restore_via_privileged_helper(
                        {"agent_id": "test"},
                        {"command_id": "test", "instance_id": "test", "backup_id": "test"},
                        "capivara-restore@{command_id}.service",
                    )
                systemctl.assert_not_called()


    def test_privileged_restore_rejects_missing_manifest_before_systemd(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "instance"
            root.mkdir()
            archive = Path(temp) / "missing-manifest.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                payload = b"world data"
                info = tarfile.TarInfo("world.dat")
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
            with (
                patch.object(backup, "_owned", return_value=({}, root)),
                patch.object(backup, "_artifact", return_value=archive),
                patch.object(backup.subprocess, "run") as systemctl,
            ):
                with self.assertRaisesRegex(ValueError, "manifest is missing"):
                    backup._restore_via_privileged_helper(
                        {"agent_id": "test"},
                        {"command_id": "test", "instance_id": "test", "backup_id": "test"},
                        "capivara-restore@{command_id}.service",
                    )
                systemctl.assert_not_called()


    def test_privileged_restore_rejects_incompatible_game_before_systemd(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "instance"
            root.mkdir()
            archive = Path(temp) / "wrong-game.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                manifest = b'{"kind":"CapivaraInstanceBackup","backup_format":"capivara-instance","game_id":"minecraft"}'
                info = tarfile.TarInfo(backup.MANIFEST_NAME)
                info.size = len(manifest)
                tar.addfile(info, io.BytesIO(manifest))
                payload = b"world data"
                info = tarfile.TarInfo("world.dat")
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
            with (
                patch.object(backup, "_owned", return_value=({"game_id": "dayz"}, root)),
                patch.object(backup, "_artifact", return_value=archive),
                patch.object(backup.subprocess, "run") as systemctl,
            ):
                with self.assertRaisesRegex(ValueError, "incompatible"):
                    backup._restore_via_privileged_helper(
                        {"agent_id": "test"},
                        {"command_id": "test", "instance_id": "test", "backup_id": "test"},
                        "capivara-restore@{command_id}.service",
                    )
                systemctl.assert_not_called()


if __name__ == "__main__":
    unittest.main()
