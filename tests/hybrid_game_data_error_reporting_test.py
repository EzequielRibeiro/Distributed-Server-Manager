"""The hybrid executor must retain actionable installer errors without a live install."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

EXECUTOR = Path(__file__).resolve().parents[1] / 'dashboard/workers/hybrid_game_data_executor.py'


class HybridErrorReportingTest(unittest.TestCase):
    def run_failure(self, output):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = root / 'installer' / 'install_selection.sh'
            installer.parent.mkdir(parents=True)
            installer.write_text('#!/bin/sh\nprintf "%s\\n" ' + ' '.join(
                "'" + line.replace("'", "'\\''") + "'" for line in output
            ) + '\nexit 1\n', encoding='utf-8')
            installer.chmod(0o755)
            request = root / 'request.json'
            result = root / 'result.json'
            request.write_text(json.dumps({'job_id': 'test-failure', 'action': 'update',
                'selection': {'provider': 'steam', 'game': 'dayz'}}), encoding='utf-8')
            completed = subprocess.run([sys.executable, str(EXECUTOR), str(root), str(request), str(result)],
                capture_output=True, text=True, timeout=15)
            self.assertNotEqual(completed.returncode, 0)
            return json.loads(result.read_text(encoding='utf-8'))

    def test_provider_error_survives_generic_trailer(self):
        result = self.run_failure(['[DSM][STEAM][ERRO] Autenticação Steam necessária ou expirada.',
            '[DSM][INSTALL-ERROR] action=install error=provider_install_failed status=healthy'])
        self.assertEqual(result['status'], 'failed')
        self.assertIn('Autenticação Steam necessária', result['error'])
        self.assertNotIn('provider_install_failed', result['error'])

    def test_secret_bearing_error_is_not_persisted(self):
        result = self.run_failure(['[DSM][STEAM][ERRO] password=DO_NOT_EXPOSE',
            '[DSM][INSTALL-ERROR] action=install error=provider_install_failed status=healthy'])
        self.assertNotIn('DO_NOT_EXPOSE', result['error'])
        self.assertIn('inspect protected job log', result['error'])

    def test_generic_failure_fallback(self):
        result = self.run_failure(['[DSM][INSTALL-ERROR] action=install error=provider_install_failed status=healthy'])
        self.assertIn('provider_install_failed', result['error'])


if __name__ == '__main__':
    unittest.main()
