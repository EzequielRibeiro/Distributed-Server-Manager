"""systemd Stopped after SIGKILL cannot be a clean historical restart."""
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agents/linux/runtime'))
sys.path.insert(0, str(ROOT / 'dashboard/workers'))
from systemd_journal_evidence import select_systemd_transitions
from dayz_native_transition import observed_systemd_restart

INSTANCE = 'cli-000001-dayz-001'
UNIT = f'capivara-instance-{INSTANCE}.service'
BEGIN = '2026-11-09T09:05:00Z'
END = '2026-11-09T09:10:00Z'
STOP_ID = '9d1aaa27d60140bd96365438aad20286'
START_ID = '39f53479d3a045ac8e11786248231fbf'
FAIL_ID = 'd9b373ed55a64feb8242e02dbe79a49c'


def event(message_id, time, **props):
    stamp = int(datetime.fromisoformat(time.replace('Z', '+00:00')).timestamp() * 1_000_000)
    return {'_COMM': 'systemd', '_PID': '1', 'UNIT': UNIT,
            'MESSAGE_ID': message_id, '__REALTIME_TIMESTAMP': str(stamp), **props}


def payload(observations):
    return {'kind': 'CapivaraSystemdLifecycleObservations',
            'instance_id': INSTANCE, 'verified_native_shutdown': False,
            'events': observations}


class ForcedStopEvidenceTest(unittest.TestCase):
    def selected(self, events):
        return select_systemd_transitions(INSTANCE, events, since=BEGIN, until=END)

    def observed(self, observations):
        return observed_systemd_restart(instance_id=INSTANCE, expected_at=BEGIN,
                                        deadline_at=END, observations=payload(observations),
                                        authenticated=True)

    def test_failed_timeout_before_stopped_is_not_clean_restart(self):
        events = self.selected([
            event(FAIL_ID, '2026-11-09T09:06:02Z', MESSAGE=f"{UNIT}: Failed with result 'timeout'."),
            event(STOP_ID, '2026-11-09T09:06:02Z', MESSAGE=f'Stopped {UNIT}.'),
            event(START_ID, '2026-11-09T09:08:04Z', MESSAGE=f'Started {UNIT}.')])
        self.assertEqual([x['event'] for x in events], ['failed', 'stopped', 'started'])
        self.assertEqual(events[0]['failure_reason'], 'timeout')
        self.assertFalse(self.observed(events))

    def test_successful_stop_then_start_remains_observed(self):
        events = self.selected([
            event(STOP_ID, '2026-11-09T09:06:02Z'),
            event(START_ID, '2026-11-09T09:08:04Z')])
        self.assertTrue(self.observed(events))

    def test_injected_failure_message_without_manager_id_is_ignored(self):
        untrusted = event('unknown-id', '2026-11-09T09:06:01Z',
                          MESSAGE=f"{UNIT}: Failed with result 'timeout'.")
        events = self.selected([untrusted, event(STOP_ID, '2026-11-09T09:06:02Z'),
                                event(START_ID, '2026-11-09T09:08:04Z')])
        self.assertEqual([x['event'] for x in events], ['stopped', 'started'])
        self.assertTrue(self.observed(events))

    def test_failure_wrong_unit_and_non_systemd_pid_are_ignored(self):
        events = self.selected([
            event(FAIL_ID, '2026-11-09T09:05:58Z', UNIT='ssh.service'),
            event(FAIL_ID, '2026-11-09T09:05:59Z', _PID='1000'),
            event(STOP_ID, '2026-11-09T09:06:02Z'),
            event(START_ID, '2026-11-09T09:08:04Z')])
        self.assertEqual([x['event'] for x in events], ['stopped', 'started'])
        self.assertTrue(self.observed(events))

    def test_failure_after_start_does_not_invalidate_prior_restart(self):
        events = self.selected([
            event(STOP_ID, '2026-11-09T09:06:02Z'),
            event(START_ID, '2026-11-09T09:08:04Z'),
            event(FAIL_ID, '2026-11-09T09:09:00Z')])
        self.assertTrue(self.observed(events))

    def test_unauthenticated_restart_never_accepted(self):
        events = self.selected([event(STOP_ID, '2026-11-09T09:06:02Z'),
                                event(START_ID, '2026-11-09T09:08:04Z')])
        self.assertFalse(observed_systemd_restart(instance_id=INSTANCE, expected_at=BEGIN,
                         deadline_at=END, observations=payload(events), authenticated=False))


if __name__ == '__main__':
    unittest.main()
