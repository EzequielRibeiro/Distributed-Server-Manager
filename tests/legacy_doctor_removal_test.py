#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for module_dir in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))

from infrastructure_http import dispatch_infrastructure_get


class LegacyDoctorRemovalTest(unittest.TestCase):
    def test_legacy_doctor_tree_is_removed(self):
        self.assertFalse((ROOT / "doctor").exists())

    def test_cap_exposes_only_infrastructure_doctor(self):
        cap = (ROOT / "bin" / "cap").read_text(encoding="utf-8")
        self.assertIn("cap infrastructure doctor", cap)
        self.assertNotIn("cap doctor ...", cap)
        self.assertNotIn("server|doctor|monitor", cap)

    def test_dashboard_shell_bridges_are_removed(self):
        bridge_paths = (
            ROOT / "dashboard" / "api" / "doctor.sh",
            ROOT / "dashboard" / "workers" / "doctor_worker.sh",
            ROOT / "dashboard" / "workers" / "collect_doctor.sh",
        )
        for path in bridge_paths:
            self.assertFalse(path.exists(), path)

    def test_dashboard_state_no_longer_depends_on_doctor_cache(self):
        server = (ROOT / "dashboard" / "server.py").read_text(encoding="utf-8")
        aggregate = (
            ROOT / "dashboard" / "workers" / "dashboard_worker.sh"
        ).read_text(encoding="utf-8")
        workers = (ROOT / "dashboard" / "workers" / "worker.sh").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("doctor_state.json", server)
        self.assertNotIn('"doctor": "doctor.sh"', server)
        self.assertNotIn('STATE.cached("doctor")', server)
        self.assertIn('path.startswith("/api/infrastructure")', server)
        self.assertNotIn("doctor_state.json", aggregate)
        self.assertNotIn("doctor_worker.sh", workers)

    def test_infrastructure_dispatcher_delegates_modern_doctor(self):
        expected = (200, {"kind": "CapivaraInfrastructureDoctor"})
        with patch(
            "infrastructure_http.dispatch_infrastructure_doctor_get",
            return_value=expected,
        ) as doctor_dispatch:
            result = dispatch_infrastructure_get(
                "/api/infrastructure/doctor",
                "",
                user={"role": "admin", "username": "admin"},
                backend=object(),
            )

        self.assertEqual(result, expected)
        doctor_dispatch.assert_called_once()

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
