import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents/linux/runtime'))
import instance_runtime

ID='cli-000001-dayz-001'
SINCE='2026-10-14T12:33:10Z'
UNTIL='2026-10-14T12:37:10Z'


class LifecycleEvidenceTest(unittest.TestCase):
    def test_owned_systemd_instance_queries_journal(self):
        record={'instance_id':ID,'agent_id':'agent-test','adapter':'systemd'}
        with patch.object(instance_runtime,'_owned',return_value=record) as owned:
            with patch('systemd_journal_reader.read_systemd_transitions',return_value=[{'event':'stopped'}]) as reader:
                result=instance_runtime.systemd_lifecycle_evidence({'agent_id':'agent-test'},ID,since=SINCE,until=UNTIL)
        owned.assert_called_once()
        reader.assert_called_once_with(ID,since=SINCE,until=UNTIL)
        self.assertEqual(result['events'],[{'event':'stopped'}])
        self.assertFalse(result['verified_native_shutdown'])

    def test_unowned_instance_rejected_without_journal_access(self):
        with patch.object(instance_runtime,'_owned',side_effect=PermissionError('not owner')):
            with patch('systemd_journal_reader.read_systemd_transitions') as reader:
                with self.assertRaises(PermissionError):
                    instance_runtime.systemd_lifecycle_evidence({'agent_id':'other'},ID,since=SINCE,until=UNTIL)
                reader.assert_not_called()

    def test_other_adapter_rejected(self):
        record={'instance_id':ID,'agent_id':'agent-test','adapter':'other'}
        with patch.object(instance_runtime,'_owned',return_value=record):
            with patch('systemd_journal_reader.read_systemd_transitions') as reader:
                with self.assertRaises(ValueError):
                    instance_runtime.systemd_lifecycle_evidence({'agent_id':'agent-test'},ID,since=SINCE,until=UNTIL)
                reader.assert_not_called()


if __name__=='__main__':
    unittest.main()
