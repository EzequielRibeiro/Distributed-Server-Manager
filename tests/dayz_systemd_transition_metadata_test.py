#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agents' / 'linux' / 'runtime'))
from adapters.systemd import SystemdAdapter


class SystemdTransitionMetadataTest(unittest.TestCase):
    def test_status_includes_invocation_and_activation_metadata(self):
        commands = []
        def runner(command, timeout):
            commands.append(command)
            return (0, '\n'.join([
                'LoadState=loaded', 'ActiveState=active', 'SubState=running',
                'MainPID=224240', 'NRestarts=0', 'Result=success',
                'InvocationID=abc123',
                'ActiveEnterTimestamp=Wed 2026-10-14 09:36:19 -03',
                'InactiveExitTimestamp=Wed 2026-10-14 09:36:19 -03',
            ]), '')
        state = SystemdAdapter(runner=runner).status({'instance_id': 'cli-000001-dayz-001'})
        self.assertEqual(state['main_pid'], 224240)
        self.assertEqual(state['invocation_id'], 'abc123')
        self.assertIn('09:36:19', state['active_enter_timestamp'])
        self.assertIn('--property=InvocationID', commands[0])
        self.assertIn('--property=ActiveEnterTimestamp', commands[0])
        self.assertIn('--property=InactiveExitTimestamp', commands[0])

    def test_missing_optional_fields_remain_none(self):
        def runner(command, timeout):
            return (0, 'LoadState=loaded\nActiveState=inactive\nMainPID=0\n', '')
        state = SystemdAdapter(runner=runner).status({'instance_id': 'cli-000001-dayz-001'})
        self.assertIsNone(state['invocation_id'])
        self.assertIsNone(state['active_enter_timestamp'])
        self.assertIsNone(state['inactive_exit_timestamp'])


if __name__ == '__main__':
    unittest.main()
