"""Isolated Agent evidence command tests: no journalctl or live service calls."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agents/linux/runtime'))
import instance_runtime as runtime

class EvidenceExecutionTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patchers=[patch.object(runtime,'HISTORY_DIR',Path(self.temp.name)/'history'),patch.object(runtime,'RESULT_DIR',Path(self.temp.name)/'results')]
        for p in self.patchers:p.start();self.addCleanup(p.stop)
        self.request={'command_id':'evidence-1','agent_id':'agent-test','instance_id':'instance-test','action':'systemd_lifecycle_evidence','since':'2026-10-14T09:30:00Z','until':'2026-10-14T09:40:00Z'}

    def test_read_only_command_returns_unverified_evidence(self):
        record={'instance_id':'instance-test','agent_id':'agent-test','adapter':'systemd'}
        with patch.object(runtime,'get_instance',return_value=record),patch('systemd_journal_reader.read_systemd_transitions',return_value=[{'event':'stopped'}]) as reader:
            result=runtime.handle_command({'agent_id':'agent-test'},self.request)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['result']['kind'],'CapivaraSystemdLifecycleObservations')
        self.assertIs(result['result']['verified_native_shutdown'],False)
        reader.assert_called_once()

    def test_cross_agent_request_fails_closed(self):
        record={'instance_id':'instance-test','agent_id':'other-agent','adapter':'systemd'}
        with patch.object(runtime,'get_instance',return_value=record):
            result=runtime.handle_command({'agent_id':'agent-test'},self.request)
        self.assertEqual(result['status'],'failed')
        self.assertNotIn('result',result)

if __name__=='__main__':unittest.main()
