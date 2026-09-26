#!/usr/bin/env python3
"""Verify the DayZ-only Customer tab uses the authenticated instance game."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

class CustomerDayzGameGateTest(unittest.TestCase):
    def test_main_overview_configures_game_specific_tab(self):
        main = (ROOT / "dashboard/web/customer-instance-v2.js").read_text(encoding="utf-8")
        dayz = (ROOT / "dashboard/web/customer-dayz.js").read_text(encoding="utf-8")
        self.assertIn("window.CapivaraInstanceDayz?.configure?.(overview)", main)
        self.assertIn('String(instance.id||"")!==iid', dayz)
        self.assertIn('toLowerCase()!=="dayz"', dayz)

    @unittest.skipUnless(shutil.which("node"), "Node.js not installed")
    def test_tab_visibility_and_api_are_game_gated(self):
        case = ROOT / "tests/customer_dayz_game_gate.test.js"
        result = subprocess.run(["node", str(case)], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout+"\n"+result.stderr)
        self.assertIn("PASS:", result.stdout)

if __name__=="__main__":
    unittest.main()
