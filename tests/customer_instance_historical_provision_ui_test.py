from pathlib import Path
import unittest
SOURCE=(Path(__file__).resolve().parents[1]/'dashboard/web/customer-instance-v2.js').read_text(encoding='utf-8')
class HistoricalProvisionUITests(unittest.TestCase):
 def test_running_verified_loader_explains_stale_99_percent_progress(self):
  self.assertIn('pr.current_runtime_diagnosis==="running_verified_installation_history_unresolved"&&running',SOURCE)
  self.assertIn('O registro de instalação em 99% é histórico e aguarda validação',SOURCE)
 def test_unverified_failure_is_not_suppressed(self):
  self.assertIn('const retryable=provisionStatus==="failed"',SOURCE)
  self.assertIn('const progress=Math.min(100,Number(pr.progress||0))',SOURCE)
if __name__=='__main__':unittest.main()
