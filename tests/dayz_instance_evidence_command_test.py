import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents/linux/runtime'))
import instance_runtime

ID='cli-000001-dayz-001'


class EvidenceCommandTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.history=Path(tmp.name)/'history'
        self.results=Path(tmp.name)/'results'
        a=patch.object(instance_runtime,'HISTORY_DIR',self.history)
        b=patch.object(instance_runtime,'RESULT_DIR',self.results)
        a.start();b.start();self.addCleanup(a.stop);self.addCleanup(b.stop)
        self.command=dict(command_id='test-1',instance_id=ID,action='systemd_lifecycle_evidence',since='2026-10-14T12:33:10Z',until='2026-10-14T12:37:10Z')

    def test_valid_query_is_read_only(self):
        with patch.object(instance_runtime,'systemd_lifecycle_evidence',return_value={'events':[],'verified_native_shutdown':False}) as query:
            with patch.object(instance_runtime,'lifecycle') as lifecycle:
                result=instance_runtime.handle_command({'agent_id':'agent-test'},self.command)
        self.assertEqual(result['status'],'completed')
        query.assert_called_once()
        lifecycle.assert_not_called()

    def test_invalid_time_rejected_before_query(self):
        self.command['until']='2026-10-14T13:37:10Z'
        with patch.object(instance_runtime,'systemd_lifecycle_evidence') as query:
            result=instance_runtime.handle_command({'agent_id':'agent-test'},self.command)
        self.assertEqual(result['status'],'failed')
        query.assert_not_called()

    def test_unowned_instance_fails(self):
        with patch.object(instance_runtime,'_owned',side_effect=PermissionError('not owned')):
            result=instance_runtime.handle_command({'agent_id':'other'},self.command)
        self.assertEqual(result['status'],'failed')


if __name__=='__main__': unittest.main()
