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


if __name__=="__main__":
    unittest.main()
