import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents/linux/runtime'))
from systemd_observation_history import record_observation


class ObservationHistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.instance = 'cli-000001-dayz-001'
        self.state = dict(adapter='systemd', unit=f'capivara-instance-{self.instance}.service', active_state='active', main_pid=123, invocation_id='run-1')

    def read(self):
        return json.loads((self.root / 'systemd-observations' / f'{self.instance}.json').read_text())

    def test_persists_first_observation(self):
        record_observation(self.root, self.instance, self.state)
        self.assertEqual(self.read()[0]['main_pid'], 123)

    def test_deduplicates_identical_state(self):
        record_observation(self.root, self.instance, self.state)
        record_observation(self.root, self.instance, self.state)
        self.assertEqual(len(self.read()), 1)

    def test_retains_distinct_transition(self):
        record_observation(self.root, self.instance, self.state)
        self.state.update(main_pid=None, active_state='inactive', invocation_id=None)
        record_observation(self.root, self.instance, self.state)
        self.assertEqual([r['active_state'] for r in self.read()], ['active', 'inactive'])

    def test_limits_history(self):
        for i in range(70):
            self.state['main_pid'] = i + 1
            record_observation(self.root, self.instance, self.state)
        self.assertEqual(len(self.read()), 64)
        self.assertEqual(self.read()[0]['main_pid'], 7)

    def test_rejects_wrong_unit(self):
        self.state['unit'] = 'other.service'
        with self.assertRaises(ValueError):
            record_observation(self.root, self.instance, self.state)

    def test_rejects_invalid_instance_id(self):
        with self.assertRaises(ValueError):
            record_observation(self.root, '../unsafe', self.state)


if __name__ == '__main__':
    unittest.main()
