#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dashboard' / 'workers'))
from dayz_native_transition import verified_native_transition


class DayZNativeTransitionTest(unittest.TestCase):
    def setUp(self):
        self.data = dict(
            instance_id='cli-000001-dayz-001',
            old_pid=3738932,
            new_pid=224240,
            expected_at='2026-10-14T12:33:10Z',
            deadline_at='2026-10-14T12:37:10Z',
            evidence=dict(
                instance_id='cli-000001-dayz-001',
                old_pid=3738932,
                new_pid=224240,
                stopped_at='2026-10-14T12:36:11Z',
                restarted_at='2026-10-14T12:36:19Z',
            ),
            authenticated=True,
        )

    def test_authenticated_transition(self):
        self.assertTrue(verified_native_transition(**self.data))

    def test_unverified_transition_rejected(self):
        self.data['authenticated'] = False
        self.assertFalse(verified_native_transition(**self.data))

    def test_different_instance_rejected(self):
        self.data['evidence']['instance_id'] = 'another-instance'
        self.assertFalse(verified_native_transition(**self.data))

    def test_unrelated_pid_rejected(self):
        self.data['evidence']['old_pid'] = 123
        self.assertFalse(verified_native_transition(**self.data))

    def test_late_stop_rejected(self):
        self.data['evidence']['stopped_at'] = '2026-10-14T12:37:11Z'
        self.assertFalse(verified_native_transition(**self.data))

    def test_restart_before_stop_rejected(self):
        self.data['evidence']['restarted_at'] = '2026-10-14T12:36:10Z'
        self.assertFalse(verified_native_transition(**self.data))

    def test_timezone_missing_rejected(self):
        self.data['evidence']['stopped_at'] = '2026-10-14T12:36:11'
        self.assertFalse(verified_native_transition(**self.data))


if __name__ == '__main__':
    unittest.main()
