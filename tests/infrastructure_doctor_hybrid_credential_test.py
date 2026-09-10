#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
if str(DATABASE) not in sys.path:
    sys.path.insert(0, str(DATABASE))

from infrastructure_doctor import _requires_permanent_agent_credential  # noqa: E402


class InfrastructureDoctorHybridCredentialTest(unittest.TestCase):
    def test_remote_agent_requires_permanent_credential(self) -> None:
        self.assertTrue(_requires_permanent_agent_credential("agent"))

    def test_hybrid_embedded_agent_does_not_require_remote_credential(self) -> None:
        self.assertFalse(_requires_permanent_agent_credential("hybrid"))

    def test_unknown_or_missing_role_does_not_suppress_credential_requirement(self) -> None:
        self.assertTrue(_requires_permanent_agent_credential(None))
        self.assertTrue(_requires_permanent_agent_credential(""))
        self.assertTrue(_requires_permanent_agent_credential("controller"))


if __name__ == "__main__":
    unittest.main()
