"""Verify jobs must never invoke the mutating install-json entry point."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

EXECUTOR = Path(__file__).resolve().parents[1] / "dashboard" / "workers" / "hybrid_game_data_executor.py"


class HybridVerifyFailClosedTest(unittest.TestCase):
    def test_verify_does_not_invoke_installer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installer = root / "installer" / "install_selection.sh"
            installer.parent.mkdir(parents=True)
            marker = root / "installer-was-called"
            installer.write_text("#!/bin/sh\ntouch " + str(marker) + "\n", encoding="utf-8")
            installer.chmod(0o755)
            request = root / "request.json"
            result = root / "result.json"
            request.write_text(json.dumps({
                "job_id": "game-data-test-verify",
                "action": "verify",
                "selection": {"kind": "RuntimeSelection", "game": "dayz", "provider": "steam"},
            }), encoding="utf-8")
            process = subprocess.run(
                [sys.executable, str(EXECUTOR), str(root), str(request), str(result)],
                capture_output=True, text=True, timeout=15,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertFalse(marker.exists())
            payload = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["error"], "read_only_version_probe_missing_metadata")


if __name__ == "__main__":
    unittest.main()
