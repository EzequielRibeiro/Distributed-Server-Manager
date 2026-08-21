#!/usr/bin/env python3
from __future__ import annotations
import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"core",ROOT/"database",ROOT/"dashboard",ROOT/"agents"/"linux"/"runtime"):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from agent_heartbeat_api import record_agent_heartbeat
from backend import DatabaseConfig
from backend_factory import create_backend
from backup_http import dispatch_backup_get,dispatch_backup_post
from backup_platform import BackupValidationError,normalize_policy
from backup_repository import BackupRepository
class BackupContractTest(unittest.TestCase):
 def test_policy_is_deterministic_and_game_agnostic(self):
  raw={"instance_id":"instance-c5","agent_id":"agent-c5","mode":"full","consistency":"live","interval_seconds":600,"retention_count":3}
  one=normalize_policy(raw);two=normalize_policy(raw);self.assertEqual(one["checksum"],two["checksum"]);self.assertEqual(one["kind"],"CapivaraBackupPolicy")
 def test_rejects_unsafe_paths_and_short_intervals(self):
  with self.assertRaises(BackupValidationError):normalize_policy({"instance_id":"i","agent_id":"a","include_paths":["../secret"]})
  with self.assertRaises(BackupValidationError):normalize_policy({"instance_id":"i","agent_id":"a","interval_seconds":30})
class BackupRepositoryTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.backend=create_backend(DatabaseConfig(driver="sqlite",database=str(Path(self.temp.name)/"c5.db")));self.backend.initialize()
  with self.backend.transaction() as c:
   c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("controller-node","Controller","controller"));c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("agent-node","Agent","agent"));c.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",("controller-c5","controller-node","C5"));c.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",("agent-c5","controller-c5","agent-node","Agent C5","active"));c.execute("INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)",("customer-c5","controller-c5","Customer","active"));c.execute("INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",("instance-c5","agent-node","game.generic","Generic","offline","controller-c5","agent-c5","customer-c5"))
  self.repo=BackupRepository(self.backend);self.repo.initialize()
 def tearDown(self):self.backend.close();self.temp.cleanup()
 def policy(self,retention=3):return {"instance_id":"instance-c5","mode":"full","consistency":"live","interval_seconds":600,"retention_count":retention}
 def test_revisions_noop_and_schedule(self):
  first=self.repo.put_policy(self.policy(),requested_by="test");same=self.repo.put_policy(self.policy(),requested_by="test");second=self.repo.put_policy(self.policy(5),requested_by="test")
  self.assertTrue(first["changed"]);self.assertFalse(same["changed"]);self.assertEqual(second["policy"]["revision"],2);self.assertEqual(len(self.repo.history(second["policy"]["policy_id"])),2)
  commands=self.repo.commands_for_agent("agent-c5");self.assertEqual(len(commands),1);self.assertEqual(commands[0]["action"],"create")
  again=self.repo.commands_for_agent("agent-c5");self.assertEqual(commands[0]["command_id"],again[0]["command_id"])
 def test_heartbeat_ack_and_no_spoof(self):
  self.repo.put_policy(self.policy());cmd=self.repo.commands_for_agent("agent-c5")[0]
  ack={"command_id":cmd["command_id"],"status":"completed","backup_id":"backup-c5","size_bytes":42,"sha256":"a"*64,"artifact_path":"/var/lib/capivara-agent/backups/instance-c5/backup-c5.tar.gz"}
  result=record_agent_heartbeat("agent-c5",{"agent_id":"agent-c5","backup_state":[ack]},backend=self.backend);self.assertEqual(result["backup_count"],0);self.assertEqual(self.repo.get_job(cmd["command_id"])["backup_id"],"backup-c5")
  self.assertEqual(self.repo.record_agent_state("other-agent",[ack]),0)
 def test_manual_restore_delete_and_http_rbac(self):
  self.repo.put_policy(self.policy());admin={"role":"admin","username":"root"}
  status,created=dispatch_backup_post("/api/backups",{"operation":"create","instance_id":"instance-c5"},user=admin,backend=self.backend);self.assertEqual(status,202);self.assertEqual(created["action"],"create")
  status,body=dispatch_backup_get("/api/backups","kind=policies",user=admin,backend=self.backend);self.assertEqual(status,200);self.assertEqual(body["count"],1)
  status,_=dispatch_backup_get("/api/backups","kind=policies",user={"role":"customer"},backend=self.backend);self.assertEqual(status,403)
if __name__=="__main__":unittest.main()
