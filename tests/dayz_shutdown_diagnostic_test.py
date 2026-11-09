#!/usr/bin/env python3
"""Bounded read-only diagnosis of the upstream DayZ Linux RPT signature."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agents/common'))
from dayz_shutdown_diagnostic import suspected_linux_130_messages_issue


class DayZShutdownDiagnosticTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.profiles = self.root / 'profiles'
        self.profiles.mkdir()
        self.record = {'files_root': str(self.root), 'arguments': [f'-profiles={self.profiles}']}

    def _rpt(self, content: str, name: str = 'DayZServer_2026-11-09_06-08-04.RPT'):
        p = self.profiles / name
        p.write_text(content, encoding='utf-8')
        return p

    def test_known_linux_130_build_and_missing_shutdown_are_advisory(self):
        self._rpt('Version 1.30.164289.70\n'
                  '6:08:41 !!! [CE][offlineDB] :: No Shutdown message present.\n')
        result = suspected_linux_130_messages_issue(self.record)
        self.assertEqual('dayz_linux_130_messages_xml_suspected', result['code'])
        self.assertEqual('1.30.164289.70', result['version'])
        self.assertEqual('DZG-2653', result['upstream_issue'])

    def test_no_signature_or_unrelated_build_returns_no_warning(self):
        self._rpt('DayZ Console version (64bit) 1.30.164289.70\nMission read.\n')
        self.assertIsNone(suspected_linux_130_messages_issue(self.record))
        self._rpt('DayZ Console version (64bit) 1.31.164900.70\nNo Shutdown message present.\n')
        self.assertIsNone(suspected_linux_130_messages_issue(self.record))

    def test_no_access_outside_instance_private_root(self):
        with tempfile.TemporaryDirectory() as outside:
            other = Path(outside) / 'outside'
            other.mkdir()
            (other / 'DayZServer_2026-11-09_06-08-04.RPT').write_text(
                'DayZ Console version (64bit) 1.30.164289.70\nNo Shutdown message present.\n')
            record = {'files_root': str(self.root), 'arguments': [f'-profiles={other}']}
            self.assertIsNone(suspected_linux_130_messages_issue(record))
            (self.profiles / 'DayZServer_2026-11-09_06-08-04.RPT').symlink_to(
                other / 'DayZServer_2026-11-09_06-08-04.RPT')
            self.assertIsNone(suspected_linux_130_messages_issue(self.record))

    def test_missing_arguments_and_invalid_profile_paths_fail_closed(self):
        self.assertIsNone(suspected_linux_130_messages_issue({}))
        self.assertIsNone(suspected_linux_130_messages_issue(
            {'files_root': str(self.root), 'arguments': ['-profiles=../outside']}))

    def test_limit_read_to_first_256k_and_latest_report(self):
        old = self._rpt('DayZ Console version (64bit) 1.30.164289.70\n'
                        'No Shutdown message present.\n', 'DayZServer_2026-11-07_12-00-00.RPT')
        import os
        os.utime(old, (100, 100))
        self._rpt('DayZ Console version (64bit) 1.30.164289.70\nMission read.\n',
                  'DayZServer_2026-11-09_06-08-04.RPT')
        self.assertIsNone(suspected_linux_130_messages_issue(self.record))
        self._rpt('DayZ Console version (64bit) 1.30.164289.70\n' + 'a' * (256 * 1024)
                  + '\nNo Shutdown message present.\n')
        self.assertIsNone(suspected_linux_130_messages_issue(self.record))


if __name__ == '__main__':
    unittest.main()
