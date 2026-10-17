"""A stale game-data result must not overwrite newer independent Steam status."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class StaleResultGuardTest(unittest.TestCase):
 def test_result_write_requires_matching_active_job(self):
  source=(ROOT/'database/server_update_repository.py').read_text()
  start=source.index(' def apply_game_data_result(')
  body=source[start:]
  self.assertIn('AND active_job_id={ph}',body)
  self.assertIn("str(job['job_id'])",body)
  self.assertIn('if cursor.rowcount != 1:return',body)
if __name__=='__main__':unittest.main()
