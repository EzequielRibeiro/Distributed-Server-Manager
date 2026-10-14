import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents/linux/runtime'))
from systemd_evidence_request import validate_evidence_request


class EvidenceRequestTest(unittest.TestCase):
    def setUp(self):
        self.request = dict(command_id='cmd-1', instance_id='cli-000001-dayz-001', action='systemd_lifecycle_evidence', since='2026-10-14T12:33:10Z', until='2026-10-14T12:37:10Z')

    def test_valid(self):
        self.assertEqual(validate_evidence_request(self.request)['instance_id'], self.request['instance_id'])

    def test_extra_field_rejected(self):
        self.request['override'] = True
        with self.assertRaises(ValueError): validate_evidence_request(self.request)

    def test_wrong_action_rejected(self):
        self.request['action'] = 'stop'
        with self.assertRaises(ValueError): validate_evidence_request(self.request)

    def test_invalid_instance_rejected(self):
        self.request['instance_id'] = '../other'
        with self.assertRaises(ValueError): validate_evidence_request(self.request)

    def test_missing_timezone_rejected(self):
        self.request['since'] = '2026-10-14T12:33:10'
        with self.assertRaises(ValueError): validate_evidence_request(self.request)

    def test_oversized_window_rejected(self):
        self.request['since'] = '2026-10-14T12:00:00Z'
        with self.assertRaises(ValueError): validate_evidence_request(self.request)


if __name__ == '__main__': unittest.main()
