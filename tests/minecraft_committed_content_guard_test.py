from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agents/common'))
from minecraft_committed_content_guard import refuse_content_sync_during_serverpack_transaction,MinecraftCommittedContentGuardError

class GuardTest(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.r=Path(self.t.name)/'instance';(self.r/'.dsm').mkdir(parents=True)
 def test_no_journal_allows_normal_content_sync(self):
  refuse_content_sync_during_serverpack_transaction(self.r)
  self.assertEqual(list((self.r/'.dsm').iterdir()),[])
 def test_each_phase_fails_closed_without_mutation(self):
  for phase in ('prepared','swapping','swapped','recovering','recovered','committed'):
   with self.subTest(phase=phase):
    path=self.r/'.dsm/minecraft-serverpack-migration.json';payload={'kind':'CapivaraMinecraftServerPackMigrationSwap','phase':phase};path.write_text(json.dumps(payload));original=path.read_bytes()
    with self.assertRaisesRegex(MinecraftCommittedContentGuardError,'explicitly finalized'):
     refuse_content_sync_during_serverpack_transaction(self.r)
    self.assertEqual(original,path.read_bytes());path.unlink()
 def test_invalid_or_tampered_journal_is_blocked(self):
  p=self.r/'.dsm/minecraft-serverpack-migration.json'
  for value in ('not json','[]','{}',json.dumps({'kind':'other','phase':'committed'})):
   p.write_text(value)
   with self.assertRaises(MinecraftCommittedContentGuardError):refuse_content_sync_during_serverpack_transaction(self.r)
 def test_orphan_temp_and_archive_checkpoint_block(self):
  for name in ('.minecraft-serverpack-migration.json.tmp','minecraft-serverpack-archive-checkpoint.json'):
   p=self.r/'.dsm'/name;p.touch()
   with self.assertRaises(MinecraftCommittedContentGuardError):refuse_content_sync_during_serverpack_transaction(self.r)
   p.unlink()
 def test_completed_archive_checkpoint_allows_sync(self):
  history=self.r/'.dsm/migration-history'
  data=b'{"phase":"committed","kind":"CapivaraMinecraftServerPackMigrationSwap"}\\n'
  digest=hashlib.sha256(data).hexdigest()
  archived=history/digest[:24];archived.mkdir(parents=True)
  (archived/'minecraft-serverpack-migration.json').write_bytes(data)
  (archived/'runtime.migration-rollback').mkdir()
  checkpoint=self.r/'.dsm/minecraft-serverpack-archive-checkpoint.json'
  checkpoint.write_text(json.dumps({'schema_version':1,'sha256':digest}))
  refuse_content_sync_during_serverpack_transaction(self.r)
  (self.r/'.dsm/minecraft-serverpack-migration.json').write_bytes(data)
  with self.assertRaises(MinecraftCommittedContentGuardError):
   refuse_content_sync_during_serverpack_transaction(self.r)
  (self.r/'.dsm/minecraft-serverpack-migration.json').unlink()
  (archived/'runtime.migration-rollback').rmdir()
  with self.assertRaises(MinecraftCommittedContentGuardError):
   refuse_content_sync_during_serverpack_transaction(self.r)
 def test_archive_checkpoint_corruption_blocks_sync(self):
  p=self.r/'.dsm/minecraft-serverpack-archive-checkpoint.json'
  for content in ('{}','not json',json.dumps({'schema_version':1,'sha256':'z'*64})):
   p.write_text(content)
   with self.assertRaises(MinecraftCommittedContentGuardError):
    refuse_content_sync_during_serverpack_transaction(self.r)
 def test_archive_checkpoint_temp_blocks_sync(self):
  p=self.r/'.dsm/.minecraft-serverpack-archive-checkpoint.tmp';p.write_text('pending')
  with self.assertRaises(MinecraftCommittedContentGuardError):
   refuse_content_sync_during_serverpack_transaction(self.r)
 def test_symlinks_and_missing_root_block(self):
  p=self.r/'.dsm/minecraft-serverpack-migration.json';p.symlink_to('/nonexistent-journal')
  with self.assertRaises(MinecraftCommittedContentGuardError):refuse_content_sync_during_serverpack_transaction(self.r)
  p.unlink();ln=Path(self.t.name)/'symlink';ln.symlink_to(self.r,target_is_directory=True)
  with self.assertRaises(MinecraftCommittedContentGuardError):refuse_content_sync_during_serverpack_transaction(ln)
  with self.assertRaises(MinecraftCommittedContentGuardError):refuse_content_sync_during_serverpack_transaction(Path(self.t.name)/'missing')
 def test_unarchived_committed_blocks_even_when_other_content_is_unchanged(self):
  p=self.r/'.dsm/minecraft-serverpack-migration.json';p.write_text(json.dumps({'kind':'CapivaraMinecraftServerPackMigrationSwap','phase':'committed'}))
  (self.r/'runtime').mkdir();(self.r/'runtime/mods').mkdir();(self.r/'runtime/mods/a.jar').write_bytes(b'A')
  with self.assertRaises(MinecraftCommittedContentGuardError):refuse_content_sync_during_serverpack_transaction(self.r)
  self.assertEqual((self.r/'runtime/mods/a.jar').read_bytes(),b'A')
if __name__=='__main__':unittest.main()
