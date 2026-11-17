import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents/linux/runtime'))
from systemd_journal_evidence import select_systemd_transitions

UNIT='capivara-instance-cli-000001-dayz-001.service'
SINCE='2026-10-14T12:33:10Z'
UNTIL='2026-10-14T12:37:10Z'
STOP='9d1aaa27d60140bd96365438aad20286'
START='39f53479d3a045ac8e11786248231fbf'


def event(message_id, at=1791981371000000, **changes):
    value=dict(UNIT=UNIT, _COMM='systemd', _PID='1', MESSAGE_ID=message_id, __REALTIME_TIMESTAMP=str(at))
    value.update(changes)
    return value


class JournalEvidenceTest(unittest.TestCase):
    def select(self, items):
        return select_systemd_transitions('cli-000001-dayz-001', items, since=SINCE, until=UNTIL)

    def test_explicit_stop_start(self):
        from datetime import datetime
        def micros(s):
            return int(datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()*1_000_000)
        items=[event(STOP,micros('2026-10-14T12:36:11Z')),event(START,micros('2026-10-14T12:36:19Z'))]
        self.assertEqual([x['event'] for x in self.select(items)], ['stopped','started'])

    def test_rejects_other_unit(self):
        self.assertEqual(self.select([event(STOP, UNIT='other.service')]),[])

    def test_rejects_non_manager(self):
        self.assertEqual(self.select([event(STOP, _PID='999')]),[])

    def test_rejects_unknown_message(self):
        self.assertEqual(self.select([event('unknown')]),[])

    def test_rejects_invalid_window(self):
        with self.assertRaises(ValueError):
            select_systemd_transitions('cli-000001-dayz-001',[],since=UNTIL,until=SINCE)


if __name__=='__main__':
    unittest.main()
