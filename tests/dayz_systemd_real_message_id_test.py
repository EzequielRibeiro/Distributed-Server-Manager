import sys
import unittest
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agents/linux/runtime'))
from systemd_journal_evidence import select_systemd_transitions

class RealSystemdMessageTest(unittest.TestCase):
    def test_dayz_deactivation_and_restart(self):
        unit='capivara-instance-cli-000001-dayz-001.service'
        def event(message_id,stamp):
            return {'_COMM':'systemd','_PID':'1','UNIT':unit,'MESSAGE_ID':message_id,'__REALTIME_TIMESTAMP':str(int(datetime.fromisoformat(stamp.replace('Z','+00:00')).timestamp()*1000000))}
        events=[event('7ad2d189f7e94e70a38c781354912448','2026-10-14T12:36:11Z'),event('39f53479d3a045ac8e11786248231fbf','2026-10-14T12:36:19Z')]
        result=select_systemd_transitions('cli-000001-dayz-001',events,since='2026-10-14T12:35:00Z',until='2026-10-14T12:37:00Z')
        self.assertEqual([item['event'] for item in result],['stopped','started'])

if __name__=='__main__':unittest.main()
