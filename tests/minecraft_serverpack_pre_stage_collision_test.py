from __future__ import annotations
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agents/common'))
from minecraft_serverpack_pre_stage_collision import assess_pre_stage_committed_collision,PreStageCollisionEvidenceError

def sample():
 j={"kind":"CapivaraMinecraftServerPackMigrationSwap","phase":"committed","migration_plan_sha256":"a"*64}
 error="migration failed and rollback also failed: manual recovery required"
 return dict(instance_id="sample-005",agent_id="agent-demo",
 previous_request={"instance_id":"sample-005","agent_id":"agent-demo","selector":"26.1.2@26.1.2.109"},
 previous_result={"instance_id":"sample-005","status":"completed","minecraft_serverpack_migration":{"status":"completed","trace":["staged","swapped","ready","committed"],"target_loader_version":"26.1.2.109","migration_plan_sha256":"a"*64,"commit":{"status":"committed","journal":copy.deepcopy(j)}}},
 failed_request={"instance_id":"sample-005","agent_id":"agent-demo","selector":"26.1.2@26.1.2.124"},
 failed_result={"instance_id":"sample-005","status":"failed","current_step":"minecraft_serverpack_migration","error":error,"traceback":'callbacks["stage"] RuntimeError: Server Pack migration journal already exists callbacks["rollback"] RuntimeError: committed migration cannot be silently recovered'},
 failed_operation={"instance_id":"sample-005","agent_id":"agent-demo","operation":"minecraft_serverpack_migration","status":"failed","error":error},
 existing_journal=copy.deepcopy(j),filesystem_artifacts_absent=True,game_unit_inactive=True)

class CollisionTest(unittest.TestCase):
 def test_identical_prior_commit_proven_but_no_release(self):
  x=sample();orig=copy.deepcopy(x);r=assess_pre_stage_committed_collision(**x)
  self.assertEqual(r['classification'],'later_pre_stage_collision_with_previous_commit')
  self.assertFalse(r['operation_release_authorized']);self.assertFalse(r['new_migration_authorized']);self.assertEqual(x,orig)
 def test_mismatched_journal_fails(self):
  x=sample();x['existing_journal']['migration_plan_sha256']='b'*64
  with self.assertRaises(PreStageCollisionEvidenceError):assess_pre_stage_committed_collision(**x)
 def test_different_agent_or_instance_fails(self):
  for field in ['agent_id','instance_id']:
   x=sample();x[field]='wrong'
   with self.subTest(field=field),self.assertRaises(PreStageCollisionEvidenceError):assess_pre_stage_committed_collision(**x)
 def test_ambiguous_traceback_fails(self):
  x=sample();x['failed_result']['traceback']='callbacks["swap"] RuntimeError: committed migration cannot be silently recovered'
  with self.assertRaises(PreStageCollisionEvidenceError):assess_pre_stage_committed_collision(**x)
 def test_missing_artifacts_gate_fails(self):
  for key in ['filesystem_artifacts_absent','game_unit_inactive']:
   x=sample();x[key]=False
   with self.subTest(key=key),self.assertRaises(PreStageCollisionEvidenceError):assess_pre_stage_committed_collision(**x)
 def test_wrong_or_successful_outer_operation_fails(self):
  for status in ['completed','interrupted','recovered']:
   x=sample();x['failed_operation']['status']=status
   with self.subTest(status=status),self.assertRaises(PreStageCollisionEvidenceError):assess_pre_stage_committed_collision(**x)
 def test_no_distinct_selector_fails(self):
  x=sample();x['failed_request']['selector']=x['previous_request']['selector']
  with self.assertRaises(PreStageCollisionEvidenceError):assess_pre_stage_committed_collision(**x)
 def test_completed_trace_absent_fails(self):
  x=sample();x['previous_result']['minecraft_serverpack_migration']['trace']=['swapped']
  with self.assertRaises(PreStageCollisionEvidenceError):assess_pre_stage_committed_collision(**x)
if __name__=='__main__':unittest.main()
