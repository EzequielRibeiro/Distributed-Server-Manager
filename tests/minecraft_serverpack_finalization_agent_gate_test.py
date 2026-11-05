"""Static compatibility guards for the optional read-only Agent scan."""
import ast
from pathlib import Path
import unittest
R=Path(__file__).resolve().parents[1]/"agents/linux/runtime/agent.py"

class AgentGateTest(unittest.TestCase):
 def test_audit_is_opt_in(self):
  src=R.read_text()
  self.assertIn('os.environ.get("CAPIVARA_SERVERPACK_FINALIZATION_AUDIT")=="1"',src)
 def test_mutating_recovery_is_not_unconditionally_enabled(self):
  src=R.read_text()
  self.assertIn('CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE',src)
  self.assertIn('CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE_INSTANCE',src)
  self.assertIn('dispatch=dispatch_completed if (reconcile or recover) else None',src)
  self.assertIn('enabled=reconcile or recover',src)
 def test_recover_requires_independent_ack_and_existing_feature_policy(self):
  src=R.read_text()
  self.assertIn('CAPIVARA_SERVERPACK_FINALIZATION_RECOVER_ACK',src)
  self.assertIn('recovery_feature_allowed(',src)
  self.assertIn('recover_pending_operational(',src)
 def test_agent_never_dispatches_restart_or_archive(self):
  src=R.read_text()
  self.assertNotIn('retry_archived_restart(',src)
  self.assertNotIn('retry_committed_finalization(',src)
 def test_scan_does_not_depend_on_services(self):
  src=(R.parent/"minecraft_serverpack_finalization_scheduler.py").read_text()
  self.assertNotIn("subprocess",src)
  self.assertNotIn("os.system",src)
 def test_agent_compiles(self):
  compile(R.read_text(),str(R),"exec")
if __name__=="__main__":unittest.main()
