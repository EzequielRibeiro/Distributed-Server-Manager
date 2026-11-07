from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import sys, unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agents/common'))
from minecraft_serverpack_collision_recovery_plan import build_collision_recovery_plan,CollisionRecoveryPlanError

def inp():
 journal={"phase":"committed","migration_plan_sha256":"a"*64}
 return dict(collision={"classification":"later_pre_stage_collision_with_previous_commit","status":"manual_recovery_design_required","read_only":True,"operation_release_authorized":False,"journal_unchanged_from_previous_commit":True,"instance_id":"synthetic","agent_id":"a"},current_operation={"instance_id":"synthetic","agent_id":"a","operation":"minecraft_serverpack_migration","status":"failed"},current_swap_journal=deepcopy(journal),prior_completed_journal=deepcopy(journal),original_rollback_digest_matches=True,active_managed_digest_matches=True,loader_verified=True,content_archive_verified=True,world_backup_verified=True,game_unit_inactive=True,exclusive_instance_lock_held=True)

class TestRecoveryPlan(unittest.TestCase):
 def test_all_valid_still_does_not_execute(self):
  args=inp();before=deepcopy(args);r=build_collision_recovery_plan(**args)
  self.assertEqual(r['status'],'ready_for_supervised_implementation');self.assertFalse(r['execution_authorized']);self.assertEqual(args,before)
 def test_each_integrity_failure_blocks(self):
  for field in ['original_rollback_digest_matches','active_managed_digest_matches','loader_verified','content_archive_verified','world_backup_verified','game_unit_inactive','exclusive_instance_lock_held']:
   with self.subTest(field=field):
    args=inp();args[field]=False;r=build_collision_recovery_plan(**args)
    self.assertEqual(r['status'],'blocked');self.assertEqual(r['blockers'],[field]);self.assertFalse(r['execution_authorized'])
 def test_missing_operation_identity_fails(self):
  args=inp();args['current_operation']['instance_id']='other'
  with self.assertRaises(CollisionRecoveryPlanError):build_collision_recovery_plan(**args)
 def test_changed_prior_journal_fails(self):
  args=inp();args['current_swap_journal']['migration_plan_sha256']='b'*64
  with self.assertRaises(CollisionRecoveryPlanError):build_collision_recovery_plan(**args)
 def test_no_collision_authorization_fails(self):
  args=inp();args['collision']['operation_release_authorized']=True
  with self.assertRaises(CollisionRecoveryPlanError):build_collision_recovery_plan(**args)
 def test_status_must_be_failed(self):
  args=inp();args['current_operation']['status']='recovered'
  with self.assertRaises(CollisionRecoveryPlanError):build_collision_recovery_plan(**args)
if __name__=='__main__':unittest.main()
