#!/usr/bin/env python3

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LegacyDoctorRemovalTest(unittest.TestCase):
    def test_legacy_doctor_tree_is_removed(self):
        self.assertFalse((ROOT / "doctor").exists())

    def test_cap_exposes_only_infrastructure_doctor(self):
        cap = (ROOT / "bin" / "cap").read_text(encoding="utf-8")
        self.assertIn("cap infrastructure doctor", cap)
        self.assertNotIn("cap doctor ...", cap)
        self.assertNotIn("server|doctor|monitor", cap)

    def test_dsm_does_not_source_legacy_doctor(self):
        dsm = (ROOT / "bin" / "dsm").read_text(encoding="utf-8")
        self.assertNotIn("${DSM_ROOT}/doctor/", dsm)
        self.assertNotIn("doctor_run", dsm)
        self.assertNotIn("doctor_format_status", dsm)
        self.assertIn("O Doctor legado foi removido", dsm)
        self.assertIn("cap infrastructure doctor", dsm)

    def test_dashboard_bridge_contains_no_linuxgsm_checks(self):
        bridge_paths = (
            ROOT / "dashboard" / "api" / "doctor.sh",
            ROOT / "dashboard" / "workers" / "doctor_worker.sh",
            ROOT / "dashboard" / "workers" / "collect_doctor.sh",
        )
        for path in bridge_paths:
            text = path.read_text(encoding="utf-8").lower()
            self.assertNotIn("linuxgsm", text, path)
            self.assertNotIn("core/lgsm.sh", text, path)
            self.assertNotIn("lgsm_", text, path)

    def test_modern_doctor_components_remain(self):
        expected = (
            ROOT / "database" / "infrastructure_doctor.py",
            ROOT / "database" / "infrastructure_doctor_contract.py",
            ROOT / "dashboard" / "infrastructure_doctor_api.py",
            ROOT / "dashboard" / "infrastructure_doctor_http.py",
        )
        for path in expected:
            self.assertTrue(path.is_file(), path)


if __name__ == "__main__":
    unittest.main()
