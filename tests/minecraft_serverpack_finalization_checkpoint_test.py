"""Tests for crash boundaries before and after journal rename."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/"agents/linux/runtime"))
import minecraft_serverpack_finalization_checkpoint as checkpoint

PLAN="a"*64
LOADER="26.1.2.109"


class CheckpointTest(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
  self.root=Path(self.t.name)/"instance"
  self.control=self.root/".dsm"
  self.control.mkdir(parents=True)
  self.journal={"phase":"committed","migration_plan_sha256":PLAN,"target_loader_version":LOADER}
  self.raw=(json.dumps(self.journal,sort_keys=True)+"\n").encode()
  self.digest=hashlib.sha256(self.raw).hexdigest()
  self.live=self.control/"minecraft-serverpack-migration.json"
  self.live.write_bytes(self.raw)
 def scan(self):
  return checkpoint.discover_committed_checkpoint(self.root,plan_sha256=PLAN,loader_version=LOADER)
 def archived(self):
  history=self.control/"migration-history"/self.digest[:24]
  history.mkdir(parents=True)
  (history/"minecraft-serverpack-migration.json").write_bytes(self.raw)
  (history/"runtime.migration-rollback").mkdir()
  (self.control/"minecraft-serverpack-archive-checkpoint.json").write_text(
    json.dumps({"schema_version":1,"sha256":self.digest}))
  self.live.unlink()
  return history
 def test_live_committed(self):
  self.assertEqual(self.scan()["status"],"active")
 def test_archived_committed(self):
  self.archived()
  self.assertEqual(self.scan()["status"],"archived")
  self.assertEqual(self.scan()["sha256"],self.digest)
 def test_archive_without_checkpoint_rejected(self):
  self.archived()
  (self.control/"minecraft-serverpack-archive-checkpoint.json").unlink()
  with self.assertRaises(checkpoint.CheckpointVerificationError):self.scan()
 def test_archive_checksum_mismatch(self):
  archive=self.archived()
  (archive/"minecraft-serverpack-migration.json").write_text("tampered")
  with self.assertRaises(checkpoint.CheckpointVerificationError):self.scan()
 def test_live_checkpoint_mismatch(self):
  (self.control/"minecraft-serverpack-archive-checkpoint.json").write_text(
    json.dumps({"schema_version":1,"sha256":"b"*64}))
  with self.assertRaises(checkpoint.CheckpointVerificationError):self.scan()
 def test_wrong_plan_rejected(self):
  self.journal["migration_plan_sha256"]="b"*64
  self.live.write_text(json.dumps(self.journal))
  with self.assertRaises(checkpoint.CheckpointVerificationError):self.scan()
 def test_swapped_journal_rejected(self):
  self.journal["phase"]="swapped"
  self.live.write_text(json.dumps(self.journal))
  with self.assertRaises(checkpoint.CheckpointVerificationError):self.scan()
 def test_unarchived_rollback_rejected(self):
  self.archived()
  (self.root/"runtime.migration-rollback").mkdir()
  with self.assertRaises(checkpoint.CheckpointVerificationError):self.scan()
 def test_archive_symlink_rejected(self):
  archive=self.archived()
  archive.rename(archive.with_name("actual"))
  archive.symlink_to(archive.with_name("actual"),target_is_directory=True)
  with self.assertRaises(checkpoint.CheckpointVerificationError):self.scan()
 def test_live_journal_symlink_rejected(self):
  self.live.unlink()
  self.live.symlink_to(self.control/"not-existing")
  with self.assertRaises(checkpoint.CheckpointVerificationError):self.scan()
 def test_missing_root_rejected(self):
  with self.assertRaises(checkpoint.CheckpointVerificationError):
   checkpoint.discover_committed_checkpoint(self.root/"missing",plan_sha256=PLAN,loader_version=LOADER)
 def test_missing_archived_rollback_rejected(self):
  archive=self.archived()
  (archive/"runtime.migration-rollback").rmdir()
  with self.assertRaises(checkpoint.CheckpointVerificationError):self.scan()

if __name__=="__main__":unittest.main()
