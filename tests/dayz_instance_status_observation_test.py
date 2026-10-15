import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents/linux/runtime'))
import instance_runtime


class InstanceStatusObservationTest(unittest.TestCase):
    def setUp(self):
        self.instance = 'cli-000001-dayz-001'
        self.record = dict(instance_id=self.instance, agent_id='agent-test', adapter='systemd')
        self.state = dict(adapter='systemd', unit=f'capivara-instance-{self.instance}.service', available=True, active_state='active', main_pid=123, invocation_id='inv1')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patches = [patch.object(instance_runtime, '_owned', return_value=self.record), patch.object(instance_runtime, '_adapter_state', return_value=self.state), patch.object(instance_runtime, 'STATE_DIR', Path(self.temp.name))]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_status_records_systemd_observation(self):
        result = instance_runtime.status({'agent_id': 'agent-test'}, self.instance)
        self.assertEqual(result['observed_state'], 'running')
        self.assertTrue((Path(self.temp.name) / 'systemd-observations' / f'{self.instance}.json').exists())

    def test_status_survives_history_write_failure(self):
        with patch('systemd_observation_history.record_observation', side_effect=OSError('read-only')):
            result = instance_runtime.status({'agent_id': 'agent-test'}, self.instance)
        self.assertEqual(result['observed_state'], 'running')

    def test_non_systemd_does_not_record(self):
        self.state['adapter'] = 'other'
        result = instance_runtime.status({'agent_id': 'agent-test'}, self.instance)
        self.assertEqual(result['observed_state'], 'running')
        self.assertFalse((Path(self.temp.name) / 'systemd-observations').exists())


if __name__ == '__main__':
    unittest.main()
