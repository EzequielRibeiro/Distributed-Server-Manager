#!/usr/bin/env python3
"""Contract tests for P8 consolidated administrative observability."""

from __future__ import annotations

import unittest

from dashboard.admin_observability_api import _count_by, _require_admin


class P8AdministrativeObservabilityContractTest(unittest.TestCase):
    def test_admin_and_controller_are_authorized(self):
        self.assertEqual(_require_admin({"role": "admin"})["role"], "admin")
        self.assertEqual(_require_admin({"role": "controller"})["role"], "controller")

    def test_customer_and_operator_are_denied(self):
        for role in ("customer", "operator", ""):
            with self.assertRaises(PermissionError):
                _require_admin({"role": role})

    def test_status_counts_are_deterministic(self):
        rows = [{"status": "online"}, {"status": "offline"}, {"status": "online"}, {}]
        self.assertEqual(_count_by(rows, "status"), {"offline": 1, "online": 2, "unknown": 1})


if __name__ == "__main__":
    unittest.main()
