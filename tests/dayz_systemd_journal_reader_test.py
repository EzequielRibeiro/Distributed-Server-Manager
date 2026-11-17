import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents/linux/runtime'))
from systemd_journal_reader import read_systemd_transitions

ID='cli-000001-dayz-001'
SINCE='2026-10-14T12:33:10Z'
UNTIL='2026-10-14T12:37:10Z'
STOP='9d1aaa27d60140bd96365438aad20286'


def event():
    at=int(datetime.fromisoformat('2026-10-14T12:36:11+00:00').timestamp()*1_000_000)
    return dict(UNIT=f'capivara-instance-{ID}.service',_COMM='systemd',_PID='1',MESSAGE_ID=STOP,__REALTIME_TIMESTAMP=str(at))


class JournalReaderTest(unittest.TestCase):
    def test_reads_bounded_manager_event(self):
        calls=[]
        def runner(cmd):
            calls.append(cmd)
            return SimpleNamespace(returncode=0,stdout=json.dumps(event())+'\n')
        result=read_systemd_transitions(ID,since=SINCE,until=UNTIL,runner=runner)
        self.assertEqual([item['event'] for item in result],['stopped'])
        self.assertIn(f'UNIT=capivara-instance-{ID}.service',calls[0])

    def test_failed_journal_is_not_empty_success(self):
        with self.assertRaises(RuntimeError):
            read_systemd_transitions(ID,since=SINCE,until=UNTIL,runner=lambda _:SimpleNamespace(returncode=1,stdout=''))

    def test_oversized_window_rejected(self):
        with self.assertRaises(ValueError):
            read_systemd_transitions(ID,since='2026-10-14T12:00:00Z',until=UNTIL,runner=lambda _:None)

    def test_malformed_json_rejected(self):
        with self.assertRaises(ValueError):
            read_systemd_transitions(ID,since=SINCE,until=UNTIL,runner=lambda _:SimpleNamespace(returncode=0,stdout='{bad'))

    def test_invalid_instance_rejected(self):
        with self.assertRaises(ValueError):
            read_systemd_transitions('../bad',since=SINCE,until=UNTIL,runner=lambda _:None)


if __name__=='__main__':
    unittest.main()
