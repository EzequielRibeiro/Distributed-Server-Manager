#!/usr/bin/env python3
from __future__ import annotations
import io
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"database",ROOT/"dashboard",ROOT/"core"):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from backend import DatabaseConfig
from backend_factory import create_backend
from deleted_backup_vault_repository import DeletedBackupVaultRepository

class DeletedBackupVaultTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.backend=create_backend(DatabaseConfig(driver="sqlite",database=str(self.root/"capivara.db")));self.backend.initialize()
  with self.backend.transaction() as c:
   c.execute("INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)",("controller-node","Controller","controller","active"))
   c.execute("INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)",("agent-node","Agent","agent","active"))
   c.execute("INSERT INTO controllers(id,node_id,name,status) VALUES (?,?,?,?)",("controller-one","controller-node","Controller","active"))
   c.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",("agent-one","controller-one","agent-node","Agent","active"))
   c.execute("INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)",(1,"controller-one","Customer","active"))
   c.execute("INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?,?)",("instance-one","agent-node","minecraft","minecraft.java.vanilla","Servidor Um","offline","controller-one","agent-one",1))
  self.vault=DeletedBackupVaultRepository(self.backend,self.root);self.vault.initialize()
 def tearDown(self):self.backend.close();self.temp.cleanup()
 def _complete_backup(self,item):
  self.vault.backups.record_agent_state("agent-one",[{"command_id":item["backup_job_id"],"instance_id":"instance-one","action":"create","status":"completed","backup_id":"backup-final","artifact_path":"/agent/backups/instance-one/backup-final.tar.gz","size_bytes":6,"sha256":"agent-sha"}])
 def test_backup_is_exported_before_remove_and_survives_instance_row_deletion(self):
  item,idempotent=self.vault.start("instance-one",requested_by="owner")
  self.assertFalse(idempotent);same,again=self.vault.start("instance-one",requested_by="owner");self.assertTrue(again);self.assertEqual(item["vault_id"],same["vault_id"])
  self._complete_backup(item);item=self.vault.reconcile(item["vault_id"]);self.assertEqual(item["status"],"export_pending");self.assertTrue(item["transfer_id"])
  transfer=self.vault.artifacts.receive_from_agent(item["transfer_id"],"agent-one",io.BytesIO(b"backup"),6);self.assertEqual(transfer["status"],"completed")
  item=self.vault.reconcile(item["vault_id"]);self.assertEqual(item["status"],"removal_pending");self.assertTrue(item["remove_command_id"]);artifact=Path(item["artifact_path"]);self.assertEqual(artifact.read_bytes(),b"backup")
  with self.backend.transaction() as c:c.execute("DELETE FROM instances WHERE id=?",("instance-one",))
  item=self.vault.reconcile(item["vault_id"]);self.assertEqual(item["status"],"ready");self.assertIsNotNone(item["deleted_at"]);self.assertTrue(artifact.is_file())
  path,visible=self.vault.artifact_for_customer(item["vault_id"],1);self.assertEqual(path.read_bytes(),b"backup");self.assertEqual(visible["customer_id"],1)
  with self.assertRaises(PermissionError):self.vault.artifact_for_customer(item["vault_id"],2)
  done=self.vault.complete_download(item["vault_id"],1);self.assertEqual(done["status"],"downloaded");self.assertFalse(artifact.exists())
 def test_failed_final_backup_blocks_export_and_remove(self):
  item,_=self.vault.start("instance-one",requested_by="owner")
  self.vault.backups.record_agent_state("agent-one",[{"command_id":item["backup_job_id"],"instance_id":"instance-one","action":"create","status":"failed","last_error":"disk full"}])
  item=self.vault.reconcile(item["vault_id"]);self.assertEqual(item["status"],"failed");self.assertIn("disk full",item["last_error"]);self.assertIsNone(item.get("remove_command_id"))

if __name__=="__main__":unittest.main()
