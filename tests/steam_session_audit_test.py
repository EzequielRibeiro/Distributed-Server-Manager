#!/usr/bin/env python3
"""Steam session metadata audit privacy and change detection regression tests."""
from __future__ import annotations

import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / 'core' / 'steam_session_audit.py'
SPEC = importlib.util.spec_from_file_location('steam_session_audit', PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class SteamSessionAuditTest(unittest.TestCase):
    def test_missing_session_is_reported_without_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = module.snapshot(Path(tmp))
            self.assertTrue(all(x['state'] == 'absent' for x in result['files'].values()))
            self.assertNotIn('username', str(result).lower())

    def test_file_metadata_without_reading_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / module.SESSION_FILES[0]
            path.parent.mkdir(parents=True)
            path.write_text('ULTRA_PRIVATE_TOKEN', encoding='utf-8')
            path.chmod(0o640)
            result = module.snapshot(Path(tmp))['files'][module.SESSION_FILES[0]]
            self.assertEqual(result['state'], 'present')
            self.assertEqual(result['mode'], '0640')
            self.assertTrue(result['group_or_world_readable'])
            self.assertNotIn('ULTRA_PRIVATE_TOKEN', str(result))

    def test_permission_warning_and_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / module.SESSION_FILES[0]
            path.parent.mkdir(parents=True)
            path.write_text('not-a-real-token')
            path.chmod(0o600)
            before = module.snapshot(root)
            self.assertFalse(before['files'][module.SESSION_FILES[0]]['group_or_world_readable'])
            path.chmod(0o755)
            after = module.snapshot(root)
            self.assertTrue(after['files'][module.SESSION_FILES[0]]['group_or_world_readable'])
            self.assertEqual(module.compare(before, after)['changes'][module.SESSION_FILES[0]], 'changed')

    def test_intermediate_symlink_never_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'real').mkdir()
            (root / '.local').symlink_to(root / 'real', target_is_directory=True)
            result = module.snapshot(root)['files'][module.SESSION_FILES[0]]
            self.assertEqual(result['state'], 'intermediate_symlink')

    def test_final_symlink_never_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / module.SESSION_FILES[0]
            path.parent.mkdir(parents=True)
            (root / 'secret').write_text('NEVER_READ')
            path.symlink_to(root / 'secret')
            result = module.snapshot(root)['files'][module.SESSION_FILES[0]]
            self.assertEqual(result['state'], 'symlink')
            self.assertNotIn('NEVER_READ', str(result))


if __name__ == '__main__':
    unittest.main()
