"""Verify privileged archival boundary and result projection via AST."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
P = ROOT/"agents/linux/runtime/minecraft_serverpack_migration_provisioning.py"
E = ROOT/"agents/linux/runtime/provisioning_executor.py"

def function_body(name):
 tree = ast.parse(P.read_text())
 matches = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
 assert len(matches) == 1
 return ast.unparse(matches[0])

class FinalizationOrderTests(unittest.TestCase):
 def test_commit_restores_then_stops_before_commit(self):
  src=function_body("commit")
  self.assertLess(src.index("_restore_initial_running_state("),src.index("_ensure_stopped_after_candidate_failure("))
  self.assertLess(src.index("_ensure_stopped_after_candidate_failure("),src.index('minecraft_serverpack_swap_phase('))
 def test_finalize_archives_before_restoring_service(self):
  src=function_body("finalize")
  self.assertLess(src.index("_ensure_stopped_after_candidate_failure("),src.index('minecraft_serverpack_swap_phase('))
  self.assertLess(src.index('minecraft_serverpack_swap_phase('),src.index("_restore_initial_running_state("))
 def test_finalize_rejects_unknown_archive_status(self):
  src=function_body("finalize")
  self.assertIn("'archived'",src)
  self.assertIn("'already_archived'",src)
 def test_finalize_is_hooked_in_transaction(self):
  self.assertIn('"finalize":finalize',P.read_text())
 def test_public_completion_uses_final_observed_state(self):
  src=E.read_text()
  self.assertIn('(detail.get("finalization") or {}).get("observed_state")',src)
 def test_rollback_does_not_archive_a_committed_migration(self):
  source=function_body("rollback")
  self.assertNotIn("archive-committed",source)
  self.assertIn("recover",source)
if __name__=="__main__":unittest.main()
