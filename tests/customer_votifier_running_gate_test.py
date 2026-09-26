#!/usr/bin/env python3
"""Votifier optional-port management stays disabled while the game is active."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

class CustomerVotifierRunningGateTest(unittest.TestCase):
    def test_asset_is_cache_busted(self):
        html = (ROOT / "dashboard/web/customer-instance.html").read_text()
        wrapper = (ROOT / "dashboard/web/customer-instance-v2-wrapper.js").read_text()
        self.assertIn("/customer-instance-v2.js?v=23", html)
        self.assertIn("/customer-instance-connection.js?v=3", wrapper)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_active_unknown_stopped_and_failed_refresh_states(self):
        result = subprocess.run(
            ["node", "tests/customer_votifier_running_gate.test.js"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS:", result.stdout)

if __name__ == "__main__":
    unittest.main()
