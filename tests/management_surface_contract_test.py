#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ManagementSurfaceContractTest(unittest.TestCase):
    def test_expected_modules_exist(self):
        expected = [
            ROOT
            / "dashboard"
            / "management_surface_api.py",
            ROOT
            / "dashboard"
            / "placement_service.py",
            ROOT
            / "dashboard"
            / "region_preference_api.py",
            ROOT
            / "core"
            / "placement"
            / "region_preference.py",
        ]

        for path in expected:
            self.assertTrue(
                path.is_file(),
                str(path),
            )


if __name__ == "__main__":
    unittest.main()
