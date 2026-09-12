#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "dashboard" / "server.py"


class InstanceLifecycleHttpConflictTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SERVER.read_text(encoding="utf-8")

    def test_lifecycle_conflict_maps_to_http_409(self):
        marker = 'success, result = control_instance(user, instance, action)'
        block = self.source.split(marker, 1)[1].split('return', 1)[0]
        self.assertIn('result.get("error") == "lifecycle_operation_in_progress"', block)
        self.assertIn('409', block)
        self.assertIn('else 422', block)
        self.assertIn('self.send_json(status, result)', block)


if __name__ == "__main__":
    unittest.main()
