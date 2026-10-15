import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agents/linux/runtime'))
from systemd_evidence_request import validate_evidence_request

class AgentEnvelopeTest(unittest.TestCase):
    def test_controller_envelope(self):
        request={'command_id':'command-123','agent_id':'agent-test','instance_id':'instance-test','action':'systemd_lifecycle_evidence','since':'2026-10-14T09:30:00Z','until':'2026-10-14T09:40:00Z'}
        normalized=validate_evidence_request(request)
        self.assertEqual(normalized['instance_id'],'instance-test')
        self.assertNotIn('agent_id',normalized)

    def test_extra_field_rejected(self):
        request={'command_id':'command-123','agent_id':'agent-test','instance_id':'instance-test','action':'systemd_lifecycle_evidence','since':'2026-10-14T09:30:00Z','until':'2026-10-14T09:40:00Z','verified_native_shutdown':True}
        with self.assertRaises(ValueError):validate_evidence_request(request)

if __name__=='__main__':unittest.main()
