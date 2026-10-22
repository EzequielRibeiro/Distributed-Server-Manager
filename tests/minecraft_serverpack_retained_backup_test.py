#!/usr/bin/env python3
"""Regression tests for Agent-owned retained backup attestation."""
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"agents/linux/runtime"))
import minecraft_serverpack_migration_provisioning as provisioning

INSTANCE="cli-000001-minecraft-005"
BACKUP="backup-test"


def make_archive(path,instance=INSTANCE,backup=BACKUP,unsafe=False,manifest=True):
    with tarfile.open(path,"w:gz") as archive:
        if manifest:
            payload=json.dumps({"kind":"CapivaraInstanceBackup",
                "backup_format":"capivara-instance","backup_id":backup,
                "source_instance":instance}).encode()
            entry=tarfile.TarInfo(".capivara-backup-manifest.json")
            entry.size=len(payload)
            archive.addfile(entry,io.BytesIO(payload))
        entry=tarfile.TarInfo("world/level.dat")
        entry.size=4
        archive.addfile(entry,io.BytesIO(b"data"))
        if unsafe:
            entry=tarfile.TarInfo("../escape")
            entry.size=1
            archive.addfile(entry,io.BytesIO(b"x"))


class RetainedBackupTest(unittest.TestCase):
    def verify(self,path,backup=BACKUP):
        with patch.object(provisioning,"find_backup_artifact",return_value=path):
            return provisioning._attest_retained_backup(backup,INSTANCE)

    def test_valid_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/"backup.tar.gz"
            make_archive(archive)
            result=self.verify(archive)
            self.assertEqual(result["backup_id"],BACKUP)
            self.assertEqual(result["size_bytes"],archive.stat().st_size)
            self.assertTrue(result["integrity_verified"])
            self.assertEqual(len(result["sha256"]),64)

    def test_missing_artifact_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(provisioning.MinecraftServerPackProvisioningHomologationError):
                self.verify(Path(folder)/"absent.tar.gz")

    def test_wrong_instance_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/"backup.tar.gz"
            make_archive(archive,instance="other-instance")
            with self.assertRaises(provisioning.MinecraftServerPackProvisioningHomologationError):
                self.verify(archive)

    def test_wrong_backup_id_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/"backup.tar.gz"
            make_archive(archive,backup="other-backup")
            with self.assertRaises(provisioning.MinecraftServerPackProvisioningHomologationError):
                self.verify(archive)

    def test_missing_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/"backup.tar.gz"
            make_archive(archive,manifest=False)
            with self.assertRaises(provisioning.MinecraftServerPackProvisioningHomologationError):
                self.verify(archive)

    def test_traversal_member_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/"backup.tar.gz"
            make_archive(archive,unsafe=True)
            with self.assertRaises(provisioning.MinecraftServerPackProvisioningHomologationError):
                self.verify(archive)

    def test_selector_chooses_newest_valid_backup(self):
        import os
        import backup_client
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)/INSTANCE
            directory.mkdir()
            old=directory/"old-backup.tar.gz"
            newest=directory/"new-backup.tar.gz"
            make_archive(old,backup="old-backup")
            make_archive(newest,backup="new-backup")
            os.utime(old,(100,100))
            os.utime(newest,(200,200))
            with patch.object(backup_client,"BACKUP_ROOT",Path(folder)):
                self.assertEqual(
                    provisioning._select_retained_backup_id({},INSTANCE),
                    "new-backup",
                )

    def test_selector_skips_newest_invalid_backup(self):
        import os
        import backup_client
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)/INSTANCE
            directory.mkdir()
            valid=directory/"valid-backup.tar.gz"
            invalid=directory/"invalid-backup.tar.gz"
            make_archive(valid,backup="valid-backup")
            make_archive(invalid,backup="incorrect-manifest-id")
            os.utime(valid,(100,100))
            os.utime(invalid,(200,200))
            with patch.object(backup_client,"BACKUP_ROOT",Path(folder)):
                self.assertEqual(
                    provisioning._select_retained_backup_id({},INSTANCE),
                    "valid-backup",
                )

    def test_selector_rejects_missing_backup_directory(self):
        import backup_client
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(backup_client,"BACKUP_ROOT",Path(folder)):
                with self.assertRaises(provisioning.MinecraftServerPackProvisioningHomologationError):
                    provisioning._select_retained_backup_id({},INSTANCE)

    def test_selector_rejects_only_invalid_backups(self):
        import backup_client
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)/INSTANCE
            directory.mkdir()
            make_archive(directory/"invalid.tar.gz",backup="other-id")
            with patch.object(backup_client,"BACKUP_ROOT",Path(folder)):
                with self.assertRaises(provisioning.MinecraftServerPackProvisioningHomologationError):
                    provisioning._select_retained_backup_id({},INSTANCE)


    def test_explicit_backup_id_is_attested(self):
        with patch.object(provisioning,"_attest_retained_backup",return_value={"integrity_verified":True}) as attest:
            result=provisioning._select_retained_backup_id(
                {"minecraft_serverpack_retained_backup_id":"selected-backup"},INSTANCE)
        self.assertEqual(result,"selected-backup")
        attest.assert_called_once_with("selected-backup",INSTANCE)

    def test_explicit_invalid_backup_is_rejected(self):
        with patch.object(provisioning,"_attest_retained_backup",
                          side_effect=provisioning.MinecraftServerPackProvisioningHomologationError("invalid")):
            with self.assertRaises(provisioning.MinecraftServerPackProvisioningHomologationError):
                provisioning._select_retained_backup_id(
                    {"minecraft_serverpack_retained_backup_id":"invalid-backup"},INSTANCE)

    def test_explicit_blank_backup_is_rejected(self):
        with self.assertRaises(provisioning.MinecraftServerPackProvisioningHomologationError):
            provisioning._select_retained_backup_id(
                {"minecraft_serverpack_retained_backup_id":"  "},INSTANCE)


    def test_backup_id_glob_metacharacters_rejected_before_lookup(self):
        for unsafe in ("*", "backup?", "backup[0]", "../backup", "dir/backup", "dir\\\\backup"):
            with self.subTest(unsafe=unsafe):
                with patch.object(provisioning,"find_backup_artifact") as lookup:
                    with self.assertRaises(provisioning.MinecraftServerPackProvisioningHomologationError):
                        provisioning._attest_retained_backup(unsafe,INSTANCE)
                    lookup.assert_not_called()

    def test_legacy_backup_id_remains_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/"legacy.tar.gz"
            make_archive(archive,backup="legacy-backup")
            with patch.object(provisioning,"find_backup_artifact",return_value=archive):
                result=provisioning._attest_retained_backup("legacy-backup",INSTANCE)
            self.assertEqual(result["backup_id"],"legacy-backup")



if __name__=="__main__":
    unittest.main()
