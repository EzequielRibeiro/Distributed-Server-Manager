"""Independent status sync never queues or applies game updates."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
ROOT=Path(__file__).resolve().parents[1]
for directory in ('core','database','dashboard','dashboard/workers'):
 sys.path.insert(0,str(ROOT/directory))
from read_only_steam_status_sync import sync

class ReadOnlySteamStatusSyncTest(unittest.TestCase):
 def test_probes_selection_then_persists_without_queue(self):
  backend=MagicMock()
  selection='{"provider":"steam","install":{"package_id":"223350"},"install_dir":"/tmp/dayz"}'
  detail={'provider':'steam','app_id':'223350','branch':'public','state':'update_available','installed_version':'1','available_version':'2'}
  with patch('server_update_repository.ServerUpdateRepository') as repository:
   repo=repository.return_value
   repo._row.return_value={'selection_json':selection}
   repo.record_read_only_probe.return_value={'state':'update_available'}
   probe=MagicMock(return_value=detail)
   self.assertEqual(sync('dayz',backend=backend,probe=probe),{'state':'update_available'})
   probe.assert_called_once_with(__import__('json').loads(selection))
   repo.record_read_only_probe.assert_called_once_with('dayz',detail)
   repo.queue_check.assert_not_called()
   repo.queue_update.assert_not_called()
 def test_nonsteam_fails_closed(self):
  with patch('server_update_repository.ServerUpdateRepository') as repository:
   repository.return_value._row.return_value={'selection_json':'{"provider":"http"}'}
   with self.assertRaises(ValueError):sync('dayz',backend=MagicMock(),probe=MagicMock())
   repository.return_value.record_read_only_probe.assert_not_called()
 def test_unknown_instance_fails_closed(self):
  with patch('server_update_repository.ServerUpdateRepository') as repository:
   repository.return_value._row.return_value=None
   with self.assertRaises(KeyError):sync('missing',backend=MagicMock(),probe=MagicMock())

if __name__=='__main__':unittest.main()
