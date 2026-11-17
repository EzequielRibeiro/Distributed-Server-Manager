import importlib.util
from pathlib import Path
from copy import deepcopy
import unittest

P=Path(__file__).resolve().parents[1]/"agents/linux/runtime/minecraft_serverpack_finalization_recovery.py"
spec=importlib.util.spec_from_file_location("finalization_recovery",P)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
OP={"instance_id":"instance-test","agent_id":"agent-test","operation":"minecraft_serverpack_migration","status":"finalization_pending"}
SWAP={"phase":"committed","migration_plan_sha256":"a"*64,"target_loader_version":"26.1.2.109"}
DETAIL={"status":"finalization_pending","trace":["committed","finalization_pending"],"migration_plan_sha256":"a"*64,"target_loader_version":"26.1.2.109"}
PROV={"instance_id":"instance-test","status":"running","current_step":"minecraft_serverpack_finalization","finalization_state":"pending","minecraft_serverpack_migration":DETAIL}

class TestFinalizationRecovery(unittest.TestCase):
 def run_case(self,op=None,prov=None,swap=None,inactive=True):
  called=[]
  def arch():
   called.append(True);return {"status":"archived"}
  try:
   result=m.retry_committed_finalization(operation=op if op is not None else OP,provisioning=prov if prov is not None else PROV,swap_journal=swap if swap is not None else SWAP,instance_id="instance-test",agent_id="agent-test",service_inactive=inactive,archive=arch)
   return result,called
  except m.FinalizationRecoveryError:
   return None,called

 def test_success(self):
  value,called=self.run_case();self.assertEqual(value["status"],"finalized");self.assertEqual(len(called),1)
 def test_active_service_denied(self):
  value,called=self.run_case(inactive=False);self.assertIsNone(value);self.assertFalse(called)
 def test_wrong_owner_denied(self):
  value,called=self.run_case(op={**OP,"agent_id":"other"});self.assertIsNone(value);self.assertFalse(called)
 def test_nonterminal_swap_denied(self):
  value,called=self.run_case(swap={**SWAP,"phase":"swapped"});self.assertIsNone(value);self.assertFalse(called)
 def test_different_plan_denied(self):
  value,called=self.run_case(swap={**SWAP,"migration_plan_sha256":"b"*64});self.assertIsNone(value);self.assertFalse(called)
 def test_completed_provisioning_denied(self):
  value,called=self.run_case(prov={**PROV,"status":"completed"});self.assertIsNone(value);self.assertFalse(called)
 def test_missing_committed_trace_denied(self):
  value,called=self.run_case(prov={**PROV,"minecraft_serverpack_migration":{**DETAIL,"trace":[]}});self.assertIsNone(value);self.assertFalse(called)
 def test_unexpected_archive_result_denied(self):
  with self.assertRaises(m.FinalizationRecoveryError):
   m.retry_committed_finalization(operation=OP,provisioning=PROV,swap_journal=SWAP,instance_id="instance-test",agent_id="agent-test",service_inactive=True,archive=lambda:{"status":"unknown"})

class TestRestartRecovery(unittest.TestCase):
 def setup_case(self):
  op={**OP,"finalization_phase":"restart_pending"}
  detail={**DETAIL,"commit":{"initial_active_state":"active"},
          "finalization":{"status":"restart_pending","archive_status":"archived","history":"/tmp/isolated/history","sha256":"a"*64}}
  prov={**PROV,"minecraft_serverpack_migration":detail}
  journal=dict(SWAP)
  return op,prov,journal
 def run_case(self,*,op=None,prov=None,journal=None,inactive=True,observed="active"):
  original_op,original_prov,original_journal=self.setup_case()
  events=[]
  def restart():
   events.append("restart")
   return observed
  return m.retry_archived_restart(
   operation=original_op if op is None else op,
   provisioning=original_prov if prov is None else prov,
   archived_journal=original_journal if journal is None else journal,
   instance_id="instance-test",agent_id="agent-test",
   observed_inactive=inactive,restart=restart),events

 def test_restart_pending_recovers_original_active_state(self):
  result,events=self.run_case()
  self.assertEqual(result["status"],"restart_recovered")
  self.assertEqual(result["observed_state"],"active")
  self.assertEqual(result["rollback_performed"],False)
  self.assertEqual(events,["restart"])
 def test_restart_pending_recovers_original_inactive_state(self):
  op,prov,journal=self.setup_case()
  prov["minecraft_serverpack_migration"]["commit"]["initial_active_state"]="inactive"
  result,events=self.run_case(prov=prov,observed="inactive")
  self.assertEqual(result["observed_state"],"inactive")
 def test_mismatched_checkpoint_rejected(self):
  op,prov,journal=self.setup_case()
  journal["migration_plan_sha256"]="f"*64
  with self.assertRaisesRegex(m.FinalizationRecoveryError,"differs"):
   self.run_case(journal=journal)
 def test_running_instance_rejected(self):
  with self.assertRaisesRegex(m.FinalizationRecoveryError,"ambiguous"):
   self.run_case(inactive=False)
 def test_original_service_state_required(self):
  op,prov,journal=self.setup_case()
  prov["minecraft_serverpack_migration"]["commit"].pop("initial_active_state")
  with self.assertRaisesRegex(m.FinalizationRecoveryError,"unknown"):
   self.run_case(prov=prov)
 def test_different_resulting_state_rejected(self):
  with self.assertRaisesRegex(m.FinalizationRecoveryError,"differs"):
   self.run_case(observed="inactive")
 def test_wrong_owner_rejected(self):
  op,prov,journal=self.setup_case()
  op["agent_id"]="foreign"
  with self.assertRaisesRegex(m.FinalizationRecoveryError,"does not match"):
   self.run_case(op=op)
 def test_no_commit_rejected(self):
  op,prov,journal=self.setup_case()
  prov["minecraft_serverpack_migration"]["trace"]=[]
  with self.assertRaisesRegex(m.FinalizationRecoveryError,"differs"):
   self.run_case(prov=prov)

if __name__=="__main__":unittest.main()
