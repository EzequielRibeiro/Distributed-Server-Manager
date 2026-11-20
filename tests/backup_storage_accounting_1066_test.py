"""Bounded #1066 contract tests: real files, quota preflight and backup preservation."""
from __future__ import annotations

import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents/linux/runtime"))
import backup_client
from backup_storage_accounting import backup_inventory, quota_snapshot, source_size, physical_backup_catalog


def create_tar(path: Path, *, payload: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as archive:
        for name, contents in [
            (".capivara-backup-manifest.json", b"{}"),
            *(([("save.dat", b"world")]) if payload else []),
        ]:
            member = tarfile.TarInfo(name)
            member.size = len(contents)
            archive.addfile(member, io.BytesIO(contents))


class BackupStorageAccounting1066(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dsm1066-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private = self.root / "instance-1"
        self.private.mkdir()
        (self.private / "save.dat").write_bytes(b"live-world")
        self.archive_root = self.root / "backups"
        self.archive_root.mkdir()
        self.record = {
            "agent_id": "agent-one",
            "instance_id": "instance-one",
            "instance_state_root": str(self.private),
            "files_root": str(self.private),
            "game_id": "dayz",
            "runtime_id": "dayz.stable",
            "storage_limit_bytes": 8 * 1024 * 1024,
        }
        self.config = {"agent_id": "agent-one"}
        self.old_backup = backup_client.BACKUP_ROOT
        self.old_state = backup_client.STATE_ROOT
        backup_client.BACKUP_ROOT = self.archive_root
        backup_client.STATE_ROOT = self.root / "agent-state"
        self.addCleanup(setattr, backup_client, "BACKUP_ROOT", self.old_backup)
        self.addCleanup(setattr, backup_client, "STATE_ROOT", self.old_state)

    def command(self):
        return {
            "instance_id": "instance-one",
            "command_id": "c1",
            "action": "create",
            "policy": {"mode": "full", "compression": "gzip", "consistency": "live"},
        }

    def test_counts_all_physical_history_not_just_database_rows(self):
        folder = self.archive_root / "instance-one"
        create_tar(folder / "old.tar.gz", payload=True)
        create_tar(folder / "manifest-only.tar.gz", payload=False)
        (folder / "broken.tar.gz").write_bytes(b"invalid TAR")
        (folder / "import.partial").write_bytes(b"not finished")
        result = backup_inventory(self.archive_root, "instance-one")
        self.assertEqual(result["file_count"], 4)
        self.assertEqual(result["manifest_only_count"], 1)
        self.assertEqual(result["invalid_count"], 1)
        self.assertEqual(result["unverified_archive_count"], 1)
        self.assertFalse(result["restorability_confirmed"])
        self.assertEqual(
            result["bytes"],
            sum(path.stat().st_size for path in folder.iterdir())
        )
        self.assertFalse(any(path.name.startswith(".pruned") for path in folder.iterdir()))

    def test_multi_instance_separation_and_orphaned_archive(self):
        own = self.archive_root / "instance-one"
        other = self.archive_root / "instance-two"
        create_tar(own / "orphan-unindexed.tar.gz", payload=True)
        create_tar(other / "orphan-two.tar.gz", payload=False)
        a = backup_inventory(self.archive_root, "instance-one")
        b = backup_inventory(self.archive_root, "instance-two")
        self.assertEqual(a["file_count"], 1)
        self.assertEqual(b["file_count"], 1)
        self.assertEqual(
            a["bytes"] + b["bytes"],
            (own / "orphan-unindexed.tar.gz").stat().st_size
            + (other / "orphan-two.tar.gz").stat().st_size,
        )

    def test_nested_backup_root_is_not_double_charged(self):
        root = self.private / "backups"
        create_tar(root / "instance-one" / "old.tar.gz", payload=True)
        snapshot = quota_snapshot(self.record, root)
        self.assertTrue(snapshot["backup_nested_in_instance"])
        self.assertEqual(snapshot["total_used_bytes"],
                         snapshot["backup_used_bytes"] + len(b"live-world"))
        self.assertEqual(snapshot["instance_used_bytes"], len(b"live-world"))

    def test_symlinks_and_cross_instance_hardlinks_fail_closed(self):
        folder = self.archive_root / "instance-one"
        folder.mkdir()
        external = self.root / "sensitive"
        external.write_text("not a backup")
        (folder / "alias.tar.gz").symlink_to(external)
        with self.assertRaises(OSError):
            backup_inventory(self.archive_root, "instance-one")
        (folder / "alias.tar.gz").unlink()
        (folder / "hardlink.tar.gz").hardlink_to(external)
        with self.assertRaisesRegex(OSError, "hardlinked"):
            backup_inventory(self.archive_root, "instance-one")

    def test_shared_workshop_hardlinks_are_charged_conservatively_and_archived(self):
        # A Workshop cache file is hardlinked into the instance's private
        # content tree. The cache outside the private root is not archived.
        cache = self.root / "shared-workshop" / "mod.cpp"
        cache.parent.mkdir()
        payload = b"shared-workshop-fixture"
        cache.write_bytes(payload)
        mods = self.private / "content" / "workshop" / "steam-workshop:2289456201"
        mods.mkdir(parents=True)
        private_mod = mods / "mod.cpp"
        private_mod.hardlink_to(cache)
        self.assertEqual(private_mod.stat().st_nlink, 2)

        expected = len(b"live-world") + len(payload)
        snapshot = quota_snapshot(self.record, self.archive_root)
        self.assertEqual(snapshot["instance_used_bytes"], expected)
        self.assertEqual(source_size([self.private], self.private), expected)

        # Charge the full private file size to a second instance too: neither
        # owner gets a zero-cost shared inode or another owner's file.
        other = self.root / "instance-two"
        other.mkdir()
        (other / "mod.cpp").hardlink_to(cache)
        record_two = dict(self.record, instance_id="instance-two",
                          instance_state_root=str(other), files_root=str(other))
        self.assertEqual(
            quota_snapshot(record_two, self.archive_root)["instance_used_bytes"],
            len(payload),
        )

        with patch.object(backup_client, "get_instance", return_value=self.record):
            created = backup_client._create(self.config, self.command())
        with tarfile.open(created["artifact_path"], "r:*") as archive:
            files = [item for item in archive.getmembers()
                     if item.name.lstrip("./") == "content/workshop/steam-workshop:2289456201/mod.cpp"]
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].isfile())
            self.assertEqual(archive.extractfile(files[0]).read(), payload)
        self.assertEqual(cache.read_bytes(), payload)
        self.assertEqual(private_mod.read_bytes(), payload)

    def test_physical_archive_catalog_lists_imported_and_unindexed_files(self):
        folder = self.archive_root / "instance-one"
        folder.mkdir()
        one = folder / "import-001.tar.gz"
        two = folder / "historical-002.tgz"
        other = folder / "transfer.partial"
        one.write_bytes(b"x" * 150)
        two.write_bytes(b"y" * 200)
        other.write_bytes(b"z" * 50)
        result = physical_backup_catalog(self.archive_root, "instance-one")
        self.assertEqual(result["total_files"], 3)
        self.assertEqual(result["total_bytes"], 400)
        self.assertFalse(result["truncated"])
        ids = {x["backup_id"]: x for x in result["files"] if x["backup_id"]}
        self.assertEqual(set(ids), {"import-001", "historical-002"})
        self.assertTrue(all(x["kind"] == "archive_unverified" for x in ids.values()))
        self.assertFalse(any("path" in item for item in result["files"]))
        self.assertEqual(next(x for x in result["files"] if x["filename"]=="transfer.partial")["kind"], "other_file")

        smaller = physical_backup_catalog(self.archive_root, "instance-one", limit=2)
        self.assertTrue(smaller["truncated"])
        self.assertEqual(len(smaller["files"]), 2)
        self.assertEqual(smaller["total_bytes"], 400)
        self.assertEqual(len(list(folder.iterdir())), 3)

    def test_physical_catalog_does_not_follow_symlinks_or_hardlinks(self):
        folder = self.archive_root / "instance-one"
        folder.mkdir()
        target = self.root / "another-client.tar.gz"
        target.write_bytes(b"outside")
        shortcut = folder / "trick.tar.gz"
        shortcut.symlink_to(target)
        with self.assertRaisesRegex(OSError, "unsafe"):
            physical_backup_catalog(self.archive_root, "instance-one")
        shortcut.unlink()
        linked = folder / "linked.tar.gz"
        linked.hardlink_to(target)
        with self.assertRaisesRegex(OSError, "unsafe"):
            physical_backup_catalog(self.archive_root, "instance-one")

    def test_full_quota_blocks_without_touching_history_or_game(self):
        previous = self.archive_root / "instance-one" / "history.tar.gz"
        create_tar(previous, payload=True)
        before = previous.read_bytes()
        self.record["storage_limit_bytes"] = 256 * 1024
        with patch.object(backup_client, "get_instance", return_value=self.record),              patch.object(backup_client, "lifecycle") as game,              patch.object(backup_client, "_create_archive") as write:
            with self.assertRaisesRegex(OSError, "quota"):
                backup_client._create(self.config, self.command())
            game.assert_not_called()
            write.assert_not_called()
        self.assertEqual(previous.read_bytes(), before)

    def test_missing_quota_fails_closed_before_backup_or_stop(self):
        self.record.pop("storage_limit_bytes")
        with patch.object(backup_client, "get_instance", return_value=self.record),              patch.object(backup_client, "lifecycle") as game:
            with self.assertRaisesRegex(OSError, "quota is unavailable"):
                backup_client._create(self.config, self.command())
            game.assert_not_called()

    def test_post_write_overflow_removes_only_new_archive(self):
        command = self.command()
        previous = self.archive_root / "instance-one" / "history.tar.gz"
        create_tar(previous, payload=True)
        before = previous.read_bytes()
        self.record["storage_limit_bytes"] = 4 * 1024 * 1024
        def oversized(root, paths, destination, compression, manifest):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"x" * (5 * 1024 * 1024))
        with patch.object(backup_client, "get_instance", return_value=self.record),              patch.object(backup_client, "_create_archive", side_effect=oversized),              patch.object(backup_client, "lifecycle") as game:
            with self.assertRaisesRegex(OSError, "final archive exceeds"):
                backup_client._create(self.config, command)
            game.assert_not_called()
        self.assertEqual(previous.read_bytes(), before)
        self.assertEqual(
            [path.name for path in previous.parent.glob("*.tar.gz")],
            ["history.tar.gz"],
        )

    def test_successful_backup_charges_archives_within_limit(self):
        with patch.object(backup_client, "get_instance", return_value=self.record):
            first = backup_client._create(self.config, self.command())
            second = backup_client._create(self.config, self.command())
        self.assertGreater(second["quota_total_used_bytes"], first["quota_total_used_bytes"])
        inventory = backup_inventory(self.archive_root, "instance-one")
        self.assertEqual(inventory["file_count"], 2)
        self.assertEqual(inventory["bytes"], second["quota_backup_used_bytes"])
        self.assertTrue(Path(first["artifact_path"]).exists())

if __name__ == "__main__":
    unittest.main()
