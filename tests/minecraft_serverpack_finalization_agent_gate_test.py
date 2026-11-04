"""Static compatibility guards for the optional read-only Agent scan."""
import ast
from pathlib import Path
import unittest
R=Path(__file__).resolve().parents[1]/"agents/linux/runtime/agent.py"

class AgentGateTest(unittest.TestCase):
 def test_audit_is_opt_in(self):
  src=R.read_text()
  self.assertIn('os.environ.get("CAPIVARA_SERVERPACK_FINALIZATION_AUDIT")=="1"',src)
 def test_loop_never_dispatched_mutating_recovery(self):
  src=R.read_text()
  start=src.index('observations=scan_pending_finalizations(')
  end=src.index('for observation in observations:',start)
  self.assertNotIn('dispatch=',src[start:end])
  self.assertNotIn('enabled=True',src[start:end])
 def test_scan_does_not_depend_on_services(self):
  src=(R.parent/"minecraft_serverpack_finalization_scheduler.py").read_text()
  self.assertNotIn("subprocess",src)
  self.assertNotIn("os.system",src)
 def test_agent_compiles(self):
  compile(R.read_text(),str(R),"exec")
if __name__=="__main__":unittest.main()
