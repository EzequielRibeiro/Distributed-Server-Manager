import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agents/linux/runtime'))
import systemd_journal_reader as reader

class BoundedJournalCaptureTest(unittest.TestCase):
    def test_subprocess_uses_file_sink_not_capture_output(self):
        def fake_run(args, **kwargs):
            self.assertNotIn('capture_output',kwargs)
            self.assertIsNotNone(kwargs['stdout'])
            kwargs['stdout'].write(b'')
            return type('Completed',(),{'returncode':0})()
        with patch.object(reader.subprocess,'run',side_effect=fake_run):
            self.assertEqual(reader.read_systemd_transitions('instance-test',since='2026-10-14T09:30:00Z',until='2026-10-14T09:31:00Z'),[])

    def test_large_journal_output_fails_closed(self):
        def fake_run(args, **kwargs):
            kwargs['stdout'].write(b'x'*(reader.MAX_OUTPUT_BYTES+1))
            return type('Completed',(),{'returncode':0})()
        with patch.object(reader.subprocess,'run',side_effect=fake_run):
            with self.assertRaisesRegex(ValueError,'too large'):
                reader.read_systemd_transitions('instance-test',since='2026-10-14T09:30:00Z',until='2026-10-14T09:31:00Z')

if __name__=='__main__':unittest.main()
