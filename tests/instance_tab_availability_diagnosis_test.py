#!/usr/bin/env python3
"""Guard the customer tab lock against treating current health as historical recovery."""
from pathlib import Path
import unittest

SOURCE=(Path(__file__).resolve().parents[1]/"dashboard/web/instance-tab-availability.js").read_text()

class AvailabilityDiagnosisTests(unittest.TestCase):
    def test_verified_present_state_has_distinct_lock_reason(self):
        self.assertIn('provision?.current_runtime_diagnosis === "running_verified_installation_history_unresolved"', SOURCE)
        self.assertIn("histórico de instalação pendente de validação", SOURCE)
    def test_verified_present_state_never_bypasses_locked_status(self):
        self.assertIn('"failed",', SOURCE)
        self.assertIn('const locked = blocksOperationalViews(provision || {})', SOURCE)
        self.assertNotIn('current_runtime_diagnosis === "running_verified_installation_history_unresolved" && !locked', SOURCE)
if __name__ == "__main__":
    unittest.main()
