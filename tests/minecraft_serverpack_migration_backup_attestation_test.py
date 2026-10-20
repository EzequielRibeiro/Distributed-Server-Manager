"""Independent retained-backup attestation using disposable archives."""
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agents/linux/runtime'))
import minecraft_serverpack_migration_provisioning as migration


class RetainedBackupAttestationTest(unittest.TestCase):
    def archive(self, root, *, instance='lab-instance', backup='lab-backup', member='runtime/level.dat'):
        path = root / 'backup.tar.gz'
        with tarfile.open(path, 'w:gz') as output:
            manifest = json.dumps({
                'kind': 'CapivaraInstanceBackup', 'backup_format': 'capivara-instance',
                'backup_id': backup, 'source_instance': instance,
            }).encode()
            for name, data in ((migration.MANIFEST_NAME, manifest), (member, b'world-data')):
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                output.addfile(entry, io.BytesIO(data))
        return path

    def test_valid_retained_backup_is_independently_attested(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = self.archive(Path(temp))
            with patch.object(migration, 'find_backup_artifact', return_value=archive):
                proof = migration._attest_retained_backup('lab-backup', 'lab-instance')
            self.assertTrue(proof['integrity_verified'])
            self.assertEqual(proof['size_bytes'], archive.stat().st_size)
            self.assertEqual(len(proof['sha256']), 64)

    def test_backup_for_different_instance_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = self.archive(Path(temp), instance='other-instance')
            with patch.object(migration, 'find_backup_artifact', return_value=archive):
                with self.assertRaisesRegex(migration.MinecraftServerPackProvisioningHomologationError, 'independent verification'):
                    migration._attest_retained_backup('lab-backup', 'lab-instance')

    def test_unsafe_archive_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = self.archive(Path(temp), member='../escape')
            with patch.object(migration, 'find_backup_artifact', return_value=archive):
                with self.assertRaisesRegex(migration.MinecraftServerPackProvisioningHomologationError, 'independent verification'):
                    migration._attest_retained_backup('lab-backup', 'lab-instance')

    def test_unsafe_backup_identifier_is_rejected_before_lookup(self):
        with patch.object(migration, 'find_backup_artifact') as lookup:
            with self.assertRaisesRegex(migration.MinecraftServerPackProvisioningHomologationError, 'unsafe'):
                migration._attest_retained_backup('../escape', 'lab-instance')
            lookup.assert_not_called()
