from __future__ import annotations
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agents/common'))
from minecraft_serverpack_migration_preflight import require_empty_serverpack_slot,MinecraftServerPackPreflightError

class PreflightTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)/'synthetic';(self.root/'.dsm').mkdir(parents=True)
 def test_clean_slot_does_not_mutate(self):
  require_empty_serverpack_slot(self.root)
  self.assertEqual(list((self.root/'.dsm').iterdir()),[])
 def test_committed_journal_is_rejected_before_game_stop(self):
  (self.root/'.dsm/minecraft-serverpack-migration.json').write_text('{"phase":"committed"}')
  with self.assertRaisesRegex(MinecraftServerPackPreflightError,'explicit finalization'):
   require_empty_serverpack_slot(self.root)
  self.assertEqual((self.root/'.dsm/minecraft-serverpack-migration.json').read_text(),'{"phase":"committed"}')
 def test_each_transaction_artifact_blocks(self):
  names=['.dsm/.minecraft-serverpack-migration.json.tmp', '.dsm/minecraft-serverpack-archive-checkpoint.json', '.dsm/.minecraft-serverpack-archive-checkpoint.tmp', 'runtime.migration-stage','runtime.migration-rollback','runtime.migration-failed']
  for name in names:
   with self.subTest(name=name):
    p=self.root/name;p.touch()
    with self.assertRaises(MinecraftServerPackPreflightError):require_empty_serverpack_slot(self.root)
    p.unlink()
 def test_symlink_redirect_rejected(self):
  (self.root/'.dsm/minecraft-serverpack-migration.json').symlink_to('/nonexistent-minecraft-journal')
  with self.assertRaises(MinecraftServerPackPreflightError):require_empty_serverpack_slot(self.root)
 def test_control_symlink_rejected(self):
  (self.root/'.dsm').rmdir();(self.root/'.dsm').symlink_to(self.root)
  with self.assertRaises(MinecraftServerPackPreflightError):require_empty_serverpack_slot(self.root)
 def test_root_symlink_rejected(self):
  link=Path(self.tmp.name)/'linked';link.symlink_to(self.root,target_is_directory=True)
  with self.assertRaises(MinecraftServerPackPreflightError):require_empty_serverpack_slot(link)
 def test_missing_control_is_rejected_without_creation(self):
  (self.root/'.dsm').rmdir()
  with self.assertRaises(MinecraftServerPackPreflightError):require_empty_serverpack_slot(self.root)
  self.assertFalse((self.root/'.dsm').exists())
if __name__=='__main__':unittest.main()
