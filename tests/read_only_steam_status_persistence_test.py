"""Isolated contract tests for read-only Steam observation persistence."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock
ROOT=Path(__file__).resolve().parents[1]
for directory in ('core','database','dashboard'):
 sys.path.insert(0,str(ROOT/directory))
from server_update_repository import ServerUpdateRepository

class ReadOnlySteamStatusPersistenceTest(unittest.TestCase):
 def setUp(self):
  self.repo=ServerUpdateRepository.__new__(ServerUpdateRepository)
  self.repo.dialect=MagicMock(placeholder='?')
  self.session=MagicMock()
  self.session.execute.return_value.fetchone.return_value={'target_key':'223350','active_job_id':None,'selection_json':'{}'}
  class Context:
   def __enter__(inner):return self.session
   def __exit__(inner,*args):return False
  self.repo.session=lambda transaction=False:Context()
  self.detail={'provider':'steam','app_id':'223350','state':'update_available','installed_version':'24570360','available_version':'25460313'}
 def test_persists_without_enqueuing(self):
  result=self.repo.record_read_only_probe('cli-000001-dayz-001',self.detail)
  self.assertEqual(result['state'],'update_available')
  self.assertEqual(result['source'],'read_only_steam_probe')
  self.assertEqual(self.session.execute.call_count,2)
  self.assertIn('UPDATE instance_update_state SET installed_version=',self.session.execute.call_args.args[0])
  self.assertNotIn('queue',self.session.execute.call_args.args[0])
 def test_rejects_app_mismatch(self):
  with self.assertRaises(ValueError):self.repo.record_read_only_probe('dayz',{**self.detail,'app_id':'999'})
  self.assertEqual(self.session.execute.call_count,1)
 def test_rejects_active_operation(self):
  self.session.execute.return_value.fetchone.return_value={'target_key':'223350','active_job_id':'running','selection_json':'{}'}
  with self.assertRaises(RuntimeError):self.repo.record_read_only_probe('dayz',self.detail)
  self.assertEqual(self.session.execute.call_count,1)
 def test_rejects_branch_mismatch(self):
  with self.assertRaises(ValueError):self.repo.record_read_only_probe('dayz',{**self.detail,'branch':'experimental'})
  self.assertEqual(self.session.execute.call_count,1)
 def test_rejects_inconsistent_state(self):
  with self.assertRaises(ValueError):self.repo.record_read_only_probe('dayz',{**self.detail,'state':'up_to_date'})
  self.session.execute.assert_not_called()
 def test_rejects_malformed_versions(self):
  with self.assertRaises(ValueError):self.repo.record_read_only_probe('dayz',{**self.detail,'available_version':'bad'})
  self.session.execute.assert_not_called()

if __name__=='__main__':unittest.main()
