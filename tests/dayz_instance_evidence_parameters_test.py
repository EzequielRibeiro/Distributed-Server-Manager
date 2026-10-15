import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'database'))
from instance_evidence_parameters import normalize_command_parameters as normalize


class EvidenceParametersTest(unittest.TestCase):
    def setUp(self):
        self.params={'since':'2026-10-14T09:33:10-03:00','until':'2026-10-14T12:37:10Z'}

    def test_normalizes_timezone(self):
        self.assertEqual(normalize('systemd_lifecycle_evidence',self.params)['since'],'2026-10-14T12:33:10Z')

    def test_legacy_without_params(self):
        self.assertIsNone(normalize('restart'))

    def test_legacy_with_params_rejected(self):
        with self.assertRaises(ValueError):normalize('restart',self.params)

    def test_missing_param_rejected(self):
        with self.assertRaises(ValueError):normalize('systemd_lifecycle_evidence',{'since':self.params['since']})

    def test_extra_param_rejected(self):
        with self.assertRaises(ValueError):normalize('systemd_lifecycle_evidence',dict(self.params,override=True))

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):normalize('systemd_lifecycle_evidence',dict(self.params,since='2026-10-14T12:33:10'))

    def test_large_interval_rejected(self):
        with self.assertRaises(ValueError):normalize('systemd_lifecycle_evidence',dict(self.params,since='2026-10-14T12:00:00Z'))

    def test_reversed_interval_rejected(self):
        with self.assertRaises(ValueError):normalize('systemd_lifecycle_evidence',dict(self.params,since='2026-10-14T12:40:00Z'))


if __name__=='__main__':unittest.main()
