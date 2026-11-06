"""Real filesystem crash-replay tests, no game runtime interaction."""
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"agents/linux/runtime"))
from minecraft_serverpack_finalization_bridge import reconcile_published_migration,FinalizationBridgeError
PLAN="a"*64


class BridgeTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.addCleanup(self.tmp.cleanup)
  self.base=Path(self.tmp.name)
  self.op=self.base/"outer.json"
  self.res=self.base/"result.json"
  self.hist=self.base/"migration-history"
  self.hist.mkdir()
  self.journal={"phase":"committed","migration_plan_sha256":PLAN,"target_loader_version":"26.1.2.109"}
  self.raw=(json.dumps(self.journal,sort_keys=True)+"\n").encode()
  digest=hashlib.sha256(self.raw).hexdigest()
  self.archive=self.hist/digest[:24]
  self.archive.mkdir()
  (self.archive/"minecraft-serverpack-migration.json").write_bytes(self.raw)
  self.outer={"instance_id":"test001","agent_id":"agent001","operation":"minecraft_serverpack_migration",
              "status":"finalization_pending","migration_plan_sha256":PLAN}
  self.detail={"status":"completed","migration_plan_sha256":PLAN,"target_loader_version":"26.1.2.109",
               "trace":["committed","finalized"],"finalization":{"status":"archived","sha256":digest}}
  self.result={"status":"completed","provisioning_id":"provision001","instance_id":"test001",
               "minecraft_serverpack_migration":self.detail}
  self.save()
 def save(self):
  self.op.write_text(json.dumps(self.outer))
  self.res.write_text(json.dumps(self.result))
 def execute(self):
  return reconcile_published_migration(instance_id="test001",agent_id="agent001",
                                       operation_path=self.op,provisioning_path=self.res,
                                       history_root=self.hist)
 def test_crash_replay_repairs_only_outer(self):
  self.assertEqual(self.execute()["status"],"operation_reconciled")
  self.assertEqual(json.loads(self.op.read_text())["status"],"completed")
  self.assertEqual(self.execute()["status"],"already_completed")
 def test_missing_history_cannot_release(self):
  (self.archive/"minecraft-serverpack-migration.json").unlink()
  with self.assertRaises(FinalizationBridgeError):self.execute()
  self.assertEqual(json.loads(self.op.read_text())["status"],"finalization_pending")
 def test_tampered_history_cannot_release(self):
  (self.archive/"minecraft-serverpack-migration.json").write_text("tampered")
  with self.assertRaises(FinalizationBridgeError):self.execute()
 def test_different_migration_cannot_release(self):
  self.detail["migration_plan_sha256"]="b"*64;self.save()
  with self.assertRaises((FinalizationBridgeError,RuntimeError,ValueError)):self.execute()
 def test_wrong_owner_cannot_release(self):
  self.outer["agent_id"]="someoneelse";self.save()
  with self.assertRaises(Exception):self.execute()
 def test_running_result_cannot_release(self):
  self.result["status"]="running";self.save()
  with self.assertRaises(Exception):self.execute()
 def test_history_symlink_cannot_release(self):
  self.hist.rename(self.base/"realhist")
  self.hist.symlink_to(self.base/"realhist",target_is_directory=True)
  with self.assertRaises(FinalizationBridgeError):self.execute()

if __name__=="__main__":unittest.main()
